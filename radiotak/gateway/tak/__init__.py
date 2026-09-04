"""TAK connection manager (PyTAK-backed with mock mode for tests/dev)."""

from __future__ import annotations

import asyncio
import logging
import ssl
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from radiotak.gateway.constants import (
    DEFAULT_STALE_SECONDS,
    PRESENCE_INTERVAL_SECONDS,
    PRESENCE_STALE_SECONDS,
)
from radiotak.gateway.cot import build_disconnect_xml, build_presence_xml

log = logging.getLogger("radiotak.tak")


def build_tak_ssl_context(
    *,
    ca_path: str | None = None,
    tls_verify: bool = True,
    cert_path: str | None = None,
    key_path: str | None = None,
) -> ssl.SSLContext:
    """mTLS context for TAK CoT streaming (port 8089).

    TAK Server's streaming cert is almost never issued for the public FQDN
    operators type (Caddy/infra hostname vs TAK keystore CN). When the enrolled
    TAK CA is present, verify the chain against that CA and skip hostname
    matching. That matches ATAK/iTAK data-package behavior.
    """
    if ca_path:
        ctx = ssl.create_default_context(cafile=ca_path)
    else:
        ctx = ssl.create_default_context()
    ctx.check_hostname = False
    if tls_verify and ca_path:
        ctx.verify_mode = ssl.CERT_REQUIRED
    else:
        ctx.verify_mode = ssl.CERT_NONE
        if tls_verify and not ca_path:
            log.warning(
                "TAK TLS verify requested but no server CA is stored; skipping verification"
            )
    if cert_path and key_path:
        ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
    return ctx


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    CERTIFICATE_ERROR = "certificate_error"
    AUTH_ERROR = "auth_error"
    DNS_ERROR = "dns_error"
    TLS_ERROR = "tls_error"


@dataclass
class QueuedCot:
    xml: str
    uid: str
    enqueued_at: float
    observation_id: str | None = None


@dataclass
class TakMetrics:
    cot_generated: int = 0
    cot_sent: int = 0
    cot_dropped: int = 0
    connection_attempts: int = 0
    last_successful_send: datetime | None = None
    last_latency_ms: int | None = None


