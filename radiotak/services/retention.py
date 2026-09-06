"""Retention / purge jobs."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete

from radiotak.db import (
    AuditLog,
    ForwardingEvent,
    LocationObservation,
    get_session_factory,
    utcnow,
)
from radiotak.services.logging_setup import log_event
from radiotak.services.settings_store import load_settings_file


def purge_old_records() -> dict[str, int]:
    data = load_settings_file()
    Session = get_session_factory()
    db = Session()
    counts = {"observations": 0, "events": 0, "audit": 0}
    try:
        now = utcnow()
        obs_days = int(data.get("observation_retention_days", 7))
        event_days = int(data.get("event_retention_days", 1))
        audit_days = int(data.get("audit_retention_days", 30))

        r = db.execute(
            delete(LocationObservation).where(
                LocationObservation.received_at < now - timedelta(days=obs_days)
            )
        )
        counts["observations"] = r.rowcount or 0
        r = db.execute(
            delete(ForwardingEvent).where(
                ForwardingEvent.created_at < now - timedelta(days=max(event_days, obs_days))
            )
        )
        counts["events"] = r.rowcount or 0
        r = db.execute(
            delete(AuditLog).where(AuditLog.created_at < now - timedelta(days=audit_days))
        )
        counts["audit"] = r.rowcount or 0
        try:
            from radiotak.services.encryption_archive import purge_expired

            counts["encrypted_archive"] = purge_expired(db)
        except Exception as exc:  # noqa: BLE001
            log_event("retention", "archive_purge_failed", detail=str(exc))
            counts["encrypted_archive"] = 0
        db.commit()
        log_event("retention", "purge_complete", detail=str(counts))
    finally:
        db.close()
    return counts
