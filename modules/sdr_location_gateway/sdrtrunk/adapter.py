"""JSONL / NDJSON decoder adapters."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import AsyncIterator, Optional

from radiotak.db import get_session_factory
from radiotak.gateway.pipeline import pipeline
from radiotak.gateway.tak import tak_registry
from radiotak.services.logging_setup import log_event


def replay_jsonl(path: str | Path, send_to_tak: bool = True, refresh_timestamps: bool = True) -> dict:
    """Synchronously replay a JSONL fixture through the pipeline."""
    from datetime import datetime, timezone

    path = Path(path)
    Session = get_session_factory()
    stats = {"total": 0, "forwarded": 0, "blocked": 0, "rejected": 0}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            raw = json.loads(line)
            if refresh_timestamps:
                raw["observed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            stats["total"] += 1
            db = Session()
            try:
                result = pipeline.process_dict(db, raw)
                if result.observation is None:
                    stats["rejected"] += 1
                elif result.forwarded:
                    stats["forwarded"] += 1
                    if send_to_tak and result.cot_xml:
                        n = tak_registry.enqueue_all(
                            result.cot_xml, result.cot_uid or "", result.observation.id
                        )
                        if n == 0:
                            from radiotak.gateway.tak import TakConnectionManager

                            mgr = tak_registry.get("replay") or TakConnectionManager(
                                server_id="replay", host="", dry_run=True
                            )
                            tak_registry.upsert(mgr)
                            mgr.enqueue(result.cot_xml, result.cot_uid or "", result.observation.id)
                        from radiotak.db import ForwardingStatus

                        result.observation.forwarding_status = ForwardingStatus.SENT.value
                        result.observation.forwarding_reason = "REPLAY SENT"
                        db.commit()
                else:
                    stats["blocked"] += 1
            finally:
                db.close()
    log_event("replay", "complete", detail=str(stats))
    return stats


_geo_stats: dict[str, object] = {
    "clients": 0,
    "connections_total": 0,
    "lines_received": 0,
    "last_line_at": None,
}


def geo_stats() -> dict:
    """Counters for the :29500 GPS feed (exporter connected? any lines yet?)."""
    import time

    last = _geo_stats["last_line_at"]
    return {
        "clients": _geo_stats["clients"],
        "connections_total": _geo_stats["connections_total"],
        "lines_received": _geo_stats["lines_received"],
        "last_line_age": round(time.time() - last, 1) if isinstance(last, float) else None,
    }


async def listen_ndjson_tcp(host: str = "127.0.0.1", port: int = 29500) -> None:
    """Listen for SDRTrunk geo event NDJSON lines."""
    import time

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        Session = get_session_factory()
        _geo_stats["clients"] = int(_geo_stats["clients"]) + 1
        _geo_stats["connections_total"] = int(_geo_stats["connections_total"]) + 1
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    raw = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
                _geo_stats["lines_received"] = int(_geo_stats["lines_received"]) + 1
                _geo_stats["last_line_at"] = time.time()
                db = Session()
                try:
                    result = pipeline.process_dict(db, raw)
                    if result.forwarded and result.cot_xml:
                        tak_registry.enqueue_all(
                            result.cot_xml, result.cot_uid or "", result.observation.id if result.observation else None
                        )
                finally:
                    db.close()
        finally:
            _geo_stats["clients"] = max(0, int(_geo_stats["clients"]) - 1)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass

    server = await asyncio.start_server(handle, host, port)
    log_event("decoder", "ndjson_listen", detail=f"{host}:{port}")
    async with server:
        await server.serve_forever()
