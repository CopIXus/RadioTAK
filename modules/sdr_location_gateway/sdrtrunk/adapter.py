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


def replay_jsonl(path: str | Path, send_to_tak: bool = True) -> dict:
    """Synchronously replay a JSONL fixture through the pipeline."""
    path = Path(path)
    Session = get_session_factory()
    stats = {"total": 0, "forwarded": 0, "blocked": 0, "rejected": 0}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            raw = json.loads(line)
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
                            # ensure at least dry-run sink for CLI demos
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


async def listen_ndjson_tcp(host: str = "127.0.0.1", port: int = 29500) -> None:
    """Listen for SDRTrunk geo event NDJSON lines."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        Session = get_session_factory()
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    raw = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
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
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, host, port)
    log_event("decoder", "ndjson_listen", detail=f"{host}:{port}")
    async with server:
        await server.serve_forever()
