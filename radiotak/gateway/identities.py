"""Radio identity lookup and allowlist helpers."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from radiotak.db import RadioIdentity, utcnow
from radiotak.services.settings_store import load_settings_file


def find_identity(db: Session, radio_id: str, system_id: str | None = None) -> RadioIdentity | None:
    stmt = select(RadioIdentity).where(RadioIdentity.radio_id == radio_id)
    if system_id:
        stmt = stmt.where(
            (RadioIdentity.system_id == system_id) | (RadioIdentity.system_id.is_(None))
        )
    rows = list(db.scalars(stmt))
    if not rows:
        return None
    for row in rows:
        if system_id and row.system_id == system_id:
            return row
    return rows[0]


def observe_or_create(
    db: Session,
    radio_id: str,
    system_id: str | None = None,
    alias: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> RadioIdentity:
    identity = find_identity(db, radio_id, system_id)
    if identity is None:
        identity = RadioIdentity(
            radio_id=radio_id,
            system_id=system_id,
            enabled=True,
            forward_to_tak=False,
            callsign=alias,
            display_name=alias,
        )
        db.add(identity)
    identity.observation_count = (identity.observation_count or 0) + 1
    identity.last_observed_at = utcnow()
    if lat is not None:
        identity.last_latitude = lat
        identity.last_gps_at = utcnow()
    if lon is not None:
        identity.last_longitude = lon
    if alias and not identity.callsign:
        identity.callsign = alias
    db.commit()
    db.refresh(identity)
    return identity


def observe_call(
    db: Session,
    *,
    radio_id: str,
    system_id: str | None = None,
    alias: str | None = None,
    talkgroup: str | None = None,
    encrypted: bool = False,
    algorithm_id: str | None = None,
    key_id: str | None = None,
    key_loaded: bool = False,
) -> RadioIdentity:
    """Record a voice/data call that may not include GPS."""
    identity = observe_or_create(db, radio_id=radio_id, system_id=system_id, alias=alias)
    identity.last_call_at = utcnow()
    if talkgroup:
        identity.last_talkgroup_id = talkgroup
    identity.last_encrypted = bool(encrypted)
    if encrypted:
        identity.last_encryption_algorithm = algorithm_id
        identity.last_encryption_key_id = key_id
        identity.last_key_loaded = bool(key_loaded)
    else:
        identity.last_encryption_algorithm = None
        identity.last_encryption_key_id = None
        identity.last_key_loaded = False
    db.commit()
    db.refresh(identity)
    return identity


def hear_status(identity: RadioIdentity) -> dict:
    """Operator-facing GPS vs encrypted-vs-silent decoder state."""
    has_gps = identity.last_latitude is not None and identity.last_longitude is not None
    encrypted = bool(getattr(identity, "last_encrypted", False))
    key_loaded = bool(getattr(identity, "last_key_loaded", False))
    tg = getattr(identity, "last_talkgroup_id", None)
    gps = f"{identity.last_latitude:.5f}, {identity.last_longitude:.5f}" if has_gps else None
    if encrypted and not has_gps:
        label = f"Encrypted TG {tg} — no GPS" if tg else "Encrypted — no GPS"
        if key_loaded:
            label += " (key on file)"
        kind = "encrypted"
    elif encrypted and has_gps:
        label = gps or "—"
        kind = "encrypted-gps"
    elif has_gps:
        label = gps or "—"
        kind = "gps"
    elif getattr(identity, "last_call_at", None) or identity.last_observed_at:
        label = f"Heard TG {tg} — no GPS" if tg else "Heard — no GPS"
        kind = "heard"
    else:
        label = "—"
        kind = "none"
    return {
        "hear_kind": kind,
        "hear_label": label,
        "last_talkgroup_id": tg,
        "last_encrypted": encrypted,
        "last_key_loaded": key_loaded,
        "last_encryption_algorithm": getattr(identity, "last_encryption_algorithm", None),
        "last_encryption_key_id": getattr(identity, "last_encryption_key_id", None),
        "has_gps": has_gps,
    }


def is_forward_allowed(identity: RadioIdentity | None) -> tuple[bool, str]:
    if identity is None:
        mode = (load_settings_file().get("forwarding") or {}).get("unknown_radios", "deny")
        if mode == "observe":
            return False, "RADIO OBSERVE ONLY"
        return False, "RADIO NOT APPROVED"
    if not identity.enabled:
        return False, "RADIO DISABLED"
    if not identity.forward_to_tak:
        return False, "RADIO NOT APPROVED"
    return True, "OK"
