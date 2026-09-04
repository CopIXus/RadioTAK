"""TAK connection manager (PyTAK-backed with mock mode for tests/dev)."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

log = logging.getLogger("radiotak.tak")


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
    observation_id: Optional[str] = None


@dataclass
class TakMetrics:
    cot_generated: int = 0
    cot_sent: int = 0
    cot_dropped: int = 0
    connection_attempts: int = 0
    last_successful_send: Optional[datetime] = None
    last_latency_ms: Optional[int] = None


@dataclass
class TakConnectionManager:
    server_id: str
    host: str
    cot_port: int = 8089
    callsign: str = "RadioTAK"
    device_uid: Optional[str] = None
    cert_path: Optional[str] = None
    key_path: Optional[str] = None
    ca_path: Optional[str] = None
    tls_verify: bool = True
    reconnect_min: float = 2.0
    reconnect_max: float = 60.0
    queue_max: int = 200
    stale_drop_seconds: float = 120.0
    dry_run: bool = False  # when True, "send" succeeds without network

    state: ConnectionState = ConnectionState.DISCONNECTED
    last_error: Optional[str] = None
    metrics: TakMetrics = field(default_factory=TakMetrics)
    _queue: deque[QueuedCot] = field(default_factory=deque)
    _task: Optional[asyncio.Task] = None
    _stop: asyncio.Event = field(default_factory=asyncio.Event)

    def enqueue(self, xml: str, uid: str, observation_id: Optional[str] = None) -> None:
        import time

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

    async def _connect_and_pump(self) -> None:
        import time

        if self.dry_run or not self.host:
            self.state = ConnectionState.CONNECTED
            self.last_error = None
            while not self._stop.is_set():
                if self._queue:
                    item = self._queue.popleft()
                    if time.time() - item.enqueued_at > self.stale_drop_seconds:
                        self.metrics.cot_dropped += 1
                        continue
                    # dry-run send
                    self.metrics.cot_sent += 1
                    self.metrics.last_successful_send = datetime.now(timezone.utc)
                    self.metrics.last_latency_ms = 1
                await asyncio.sleep(0.05)
            return

        # Live path using PyTAK when credentials exist
        try:
            import pytak  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("pytak not installed") from exc

        # Minimal TLS send loop — full PyTAK QueueWorker wiring can be expanded later.
        # For MVP with certs present, use asyncio open_connection with SSL context.
        import ssl

        ctx = ssl.create_default_context(cafile=self.ca_path) if self.ca_path else ssl.create_default_context()
        if not self.tls_verify:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        if self.cert_path and self.key_path:
            ctx.load_cert_chain(certfile=self.cert_path, keyfile=self.key_path)

        reader, writer = await asyncio.open_connection(self.host, self.cot_port, ssl=ctx)
        self.state = ConnectionState.CONNECTED
        self.last_error = None
        try:
            while not self._stop.is_set():
                if self._queue:
                    item = self._queue.popleft()
                    if time.time() - item.enqueued_at > self.stale_drop_seconds:
                        self.metrics.cot_dropped += 1
                        continue
                    t0 = time.time()
                    writer.write(item.xml.encode("utf-8") + b"\n")
                    await writer.drain()
                    self.metrics.cot_sent += 1
                    self.metrics.last_successful_send = datetime.now(timezone.utc)
                    self.metrics.last_latency_ms = int((time.time() - t0) * 1000)
                await asyncio.sleep(0.05)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass


class TakManagerRegistry:
    def __init__(self) -> None:
        self._managers: dict[str, TakConnectionManager] = {}

    def get(self, server_id: str) -> Optional[TakConnectionManager]:
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

    def enqueue_all(self, xml: str, uid: str, observation_id: Optional[str] = None) -> int:
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
        self, server_id: str, xml: str, uid: str, observation_id: Optional[str] = None
    ) -> bool:
        mgr = self._managers.get(server_id)
        if not mgr:
            return False
        mgr.enqueue(xml, uid, observation_id)
        return True


tak_registry = TakManagerRegistry()
