"""Radio identity lookup and allowlist helpers."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from radiotak.db import RadioIdentity, utcnow
from radiotak.services.settings_store import load_settings_file


def find_identity(
    db: Session, radio_id: str, system_id: Optional[str] = None
) -> Optional[RadioIdentity]:
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
    system_id: Optional[str] = None,
    alias: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
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
    if lon is not None:
        identity.last_longitude = lon
    if alias and not identity.callsign:
        identity.callsign = alias
    db.commit()
    db.refresh(identity)
    return identity


def is_forward_allowed(identity: Optional[RadioIdentity]) -> tuple[bool, str]:
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
