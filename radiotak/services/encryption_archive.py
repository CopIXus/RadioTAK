"""Encrypted traffic historical archive.

Preserves observed P25/DMR encryption metadata for authorized operators.
This is not a cracking engine: it never searches for unknown keys and never
stores traffic-key material.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import timedelta
from typing import Any

from sqlalchemy import Select, delete, desc, func, or_, select
from sqlalchemy.orm import Session

from radiotak.db import CaptureSession, EncryptedTrafficEvent, utcnow
from radiotak.gateway import DecodeEventIn
from radiotak.services.logging_setup import log_event
from radiotak.services.settings_store import load_settings_file
from radiotak.services.traffic_keys import (
    decrypt_state,
    describe_cipher,
    parse_message_indicator,
)

DEDUPE_SECONDS = 15
DEFAULT_RETENTION_DAYS = 365


def archive_settings() -> dict[str, Any]:
    cfg = load_settings_file().get("encryption_archive") or {}
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "metadata_retention_days": int(cfg.get("metadata_retention_days", DEFAULT_RETENTION_DAYS)),
        "raw_samples": bool(cfg.get("raw_samples", False)),
        "iq_enabled": bool(cfg.get("iq_enabled", False)),
    }


def current_session(db: Session, *, decoder_version: str | None = None) -> CaptureSession:
    row = db.scalar(
        select(CaptureSession)
        .where(CaptureSession.ended_at.is_(None))
        .order_by(desc(CaptureSession.started_at))
        .limit(1)
    )
    if row:
        return row
    from radiotak.services import updater as updater_svc

    row = CaptureSession(
        name="live",
        description="RadioTAK decoder capture session",
        software_version=updater_svc.current_version(),
        decoder_version=decoder_version,
        receiver="sdrtrunk",
    )
    db.add(row)
    db.flush()
    return row


def _raw_event_json(event: DecodeEventIn) -> dict[str, Any]:
    payload = event.model_dump(mode="json", by_alias=True)
    for secret in ("key_hex", "key", "traffic_key"):
        payload.pop(secret, None)
    return payload


def record_decode(
    db: Session,
    event: DecodeEventIn,
    *,
    algid: int | None,
    kid: int | None,
    key_loaded: bool,
) -> EncryptedTrafficEvent | None:
    """Persist a decode event. Failures must not affect realtime TAK ingest."""
    cfg = archive_settings()
    if not cfg["enabled"]:
        return None
    mi = parse_message_indicator(
        event.message_indicator, event.message_indicator_hex, event.details
    )
    state = decrypt_state(
        encrypted=event.encrypted, algid=algid, key_id=kid, key_loaded=key_loaded
    )
    now = event.observed_at
    window = now - timedelta(seconds=DEDUPE_SECONDS)
    existing = db.scalar(
        select(EncryptedTrafficEvent)
        .where(
            EncryptedTrafficEvent.source_radio_id == event.radio_id,
            EncryptedTrafficEvent.talkgroup_id == (event.talkgroup or None),
            EncryptedTrafficEvent.algorithm_id == algid,
            EncryptedTrafficEvent.key_id == kid,
            EncryptedTrafficEvent.encrypted.is_(event.encrypted),
            EncryptedTrafficEvent.observed_at >= window,
        )
        .order_by(desc(EncryptedTrafficEvent.observed_at))
        .limit(1)
    )
    if existing:
        existing.last_seen_at = now
        existing.hear_count = int(existing.hear_count or 1) + 1
        existing.key_loaded = existing.key_loaded or key_loaded
        existing.authorized_key_match = existing.authorized_key_match or key_loaded
        existing.decrypt_state = state
        if mi and not existing.message_indicator:
            existing.message_indicator = mi
        if event.system_id and not existing.system_id:
            existing.system_id = event.system_id
        if event.site_id and not existing.site_id:
            existing.site_id = event.site_id
        if event.frequency_hz and not existing.frequency_hz:
            existing.frequency_hz = event.frequency_hz
        db.commit()
        return existing

    session = current_session(db)
    row = EncryptedTrafficEvent(
        capture_session_id=session.id,
        observed_at=now,
        last_seen_at=now,
        hear_count=1,
        protocol=event.protocol,
        p25_phase=event.p25_phase,
        system_id=event.system_id,
        system_name=event.system_name,
        wacn=event.wacn,
        nac=event.nac,
        rfss=event.rfss,
        site_id=event.site_id,
        frequency_hz=event.frequency_hz,
        channel=event.channel,
        timeslot=event.timeslot,
        source_radio_id=event.radio_id,
        destination_radio_id=event.destination_radio_id,
        talkgroup_id=event.talkgroup,
        source_alias=event.source_alias,
        encrypted=event.encrypted,
        algorithm_id=algid,
        key_id=kid,
        message_indicator=mi,
        key_loaded=key_loaded,
        authorized_key_match=key_loaded,
        decrypt_state=state,
        duration_ms=event.duration_ms,
        raw_event_type=event.raw_event_type,
        details=event.details,
        raw_event_json=_raw_event_json(event),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    if event.encrypted:
        log_event(
            "encryption",
            "archived",
            detail=(
                f"radio={event.radio_id} tg={event.talkgroup or '-'} "
                f"algid={algid} kid={kid} state={state}"
            ),
        )
    return row


def _filtered_query(
    *,
    encrypted_only: bool = True,
    radio_id: str | None = None,
    talkgroup: str | None = None,
    algid: int | None = None,
    kid: int | None = None,
    site_id: str | None = None,
    system_id: str | None = None,
    decrypt_state_value: str | None = None,
    q: str | None = None,
    since=None,
) -> Select[tuple[EncryptedTrafficEvent]]:
    stmt = select(EncryptedTrafficEvent)
    if encrypted_only:
        stmt = stmt.where(EncryptedTrafficEvent.encrypted.is_(True))
    if radio_id:
        stmt = stmt.where(EncryptedTrafficEvent.source_radio_id == radio_id)
    if talkgroup:
        stmt = stmt.where(EncryptedTrafficEvent.talkgroup_id == talkgroup)
    if algid is not None:
        stmt = stmt.where(EncryptedTrafficEvent.algorithm_id == algid)
    if kid is not None:
        stmt = stmt.where(EncryptedTrafficEvent.key_id == kid)
    if site_id:
        stmt = stmt.where(EncryptedTrafficEvent.site_id == site_id)
    if system_id:
        stmt = stmt.where(EncryptedTrafficEvent.system_id == system_id)
    if decrypt_state_value:
        stmt = stmt.where(EncryptedTrafficEvent.decrypt_state == decrypt_state_value)
    if since is not None:
        stmt = stmt.where(EncryptedTrafficEvent.observed_at >= since)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                EncryptedTrafficEvent.source_radio_id.like(like),
                EncryptedTrafficEvent.talkgroup_id.like(like),
                EncryptedTrafficEvent.site_id.like(like),
                EncryptedTrafficEvent.system_id.like(like),
                EncryptedTrafficEvent.system_name.like(like),
                EncryptedTrafficEvent.decrypt_state.like(like),
                EncryptedTrafficEvent.message_indicator.like(like),
            )
        )
    return stmt.order_by(desc(EncryptedTrafficEvent.observed_at))


def list_events(
    db: Session,
    *,
    limit: int = 200,
    offset: int = 0,
    **filters: Any,
) -> list[EncryptedTrafficEvent]:
    stmt = _filtered_query(**filters).limit(max(1, min(limit, 2000))).offset(max(0, offset))
    return list(db.scalars(stmt))


def event_to_dict(row: EncryptedTrafficEvent) -> dict[str, Any]:
    cipher = describe_cipher(row.algorithm_id)
    return {
        "id": row.id,
        "capture_session_id": row.capture_session_id,
        "observed_at": row.observed_at.isoformat() if row.observed_at else None,
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        "hear_count": row.hear_count,
        "protocol": row.protocol,
        "p25_phase": row.p25_phase,
        "system_id": row.system_id,
        "system_name": row.system_name,
        "wacn": row.wacn,
        "nac": row.nac,
        "rfss": row.rfss,
        "site_id": row.site_id,
        "frequency_hz": row.frequency_hz,
        "frequency_mhz": round(row.frequency_hz / 1_000_000, 5) if row.frequency_hz else None,
        "channel": row.channel,
        "timeslot": row.timeslot,
        "source_radio_id": row.source_radio_id,
        "destination_radio_id": row.destination_radio_id,
        "talkgroup_id": row.talkgroup_id,
        "source_alias": row.source_alias,
        "encrypted": row.encrypted,
        "algorithm_id": row.algorithm_id,
        "algorithm_id_hex": cipher["algid_hex"],
        "algorithm_name": cipher["name"],
        "key_id": row.key_id,
        "message_indicator": row.message_indicator,
        "key_loaded": row.key_loaded,
        "authorized_key_match": row.authorized_key_match,
        "decrypt_state": row.decrypt_state,
        "duration_ms": row.duration_ms,
        "raw_event_type": row.raw_event_type,
        "details": row.details,
        "raw_event_json": row.raw_event_json,
    }


def stats(db: Session) -> dict[str, Any]:
    now = utcnow()
    enc = EncryptedTrafficEvent.encrypted.is_(True)
    total = db.scalar(select(func.count()).select_from(EncryptedTrafficEvent).where(enc)) or 0
    today = (
        db.scalar(
            select(func.count())
            .select_from(EncryptedTrafficEvent)
            .where(enc, EncryptedTrafficEvent.observed_at >= now - timedelta(days=1))
        )
        or 0
    )
    week = (
        db.scalar(
            select(func.count())
            .select_from(EncryptedTrafficEvent)
            .where(enc, EncryptedTrafficEvent.observed_at >= now - timedelta(days=7))
        )
        or 0
    )
    radios = (
        db.scalar(
            select(func.count(func.distinct(EncryptedTrafficEvent.source_radio_id))).where(enc)
        )
        or 0
    )
    talkgroups = (
        db.scalar(
            select(func.count(func.distinct(EncryptedTrafficEvent.talkgroup_id))).where(
                enc, EncryptedTrafficEvent.talkgroup_id.is_not(None)
            )
        )
        or 0
    )
    algids = list(
        db.scalars(
            select(EncryptedTrafficEvent.algorithm_id)
            .where(enc, EncryptedTrafficEvent.algorithm_id.is_not(None))
            .distinct()
        )
    )
    kids = list(
        db.scalars(
            select(EncryptedTrafficEvent.key_id)
            .where(enc, EncryptedTrafficEvent.key_id.is_not(None))
            .distinct()
        )
    )
    matched = (
        db.scalar(
            select(func.count())
            .select_from(EncryptedTrafficEvent)
            .where(enc, EncryptedTrafficEvent.authorized_key_match.is_(True))
        )
        or 0
    )
    unknown = (
        db.scalar(
            select(func.count())
            .select_from(EncryptedTrafficEvent)
            .where(
                enc,
                EncryptedTrafficEvent.decrypt_state.in_(
                    ("ENCRYPTED_KEY_NOT_AVAILABLE", "ENCRYPTED_METADATA_ONLY")
                ),
            )
        )
        or 0
    )
    newest = db.scalar(
        select(func.max(EncryptedTrafficEvent.observed_at)).where(enc)
    )
    oldest = db.scalar(
        select(func.min(EncryptedTrafficEvent.observed_at)).where(enc)
    )
    top_tgs = list(
        db.execute(
            select(
                EncryptedTrafficEvent.talkgroup_id,
                func.sum(EncryptedTrafficEvent.hear_count).label("hears"),
            )
            .where(enc, EncryptedTrafficEvent.talkgroup_id.is_not(None))
            .group_by(EncryptedTrafficEvent.talkgroup_id)
            .order_by(desc("hears"))
            .limit(8)
        )
    )
    top_kids = list(
        db.execute(
            select(
                EncryptedTrafficEvent.key_id,
                EncryptedTrafficEvent.algorithm_id,
                func.sum(EncryptedTrafficEvent.hear_count).label("hears"),
            )
            .where(enc, EncryptedTrafficEvent.key_id.is_not(None))
            .group_by(EncryptedTrafficEvent.key_id, EncryptedTrafficEvent.algorithm_id)
            .order_by(desc("hears"))
            .limit(8)
        )
    )
    return {
        "encrypted_events": int(total),
        "encrypted_24h": int(today),
        "encrypted_7d": int(week),
        "unique_encrypted_radios": int(radios),
        "unique_encrypted_talkgroups": int(talkgroups),
        "algids": [
            {"id": a, "hex": f"{a:02X}", "name": describe_cipher(a)["name"]}
            for a in algids
            if a is not None
        ],
        "kids": [int(k) for k in kids if k is not None],
        "authorized_matches": int(matched),
        "unknown_kids": int(unknown),
        "newest": newest.isoformat() if newest else None,
        "oldest": oldest.isoformat() if oldest else None,
        "top_talkgroups": [{"talkgroup": tg, "hears": int(n)} for tg, n in top_tgs],
        "top_kids": [
            {
                "key_id": int(kid),
                "algorithm_id": alg,
                "algorithm_hex": f"{alg:02X}" if alg is not None else None,
                "hears": int(n),
            }
            for kid, alg, n in top_kids
        ],
        "settings": archive_settings(),
    }


def export_events(
    db: Session,
    *,
    fmt: str = "jsonl",
    **filters: Any,
) -> tuple[str, str, bytes]:
    rows = [event_to_dict(r) for r in list_events(db, limit=5000, **filters)]
    fmt = (fmt or "jsonl").lower()
    stamp = utcnow().strftime("%Y-%m-%d")
    if fmt == "csv":
        buf = io.StringIO()
        fields = [
            "observed_at",
            "source_radio_id",
            "talkgroup_id",
            "system_id",
            "site_id",
            "wacn",
            "nac",
            "frequency_mhz",
            "timeslot",
            "algorithm_id_hex",
            "algorithm_name",
            "key_id",
            "message_indicator",
            "decrypt_state",
            "authorized_key_match",
            "hear_count",
        ]
        writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return (
            f"radiotak-encrypted-{stamp}.csv",
            "text/csv",
            buf.getvalue().encode("utf-8"),
        )
    if fmt == "json":
        body = json.dumps(
            {
                "export_format_version": 1,
                "exported_at": utcnow().isoformat(),
                "note": "Metadata only. Authorized traffic keys are not included.",
                "count": len(rows),
                "events": rows,
            },
            indent=2,
        )
        return f"radiotak-encrypted-{stamp}.json", "application/json", body.encode("utf-8")
    lines = "\n".join(json.dumps(row, default=str) for row in rows) + ("\n" if rows else "")
    return (
        f"radiotak-encrypted-{stamp}.jsonl",
        "application/jsonl",
        lines.encode("utf-8"),
    )


def purge_expired(db: Session) -> int:
    cfg = archive_settings()
    days = int(cfg["metadata_retention_days"])
    cutoff = utcnow() - timedelta(days=days)
    result = db.execute(
        delete(EncryptedTrafficEvent).where(EncryptedTrafficEvent.observed_at < cutoff)
    )
    db.commit()
    count = result.rowcount or 0
    if count:
        log_event("encryption", "retention_purge", detail=f"removed={count} days={days}")
    return count
