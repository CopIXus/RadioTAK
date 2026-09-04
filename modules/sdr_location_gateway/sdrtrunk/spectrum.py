"""Spectrum / DFT frame ingest for the Console waterfall."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional

from radiotak.services.settings_store import load_settings_file

log = logging.getLogger("radiotak.spectrum")


def align_span_to_control_channels(
    f_min: Any,
    f_max: Any,
    cc_hz: list[Any],
) -> tuple[Any, Any, Any, Any]:
    """Label the listening-channel window when SDRTrunk's spectral panel is idle.

    ``showFirstTuner()`` often leaves OverlayPanel parked near 100 MHz (FM band)
    after a P25/DMR channel has already retuned the same stick. Bins are still
    one tuner-bandwidth wide, so we keep that width and recenter on the CCs.

    Returns ``(f_min, f_max, panel_f_min, panel_f_max)``. Panel fields are set
    only when the axis was remapped.
    """
    try:
        lo = float(f_min)
        hi = float(f_max)
        ccs = [float(x) for x in (cc_hz or []) if x is not None and float(x) > 0]
    except (TypeError, ValueError):
        return f_min, f_max, None, None
    if hi <= lo or not ccs:
        return f_min, f_max, None, None
    if any(lo <= cc <= hi for cc in ccs):
        return f_min, f_max, None, None
    bw = hi - lo
    span_lo, span_hi = min(ccs), max(ccs)
    center = (span_lo + span_hi) / 2.0 if (span_hi - span_lo) <= bw else ccs[0]
    return center - bw / 2.0, center + bw / 2.0, lo, hi


class SpectrumHub:
    def __init__(self) -> None:
        self.latest: Optional[dict[str, Any]] = None
        self.last_frame_at: Optional[float] = None
        self._subscribers: list[asyncio.Queue] = []
        self._task: Optional[asyncio.Task] = None
        self.frames_received = 0
        self.clients = 0  # exporter TCP connections currently open on :29501

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=8)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    def publish(self, frame: dict[str, Any]) -> None:
        self.latest = frame
        self.last_frame_at = time.time()
        self.frames_received += 1
        for q in list(self._subscribers):
            try:
                if q.full():
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                q.put_nowait(frame)
            except Exception:  # noqa: BLE001
                pass

    def parse_frame(self, raw: bytes | str) -> Optional[dict[str, Any]]:
        try:
            if isinstance(raw, bytes):
                text = raw.decode("utf-8", errors="ignore").strip()
            else:
                text = raw.strip()
            if not text:
                return None
            data = json.loads(text)
            bins = data.get("bins") or data.get("magnitudes") or data.get("data")
            if not bins:
                return None
            # Downsample if oversized
            if len(bins) > 512:
                step = len(bins) / 512.0
                bins = [bins[int(i * step)] for i in range(512)]
            cc_hz = data.get("cc_hz") or data.get("control_channels_hz") or []
            f_min = data.get("f_min") or data.get("freq_min_hz")
            f_max = data.get("f_max") or data.get("freq_max_hz")
            panel_min = data.get("panel_f_min")
            panel_max = data.get("panel_f_max")
            if panel_min is None or panel_max is None:
                f_min, f_max, panel_min, panel_max = align_span_to_control_channels(
                    f_min, f_max, cc_hz
                )
            frame: dict[str, Any] = {
                "schema": data.get("schema", "sdr2tak.spectrum.v1"),
                "bins": [float(x) for x in bins],
                "f_min": f_min,
                "f_max": f_max,
                "cc_hz": cc_hz,
                "ts": data.get("ts") or time.time(),
            }
            if panel_min is not None and panel_max is not None:
                frame["panel_f_min"] = panel_min
                frame["panel_f_max"] = panel_max
            return frame
        except Exception as exc:  # noqa: BLE001
            log.debug("spectrum parse failed: %s", exc)
            return None


spectrum_hub = SpectrumHub()


async def listen_spectrum_tcp() -> None:
    cfg = load_settings_file().get("spectrum") or {}
    if not cfg.get("enabled", True):
        log.info("spectrum export listener disabled")
        return
    host = cfg.get("host") or "127.0.0.1"
    port = int(cfg.get("port") or 29501)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        buf = b""
        spectrum_hub.clients += 1
        log.info("spectrum exporter connected (%d client(s))", spectrum_hub.clients)
        try:
            while True:
                chunk = await reader.read(65536)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    frame = spectrum_hub.parse_frame(line)
                    if frame:
                        spectrum_hub.publish(frame)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.debug("spectrum client error: %s", exc)
        finally:
            spectrum_hub.clients = max(0, spectrum_hub.clients - 1)
            log.info("spectrum exporter disconnected (%d client(s))", spectrum_hub.clients)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass

    try:
        server = await asyncio.start_server(handle, host, port)
        log.info("spectrum listener on %s:%s", host, port)
        async with server:
            await server.serve_forever()
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("spectrum listener failed: %s", exc)
