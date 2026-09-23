"""Minimal KISS TCP client and AX.25 UI → TNC2 line conversion."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable

FEND = 0xC0
FESC = 0xDB
TFEND = 0xDC
TFESC = 0xDD


class KissDecoder:
    """Incremental KISS frame unescaper."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self._in_frame = False
        self._esc = False

    def feed(self, data: bytes) -> list[bytes]:
        frames: list[bytes] = []
        for b in data:
            if not self._in_frame:
                if b == FEND:
                    self._in_frame = True
                    self._buf.clear()
                    self._esc = False
                continue
            if self._esc:
                if b == TFEND:
                    self._buf.append(FEND)
                elif b == TFESC:
                    self._buf.append(FESC)
                else:
                    self._buf.append(b)
                self._esc = False
                continue
            if b == FESC:
                self._esc = True
                continue
            if b == FEND:
                if self._buf:
                    frames.append(bytes(self._buf))
                self._buf.clear()
                continue
            self._buf.append(b)
        return frames


def _ax25_addr(raw: bytes) -> tuple[str, int, bool]:
    """Decode one 7-byte AX.25 address → (call-SSID, ssid, address_extension_end)."""
    if len(raw) < 7:
        return "", 0, True
    call = "".join(chr((b >> 1) & 0x7F) for b in raw[:6]).strip()
    ssid_byte = raw[6]
    ssid = (ssid_byte >> 1) & 0x0F
    end = bool(ssid_byte & 0x01)
    if ssid:
        return f"{call}-{ssid}", ssid, end
    return call, ssid, end


def ax25_ui_to_tnc2(frame: bytes) -> str | None:
    """Convert a KISS payload (command byte stripped) AX.25 UI frame to TNC2 text."""
    if len(frame) < 16:
        return None
    # Skip KISS command/port nibble if still present (0x00 for data on port 0)
    offset = 0
    if frame[0] in (0x00, 0x10, 0x20, 0x30):
        # Heuristic: real AX.25 address bytes are even (shifted ASCII). Command 0x00 is common.
        # Prefer treating first byte as KISS cmd when second byte looks like address start.
        if frame[1] & 0x01 == 0:
            offset = 1
    data = frame[offset:]
    if len(data) < 16:
        return None

    addrs: list[str] = []
    i = 0
    while i + 7 <= len(data) and len(addrs) < 10:
        call, _ssid, end = _ax25_addr(data[i : i + 7])
        i += 7
        if call:
            addrs.append(call)
        if end:
            break
    if len(addrs) < 2 or i + 2 > len(data):
        return None
    control = data[i]
    pid = data[i + 1]
    info = data[i + 2 :]
    # UI frame control is typically 0x03 (or with poll bit)
    if (control & 0xEF) != 0x03:
        return None
    if pid != 0xF0:
        return None
    try:
        payload = info.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return None
    dest = addrs[0]
    src = addrs[1]
    path = ",".join(addrs[2:]) if len(addrs) > 2 else ""
    if path:
        return f"{src}>{dest},{path}:{payload}"
    return f"{src}>{dest}:{payload}"


async def kiss_frames(
    host: str,
    port: int,
    *,
    stop: asyncio.Event | None = None,
    on_connected: Callable[[], None] | None = None,
    on_disconnected: Callable[[], None] | None = None,
    reconnect_delay: float = 3.0,
) -> AsyncIterator[bytes]:
    """Yield raw KISS payloads (including command byte) from Direwolf KISSPORT."""
    decoder = KissDecoder()
    while True:
        if stop and stop.is_set():
            return
        try:
            reader, writer = await asyncio.open_connection(host, port)
        except (OSError, ConnectionError):
            if on_disconnected:
                on_disconnected()
            await asyncio.sleep(reconnect_delay)
            continue
        if on_connected:
            on_connected()
        try:
            while True:
                if stop and stop.is_set():
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except Exception:  # noqa: BLE001
                        pass
                    return
                chunk = await reader.read(4096)
                if not chunk:
                    break
                for frame in decoder.feed(chunk):
                    yield frame
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass
            if on_disconnected:
                on_disconnected()
        await asyncio.sleep(reconnect_delay)
