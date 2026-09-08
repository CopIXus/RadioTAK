"""Operator-initiated wipe of heard radios and encryption metadata."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from radiotak.db import (
    EncryptedTrafficEvent,
    ForwardingEvent,
    LocationObservation,
    RadioIdentity,
)
from radiotak.gateway.events import event_bus
from radiotak.services.logging_setup import log_event


def clear_heard_history(
    db: Session,
    *,
    observed: bool = True,
    encryption: bool = True,
    live_events: bool = True,
) -> dict[str, int]:
    """Delete historical heard data. Approved units and traffic keys are kept."""
    counts = {
        "observed": 0,
        "encryption": 0,
        "locations": 0,
        "forwarding": 0,
        "live_events": 0,
    }
    if observed:
        rows = list(
            db.scalars(select(RadioIdentity).where(RadioIdentity.forward_to_tak.is_(False)))
        )
        radio_ids = [row.radio_id for row in rows]
        if radio_ids:
            obs_ids = list(
                db.scalars(
                    select(LocationObservation.id).where(
                        LocationObservation.radio_id.in_(radio_ids)
                    )
                )
            )
            if obs_ids:
                fwd = db.execute(
                    delete(ForwardingEvent).where(ForwardingEvent.observation_id.in_(obs_ids))
                )
                counts["forwarding"] = fwd.rowcount or 0
                loc = db.execute(
                    delete(LocationObservation).where(LocationObservation.id.in_(obs_ids))
                )
                counts["locations"] = loc.rowcount or 0
        for row in rows:
            db.delete(row)
        counts["observed"] = len(rows)
    if encryption:
        enc = db.execute(delete(EncryptedTrafficEvent))
        counts["encryption"] = enc.rowcount or 0
    db.commit()
    if live_events:
        counts["live_events"] = len(event_bus.history)
        event_bus.clear()
    log_event("heard", "history_cleared", detail=str(counts))
    return counts