@dataclass
class TakConnectionManager:
    server_id: str
    host: str
    cot_port: int = 8089
    api_port: int = 8443
    callsign: str = "RadioTAK"
    device_uid: str | None = None
    cert_path: str | None = None
    key_path: str | None = None
    ca_path: str | None = None
    tls_verify: bool = True
    reconnect_min: float = 2.0
    reconnect_max: float = 60.0
    queue_max: int = 200
    stale_drop_seconds: float = float(DEFAULT_STALE_SECONDS)
    dry_run: bool = False  # when True, "send" succeeds without network
    active_groups: list[str] = field(default_factory=list)
    presence_lat: float = 0.0
    presence_lon: float = 0.0
    app_version: str = "0.0.0"

    state: ConnectionState = ConnectionState.DISCONNECTED
    last_error: str | None = None
    metrics: TakMetrics = field(default_factory=TakMetrics)
    _queue: deque[QueuedCot] = field(default_factory=deque)
    _task: asyncio.Task | None = None
    _stop: asyncio.Event = field(default_factory=asyncio.Event)

    def presence_uid(self) -> str:
        return self.device_uid or f"RadioTAK-{self.server_id[:8]}"

    def _presence_xml(self) -> str:
        groups = [g for g in (self.active_groups or []) if g]
        return build_presence_xml(
            uid=self.presence_uid(),
            callsign=self.callsign or "RadioTAK",
            latitude=self.presence_lat or 0.0,
            longitude=self.presence_lon or 0.0,
            stale_seconds=PRESENCE_STALE_SECONDS,
            group_name=groups[0] if groups else None,
            version=self.app_version,
        )

    def enqueue(self, xml: str, uid: str, observation_id: str | None = None) -> None:
        self.metrics.cot_generated += 1
        if len(self._queue) >= self.queue_max:
            self._queue.popleft()
            self.metrics.cot_dropped += 1
        self._queue.append(
            QueuedCot(xml=xml, uid=uid, enqueued_at=time.time(), observation_id=observation_id)
        )

    async def start(self) -> None:
        self._stop.clear()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name=f"tak-{self.server_id}")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await asyncio.wait([self._task], timeout=5)
        self.state = ConnectionState.DISCONNECTED

    async def _run(self) -> None:
        delay = self.reconnect_min
        while not self._stop.is_set():
            try:
                self.state = ConnectionState.CONNECTING
                self.metrics.connection_attempts += 1
                await self._connect_and_pump()
                delay = self.reconnect_min
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)
                self.state = ConnectionState.TLS_ERROR
                log.warning("TAK %s error: %s", self.server_id, exc)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.reconnect_max)

    async def _apply_groups(self) -> None:
        if not self.active_groups or not self.cert_path or not self.key_path:
            return
        try:
            from radiotak.gateway.tak.marti import set_active_groups

            await set_active_groups(
                self.host,
                list(self.active_groups),
                api_port=self.api_port,
                client_uid=self.presence_uid(),
                cert=(self.cert_path, self.key_path),
                verify=False,
            )
            log.info("Marti groups applied for %s uid=%s", self.server_id, self.presence_uid())
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "Marti groups apply failed for %s (will retry on reconnect): %s",
                self.server_id,
                exc,
            )

    def _mark_sent(self, latency_ms: int = 1) -> None:
        self.metrics.cot_sent += 1
        self.metrics.last_successful_send = datetime.now(UTC)
        self.metrics.last_latency_ms = latency_ms

    async def _drain_queue(self, writer=None) -> None:  # noqa: ANN001
        if not self._queue:
            return
        item = self._queue.popleft()
        if time.time() - item.enqueued_at > self.stale_drop_seconds:
            self.metrics.cot_dropped += 1
            return
        t0 = time.time()
        if writer is not None:
            writer.write(item.xml.encode("utf-8") + b"\n")
            await writer.drain()
        self._mark_sent(int((time.time() - t0) * 1000) or 1)

    async def _write_xml(self, xml: str, writer=None) -> None:  # noqa: ANN001
        t0 = time.time()
        if writer is not None:
            writer.write(xml.encode("utf-8") + b"\n")
            await writer.drain()
        self.metrics.cot_generated += 1
        self._mark_sent(int((time.time() - t0) * 1000) or 1)

    async def _connect_and_pump(self) -> None:
        if self.dry_run or not self.host:
            self.state = ConnectionState.CONNECTED
            self.last_error = None
            last_presence = 0.0
            while not self._stop.is_set():
                now = time.monotonic()
                if now - last_presence >= PRESENCE_INTERVAL_SECONDS:
                    await self._write_xml(self._presence_xml())
                    last_presence = now
                await self._drain_queue()
                await asyncio.sleep(0.05)
            return

        try:
            import pytak  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("pytak not installed") from exc

        ctx = build_tak_ssl_context(
            ca_path=self.ca_path,
            tls_verify=self.tls_verify,
            cert_path=self.cert_path,
            key_path=self.key_path,
        )

        try:
            reader, writer = await asyncio.open_connection(self.host, self.cot_port, ssl=ctx)
        except ssl.SSLCertVerificationError as exc:
            raise RuntimeError(
                "TAK Server certificate was rejected. The streaming cert on port "
                f"{self.cot_port} is often issued for an internal name, not '{self.host}'. "
                "RadioTAK trusts the enrolled TAK CA without hostname matching when ca.pem "
                f"is present. {exc}"
            ) from exc
        except ssl.SSLError as exc:
            raise RuntimeError(
                f"TLS handshake with {self.host}:{self.cot_port} failed: {exc}"
            ) from exc
        self.state = ConnectionState.CONNECTED
        self.last_error = None
        try:
            await self._write_xml(self._presence_xml(), writer)
            await self._apply_groups()
            await self._write_xml(self._presence_xml(), writer)
            last_presence = time.monotonic()
            while not self._stop.is_set():
                now = time.monotonic()
                if now - last_presence >= PRESENCE_INTERVAL_SECONDS:
                    await self._write_xml(self._presence_xml(), writer)
                    last_presence = now
                await self._drain_queue(writer)
                await asyncio.sleep(0.05)
        finally:
            try:
                await self._write_xml(
                    build_disconnect_xml(
                        uid=self.presence_uid(), callsign=self.callsign or "RadioTAK"
                    ),
                    writer,
                )
            except Exception:  # noqa: BLE001
                pass
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass


class TakManagerRegistry:
    def __init__(self) -> None:
        self._managers: dict[str, TakConnectionManager] = {}

    def get(self, server_id: str) -> TakConnectionManager | None:
        return self._managers.get(server_id)

    def upsert(self, manager: TakConnectionManager) -> TakConnectionManager:
        existing = self._managers.get(manager.server_id)
        if existing:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(existing.stop())
            except RuntimeError:
                pass
        self._managers[manager.server_id] = manager
        return manager

    async def replace(self, manager: TakConnectionManager) -> TakConnectionManager:
        existing = self._managers.get(manager.server_id)
        if existing:
            await existing.stop()
        self._managers[manager.server_id] = manager
        return manager

    def all(self) -> list[TakConnectionManager]:
        return list(self._managers.values())

    async def stop_all(self) -> None:
        for mgr in list(self._managers.values()):
            try:
                await mgr.stop()
            except Exception:  # noqa: BLE001
                pass
        self._managers.clear()

    def enqueue_all(self, xml: str, uid: str, observation_id: str | None = None) -> int:
        n = 0
        for mgr in self._managers.values():
            if mgr.state != ConnectionState.DISCONNECTED or mgr.dry_run:
                mgr.enqueue(xml, uid, observation_id)
                n += 1
            elif mgr.host:
                mgr.enqueue(xml, uid, observation_id)
                n += 1
        return n

    def enqueue_for(
        self, server_id: str, xml: str, uid: str, observation_id: str | None = None
    ) -> bool:
        mgr = self._managers.get(server_id)
        if not mgr:
            return False
        mgr.enqueue(xml, uid, observation_id)
        return True


tak_registry = TakManagerRegistry()
