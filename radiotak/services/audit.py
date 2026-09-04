"""Audit log helpers."""

from __future__ import annotations

import logging
from typing import Any, Optional

from radiotak.db import AuditLog, get_session_factory, utcnow

log = logging.getLogger("radiotak.audit")


def write_audit(
    action: str,
    *,
    actor: str = "",
    detail: Optional[dict[str, Any]] = None,
    target: str = "",
) -> None:
    try:
        Session = get_session_factory()
        db = Session()
        try:
            row = AuditLog(
                action=action,
                actor=actor or None,
                target=target or None,
                detail=detail or {},
                created_at=utcnow(),
            )
            db.add(row)
            db.commit()
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001
        log.warning("audit write failed for %s: %s", action, exc)


def recent_audit(limit: int = 50) -> list[dict[str, Any]]:
    Session = get_session_factory()
    db = Session()
    try:
        from sqlalchemy import select

        rows = list(db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)))
        out = []
        for r in rows:
            out.append(
                {
                    "id": r.id,
                    "action": r.action,
                    "actor": r.actor,
                    "target": r.target,
                    "detail": r.detail,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
            )
        return out
    finally:
        db.close()
