"""TAK connection lifecycle — start managers for configured servers."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select

from radiotak.db import TakServer, get_session_factory
from radiotak.gateway.constants import DEFAULT_STALE_SECONDS
from radiotak.gateway.tak import TakConnectionManager, tak_registry
from radiotak.services.settings_store import load_settings_file
from radiotak.services.updater import current_version

log = logging.getLogger("radiotak.tak_runtime")


def _manager_for(server: TakServer) -> TakConnectionManager:
    cert = server.client_cert_path
    key = server.client_key_path
    has_certs = bool(cert and key and Path(cert).exists() and Path(key).exists())
    ca_path = server.server_ca_path
    if not ca_path:
        candidate = Path(cert).parent / "ca.pem" if cert else None
        if candidate and candidate.exists():
            ca_path = str(candidate)
    fwd = (load_settings_file().get("forwarding") or {})
    stale = float(fwd.get("stale_seconds") or DEFAULT_STALE_SECONDS)
    device_uid = server.device_uid or f"RadioTAK-{server.id[:8]}"
    groups = list(server.active_groups or [])
    return TakConnectionManager(
        server_id=server.id,
        host=server.host,
        cot_port=server.cot_port or 8089,
        api_port=server.api_port or 8443,
        callsign=server.callsign or "RadioTAK",
        device_uid=device_uid,
        cert_path=cert if has_certs else None,
        key_path=key if has_certs else None,
        ca_path=ca_path,
        tls_verify=bool(server.tls_verify),
        dry_run=not has_certs,
        active_groups=groups,
        presence_lat=float(server.presence_lat or 0.0),
        presence_lon=float(server.presence_lon or 0.0),
        app_version=current_version(),
        stale_drop_seconds=max(stale, 60.0),
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
            if not server.device_uid:
                server.device_uid = f"RadioTAK-{server.id[:8]}"
            if server.last_error and "activebits" in server.last_error:
                server.last_error = None
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


async def restart(server_id: str) -> TakConnectionManager | None:
    Session = get_session_factory()
    db = Session()
    try:
        server = db.get(TakServer, server_id)
        if not server:
            return None
        if not server.device_uid:
            server.device_uid = f"RadioTAK-{server.id[:8]}"
        if server.last_error and "activebits" in server.last_error:
            server.last_error = None
        mgr = _manager_for(server)
        await tak_registry.replace(mgr)
        await mgr.start()
        server.status = mgr.state.value
        db.commit()
        return mgr
    finally:
        db.close()
