"""TAK connection lifecycle — start managers for configured servers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from sqlalchemy import select

from radiotak.db import TakServer, get_session_factory
from radiotak.gateway.tak import TakConnectionManager, tak_registry

log = logging.getLogger("radiotak.tak_runtime")


def _manager_for(server: TakServer) -> TakConnectionManager:
    cert = server.client_cert_path
    key = server.client_key_path
    has_certs = bool(cert and key and Path(cert).exists() and Path(key).exists())
    return TakConnectionManager(
        server_id=server.id,
        host=server.host,
        cot_port=server.cot_port or 8089,
        callsign=server.callsign or server.default_callsign or "RadioTAK",
        device_uid=server.device_uid,
        cert_path=cert if has_certs else None,
        key_path=key if has_certs else None,
        ca_path=server.server_ca_path,
        tls_verify=bool(server.tls_verify),
        dry_run=not has_certs,
    )


async def start_all() -> int:
    Session = get_session_factory()
    db = Session()
    started = 0
    try:
        servers = list(db.scalars(select(TakServer).where(TakServer.enabled.is_(True))))
        for server in servers:
            if not server.auto_connect:
                continue
            mgr = _manager_for(server)
            await tak_registry.replace(mgr)
            await mgr.start()
            server.status = mgr.state.value
            started += 1
            log.info("TAK manager started for %s (%s) dry_run=%s", server.name, server.id, mgr.dry_run)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("tak_runtime.start_all failed: %s", exc)
    finally:
        db.close()
    return started


async def stop_all() -> None:
    await tak_registry.stop_all()


async def restart(server_id: str) -> Optional[TakConnectionManager]:
    Session = get_session_factory()
    db = Session()
    try:
        server = db.get(TakServer, server_id)
        if not server:
            return None
        mgr = _manager_for(server)
        await tak_registry.replace(mgr)
        await mgr.start()
        server.status = mgr.state.value
        db.commit()
        return mgr
    finally:
        db.close()
