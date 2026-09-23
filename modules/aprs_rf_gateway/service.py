"""APRS gateway service: Direwolf KISS + optional APRS-IS → pipeline / GeoChat."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from sqlalchemy.orm import Session

from radiotak.db import RadioIdentity, get_session_factory
from radiotak.gateway.cot import build_geochat_xml
from radiotak.gateway.events import event_bus
from radiotak.gateway.identities import find_identity, is_forward_allowed, observe_or_create
from radiotak.gateway.pipeline import pipeline
from radiotak.gateway.tak import tak_registry
from radiotak.services.logging_setup import log_event

from .aprs_map import message_from_packet, parse_tnc2, position_to_ndjson
from .kiss_client import ax25_ui_to_tnc2, kiss_frames
from .settings import aprs_passcode, load_settings

log = logging.getLogger("radiotak.aprs")

_stats: dict[str, Any] = {
    "kiss_connected": False,
    "is_connected": False,
    "packets_total": 0,
    "rf_packets": 0,
    "is_packets": 0,
    "positions_sent": 0,
    "messages_sent": 0,
    "messages_blocked": 0,
    "last_callsign": None,
    "last_packet_at": None,
    "packets_window": [],  # timestamps for packets/min
    "running": False,
    "last_error": None,
}

_stop: asyncio.Event | None = None
_tasks: list[asyncio.Task] = []


def stats_snapshot() -> dict[str, Any]:
    now = time.time()
    window = [t for t in _stats["packets_window"] if now - t < 60.0]
    _stats["packets_window"] = window
    last = _stats["last_packet_at"]
    return {
        "running": _stats["running"],
        "kiss_connected": _stats["kiss_connected"],
        "is_connected": _stats["is_connected"],
        "packets_total": _stats["packets_total"],
        "rf_packets": _stats["rf_packets"],
        "is_packets": _stats["is_packets"],
        "positions_sent": _stats["positions_sent"],
        "messages_sent": _stats["messages_sent"],
        "messages_blocked": _stats["messages_blocked"],
        "last_callsign": _stats["last_callsign"],
        "packets_per_min": len(window),
        "last_packet_age": round(now - last, 1) if isinstance(last, float) else None,
        "last_error": _stats["last_error"],
        "settings": {
            "enable_rf": load_settings().get("enable_rf"),
            "enable_is": load_settings().get("enable_is"),
            "auto_approve_units": load_settings().get("auto_approve_units"),
            "chatroom": load_settings().get("chatroom"),
            "mycall": load_settings().get("mycall"),
        },
    }


def ensure_aprs_unit_approved(
    db: Session,
    radio_id: str,
    *,
    alias: str | None = None,
) -> RadioIdentity:
    """Approve an APRS callsign for TAK using Settings default stale (unit stale=0).

    Does not bump observation_count (pipeline / observe_or_create still owns that).
    Operator hard-block: if ``enabled`` is False, leave the unit alone.
    """
    call = alias or radio_id
    identity = find_identity(db, radio_id, "APRS")
    if identity is None:
        identity = RadioIdentity(
            radio_id=radio_id,
            system_id="APRS",
            enabled=True,
            forward_to_tak=True,
            callsign=call,
            display_name=call,
            stale_seconds=0,
        )
        db.add(identity)
        db.commit()
        db.refresh(identity)
        return identity
    if not identity.enabled:
        return identity
    if not identity.forward_to_tak:
        identity.forward_to_tak = True
        # 0 = use Settings → Forwarding "Radio marker stale" (default 20 min)
        identity.stale_seconds = 0
        db.commit()
        db.refresh(identity)
    return identity


def _maybe_auto_approve(db: Session, radio_id: str, cfg: dict[str, Any]) -> None:
    if not cfg.get("auto_approve_units"):
        return
    if not radio_id:
        return
    ensure_aprs_unit_approved(db, radio_id, alias=radio_id)


def _note_packet(call: str | None, source: str) -> None:
    now = time.time()
    _stats["packets_total"] = int(_stats["packets_total"]) + 1
    if source == "rf":
        _stats["rf_packets"] = int(_stats["rf_packets"]) + 1
    else:
        _stats["is_packets"] = int(_stats["is_packets"]) + 1
    _stats["last_packet_at"] = now
    window = list(_stats["packets_window"])
    window.append(now)
    _stats["packets_window"] = [t for t in window if now - t < 60.0]
    if call:
        _stats["last_callsign"] = call


def _handle_position(loc: dict[str, Any], cfg: dict[str, Any]) -> bool:
    """Feed position through LocationPipeline once (no TCP loopback / double enqueue)."""
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        rid = str(loc.get("radio_id") or "")
        _maybe_auto_approve(db, rid, cfg)
        result = pipeline.process_dict(db, loc)
        if result.reason and str(result.reason).startswith("schema:"):
            _stats["last_error"] = result.reason
            return False
        _stats["positions_sent"] = int(_stats["positions_sent"]) + 1
        return True
    except Exception as exc:  # noqa: BLE001
        _stats["last_error"] = str(exc)
        log.warning("APRS position pipeline failed: %s", exc)
        return False
    finally:
        db.close()


def _handle_message(msg: dict[str, Any], cfg: dict[str, Any]) -> None:
    call = msg["from"]
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        _maybe_auto_approve(db, call, cfg)
        identity = observe_or_create(db, radio_id=call, system_id="APRS", alias=call)
        allowed, reason = is_forward_allowed(identity)
        event_bus.publish(
            {
                "type": "aprs_message",
                "protocol": "APRS",
                "radio_id": call,
                "reason": msg["body"][:120],
                "source": msg.get("source"),
            }
        )
        if not allowed:
            _stats["messages_blocked"] = int(_stats["messages_blocked"]) + 1
            event_bus.publish(
                {
                    "type": "blocked",
                    "protocol": "APRS",
                    "radio_id": call,
                    "reason": f"GeoChat {reason}",
                }
            )
            return
        chatroom = str(cfg.get("chatroom") or "APRS")
        dest = (cfg.get("marti_dest_group") or "").strip() or None
        sender_uid = f"RADIOTAK-APRS-{call}"
        xml = build_geochat_xml(
            sender_uid=sender_uid,
            sender_callsign=call,
            message_body=msg["body"],
            chatroom=chatroom,
            message_id=msg.get("message_id"),
            latitude=float(msg.get("latitude") or 0.0),
            longitude=float(msg.get("longitude") or 0.0),
            marti_dest_group=dest,
        )
        n = tak_registry.enqueue_all(xml, f"GeoChat.{sender_uid}.{chatroom}")
        _stats["messages_sent"] = int(_stats["messages_sent"]) + 1
        event_bus.publish(
            {
                "type": "queued",
                "protocol": "APRS",
                "radio_id": call,
                "reason": f"GeoChat → {chatroom} ({n} server(s))",
            }
        )
        log_event("aprs", "geochat", detail=f"{call} → {chatroom}")
    finally:
        db.close()


async def _ingest_packet(packet: dict[str, Any], *, source: str, cfg: dict[str, Any]) -> None:
    call = str(packet.get("from") or "").upper()
    _note_packet(call or None, source)

    msg = message_from_packet(packet, source=source)
    if msg:
        await asyncio.to_thread(_handle_message, msg, cfg)

    loc = position_to_ndjson(packet, source=source)
    if loc:
        await asyncio.to_thread(_handle_position, loc, cfg)


async def _rf_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        cfg = load_settings()
        if not cfg.get("enable_rf", True):
            _stats["kiss_connected"] = False
            try:
                await asyncio.wait_for(stop.wait(), timeout=5.0)
            except TimeoutError:
                pass
            continue
        host = str(cfg.get("kiss_host") or "127.0.0.1")
        port = int(cfg.get("kiss_port") or 8001)
        log_event("aprs", "kiss_connect", detail=f"{host}:{port}")
        try:
            async for frame in kiss_frames(
                host,
                port,
                stop=stop,
                on_connected=lambda: _stats.__setitem__("kiss_connected", True),
                on_disconnected=lambda: _stats.__setitem__("kiss_connected", False),
            ):
                if stop.is_set():
                    break
                cfg = load_settings()
                if not cfg.get("enable_rf", True):
                    break
                tnc2 = ax25_ui_to_tnc2(frame)
                if not tnc2:
                    continue
                packet = parse_tnc2(tnc2)
                if not packet:
                    continue
                await _ingest_packet(packet, source="rf", cfg=cfg)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            _stats["last_error"] = str(exc)
            log.warning("APRS KISS loop error: %s", exc)
            await asyncio.sleep(3.0)


async def _is_loop(stop: asyncio.Event) -> None:
    """Optional APRS-IS consumer (internet stations when RF is quiet)."""
    while not stop.is_set():
        cfg = load_settings()
        if not cfg.get("enable_is"):
            _stats["is_connected"] = False
            try:
                await asyncio.wait_for(stop.wait(), timeout=5.0)
            except TimeoutError:
                pass
            continue
        try:
            import aprslib
        except ImportError:
            _stats["last_error"] = "aprslib not installed"
            _stats["is_connected"] = False
            await asyncio.sleep(30.0)
            continue

        mycall = str(cfg.get("mycall") or "N0CALL-15")
        passcode = int(cfg.get("aprs_is_passcode") or -1)
        if passcode < 0:
            passcode = aprs_passcode(mycall)
        server = str(cfg.get("aprs_is_server") or "rotate.aprs2.net")
        port = int(cfg.get("aprs_is_port") or 14580)
        filt = str(cfg.get("aprs_is_filter") or "")
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        loop = asyncio.get_running_loop()

        def _on_packet(packet: dict) -> None:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, packet)
            except Exception:  # noqa: BLE001
                pass

        ais = aprslib.IS(mycall, passwd=passcode, host=server, port=port)
        consumer_fut = None
        try:
            if filt:
                ais.set_filter(filt)
            ais.connect(blocking=True)
            _stats["is_connected"] = True
            log_event("aprs", "is_connect", detail=f"{server}:{port} filter={filt}")

            def _consume() -> None:
                ais.consumer(_on_packet, raw=False, immortal=True)

            consumer_fut = loop.run_in_executor(None, _consume)
            while not stop.is_set():
                cfg = load_settings()
                if not cfg.get("enable_is"):
                    break
                if consumer_fut.done():
                    exc = consumer_fut.exception()
                    if exc:
                        raise exc
                    break
                try:
                    packet = await asyncio.wait_for(queue.get(), timeout=1.0)
                except TimeoutError:
                    continue
                await _ingest_packet(packet, source="is", cfg=cfg)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            _stats["last_error"] = f"APRS-IS: {exc}"
            log.warning("APRS-IS error: %s", exc)
        finally:
            _stats["is_connected"] = False
            try:
                ais.close()
            except Exception:  # noqa: BLE001
                pass
            if consumer_fut is not None and not consumer_fut.done():
                try:
                    await asyncio.wait_for(asyncio.shield(consumer_fut), timeout=2.0)
                except Exception:  # noqa: BLE001
                    pass
        await asyncio.sleep(5.0)


async def start_service() -> None:
    global _stop, _tasks
    if _stats["running"]:
        return
    _stop = asyncio.Event()
    _stats["running"] = True
    _stats["last_error"] = None
    _tasks = [
        asyncio.create_task(_rf_loop(_stop), name="aprs-rf"),
        asyncio.create_task(_is_loop(_stop), name="aprs-is"),
    ]
    log_event("aprs", "service_start")


async def stop_service() -> None:
    global _stop, _tasks
    if _stop:
        _stop.set()
    for t in _tasks:
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001
            pass
    _tasks = []
    _stop = None
    _stats["running"] = False
    _stats["kiss_connected"] = False
    _stats["is_connected"] = False
    log_event("aprs", "service_stop")
