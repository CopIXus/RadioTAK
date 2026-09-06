"""Decoded talkgroup audio ingest for the SDR page Listen button."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from radiotak.services.settings_store import load_settings_file

log = logging.getLogger("radiotak.audio")

SCHEMA = "sdr2tak.audio.v1"


class AudioHub:
    def __init__(self) -> None:
        self.latest_meta: dict[str, Any] | None = None
        self.last_frame_at: float | None = None
        self._subscribers: list[asyncio.Queue] = []
        self.frames_received = 0
        self.pcm_frames = 0
        self.encrypted_frames = 0
        self.clients = 0

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=24)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    def publish(self, frame: dict[str, Any]) -> None:
        self.latest_meta = {k: v for k, v in frame.items() if k != "pcm_b64"}
        self.last_frame_at = time.time()
        self.frames_received += 1
        if frame.get("encrypted"):
            self.encrypted_frames += 1
        elif frame.get("pcm_b64"):
            self.pcm_frames += 1
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

    def parse_frame(self, raw: bytes | str) -> dict[str, Any] | None:
        try:
            if isinstance(raw, bytes):
                text = raw.decode("utf-8", errors="ignore").strip()
            else:
                text = raw.strip()
            if not text:
                return None
            data = json.loads(text)
            if not isinstance(data, dict):
                return None
            schema = data.get("schema") or SCHEMA
            if schema != SCHEMA and "pcm_b64" not in data and "encrypted" not in data:
                return None
            encrypted = bool(data.get("encrypted"))
            pcm_b64 = "" if encrypted else str(data.get("pcm_b64") or "")
            end = bool(data.get("end"))
            silence = bool(data.get("silence") or encrypted or not pcm_b64)
            if not pcm_b64 and not encrypted and not end and not data.get("silence"):
                return None
            sample_rate = int(data.get("sample_rate") or 8000)
            if sample_rate < 4000 or sample_rate > 48000:
                sample_rate = 8000
            return {
                "schema": SCHEMA,
                "encrypted": encrypted,
                "silence": silence,
                "end": end,
                "talkgroup": str(data.get("talkgroup") or ""),
                "radio_id": str(data.get("radio_id") or ""),
                "protocol": data.get("protocol"),
                "sample_rate": sample_rate,
                "channels": 1,
                "encoding": "pcm_s16le",
                "pcm_b64": pcm_b64,
                "ts": data.get("ts") or time.time(),
            }
        except Exception as exc:  # noqa: BLE001
            log.debug("audio parse failed: %s", exc)
            return None

    def snapshot(self) -> dict[str, Any]:
        age = None
        if self.last_frame_at is not None:
            age = round(time.time() - self.last_frame_at, 1)
        meta = self.latest_meta or {}
        return {
            "clients": self.clients,
            "frames_received": self.frames_received,
            "pcm_frames": self.pcm_frames,
            "encrypted_frames": self.encrypted_frames,
            "last_frame_age": age,
            "live": age is not None and age < 5.0,
            "encrypted": bool(meta.get("encrypted")),
            "talkgroup": meta.get("talkgroup") or "",
            "radio_id": meta.get("radio_id") or "",
        }


audio_hub = AudioHub()


async def listen_audio_tcp() -> None:
    cfg = load_settings_file().get("audio") or {}
    if not cfg.get("enabled", True):
        log.info("audio export listener disabled")
        return
    host = cfg.get("host") or "127.0.0.1"
    port = int(cfg.get("port") or 29502)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        buf = b""
        audio_hub.clients += 1
        log.info("audio exporter connected (%d client(s))", audio_hub.clients)
        try:
            while True:
                chunk = await reader.read(65536)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    frame = audio_hub.parse_frame(line)
                    if frame:
                        audio_hub.publish(frame)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.debug("audio client error: %s", exc)
        finally:
            audio_hub.clients = max(0, audio_hub.clients - 1)
            log.info("audio exporter disconnected (%d client(s))", audio_hub.clients)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass

    try:
        server = await asyncio.start_server(handle, host, port)
        log.info("audio listener on %s:%s", host, port)
        async with server:
            await server.serve_forever()
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("audio listener failed: %s", exc)
