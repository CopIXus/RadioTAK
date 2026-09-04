"""Ingest pipeline: validate → allowlist → dedupe → CoT → TAK queue."""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from radiotak.db import ForwardingStatus, LocationObservation, TakServer, utcnow
from radiotak.gateway import DecodeEventIn, LocationEventIn, stable_cot_uid
from radiotak.gateway.constants import DEFAULT_STALE_SECONDS, DETECTION_COT_TYPE
from radiotak.gateway.cot import build_cot_xml
from radiotak.gateway.identities import (
    hear_status,
    is_forward_allowed,
    observe_call,
    observe_or_create,
)
from radiotak.gateway.marker_style import resolve_style
from radiotak.gateway.tak import tak_registry
from radiotak.services.logging_setup import log_event
from radiotak.services.settings_store import load_settings_file


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass
class PipelineResult:
    observation: LocationObservation | None
    forwarded: bool
    reason: str
    cot_xml: str | None = None
    cot_uid: str | None = None
    heard: bool = False


@dataclass
class DedupeState:
    last_sent: dict[str, tuple[float, float, float]] = field(default_factory=dict)


class LocationPipeline:
    def __init__(self) -> None:
        self.dedupe = DedupeState()
        self._listeners: list = []

    def add_listener(self, callback) -> None:  # noqa: ANN001
        self._listeners.append(callback)

    def _emit(self, event: dict[str, Any]) -> None:
        for cb in list(self._listeners):
            try:
                cb(event)
            except Exception:  # noqa: BLE001
                pass

    def process_dict(self, db: Session, raw: dict[str, Any]) -> PipelineResult:
        schema = str(raw.get("schema") or "")
        if schema == "sdr2tak.decode.v1":
            try:
                event = DecodeEventIn.model_validate(raw)
            except Exception as exc:  # noqa: BLE001
                log_event("pipeline", "schema_reject", detail=str(exc))
                self._emit({"type": "reject", "reason": f"schema: {exc}", "raw": raw})
                return PipelineResult(None, False, f"schema: {exc}")
            return self.process_decode(db, event)

        try:
            event = LocationEventIn.model_validate(raw)
        except Exception as exc:  # noqa: BLE001
            log_event("pipeline", "schema_reject", detail=str(exc))
            self._emit({"type": "reject", "reason": f"schema: {exc}", "raw": raw})
            return PipelineResult(None, False, f"schema: {exc}")

        return self.process_event(db, event, raw)

    def process_decode(self, db: Session, event: DecodeEventIn) -> PipelineResult:
        key_loaded = bool(event.key_loaded)
        if not key_loaded and (event.algorithm_id or event.algorithm_id_hex) and event.key_id:
            try:
                from radiotak.services.traffic_keys import matching_key

                key_loaded = (
                    matching_key(db, event.algorithm_id or event.algorithm_id_hex, event.key_id)
                    is not None
                )
            except Exception:  # noqa: BLE001
                key_loaded = bool(event.key_loaded)

        identity = observe_call(
            db,
            radio_id=event.radio_id,
            system_id=event.system_id,
            alias=event.source_alias,
            talkgroup=event.talkgroup,
            encrypted=event.encrypted,
            algorithm_id=event.algorithm_id_hex or event.algorithm_id,
            key_id=event.key_id,
            key_loaded=key_loaded,
        )
        tg = event.talkgroup or identity.last_talkgroup_id
        if event.encrypted:
            reason = f"ENCRYPTED TG {tg}" if tg else "ENCRYPTED CALL"
            if key_loaded:
                reason += " · key on file"
            else:
                reason += " · no matching key"
            event_type = "encrypted"
        else:
            reason = f"HEARD TG {tg} · no GPS" if tg else "HEARD · no GPS"
            event_type = "heard"
        payload = {
            "type": event_type,
            "radio_id": event.radio_id,
            "callsign": identity.callsign,
            "talkgroup": tg,
            "protocol": event.protocol,
            "encrypted": event.encrypted,
            "key_loaded": key_loaded,
            "algorithm_id": event.algorithm_id_hex or event.algorithm_id,
            "key_id": event.key_id,
            "reason": reason,
            **hear_status(identity),
        }
        self._emit(payload)
        return PipelineResult(None, False, reason, heard=True)

    def process_event(
        self, db: Session, event: LocationEventIn, raw: dict | None = None
    ) -> PipelineResult:
        settings = load_settings_file()
        fwd = settings.get("forwarding", {})
        identity = observe_or_create(
            db,
            radio_id=event.radio_id,
            system_id=event.system_id,
            alias=event.source_alias,
            lat=event.latitude,
            lon=event.longitude,
        )
        allowed, reason = is_forward_allowed(identity)
        cot_uid = stable_cot_uid(event.system_id, event.radio_id)
        payload_hash = hashlib.sha256(
            json.dumps(raw or event.model_dump(mode="json"), sort_keys=True, default=str).encode()
        ).hexdigest()

        obs = LocationObservation(
            source="decoder",
            decoder=event.decoder,
            protocol=event.protocol,
            system_id=event.system_id,
            system_name=event.system_name,
            site_id=event.site_id,
            frequency_hz=event.frequency_hz,
            talkgroup_id=event.talkgroup,
            radio_id=event.radio_id,
            radio_alias=identity.callsign or event.source_alias,
            latitude=event.latitude,
            longitude=event.longitude,
            altitude_m=event.altitude_m,
            speed_mps=event.speed_mps,
            heading_deg=event.heading_deg,
            accuracy_m=event.accuracy_m,
            emergency=event.emergency,
            signal_quality=event.rssi_dbm,
            observed_at=event.observed_at,
            received_at=utcnow(),
            raw_event_type=event.raw_event_type,
            raw_payload_hash=payload_hash,
            cot_uid=cot_uid,
        )

        if not allowed:
            obs.forwarding_status = ForwardingStatus.BLOCKED.value
            obs.forwarding_reason = reason
            db.add(obs)
            db.commit()
            db.refresh(obs)
            self._emit(
                {
                    "type": "blocked",
                    "radio_id": event.radio_id,
                    "reason": reason,
                    "lat": event.latitude,
                    "lon": event.longitude,
                    "protocol": event.protocol,
                    "callsign": identity.callsign,
                }
            )
            return PipelineResult(obs, False, reason)

        age = (utcnow() - event.observed_at).total_seconds()
        max_age = float(fwd.get("stale_seconds", DEFAULT_STALE_SECONDS)) * 2
        if age > max_age and not event.emergency:
            obs.forwarding_status = ForwardingStatus.DROPPED.value
            obs.forwarding_reason = "TOO OLD"
            db.add(obs)
            db.commit()
            return PipelineResult(obs, False, "TOO OLD")

        key = cot_uid
        now_m = time.monotonic()
        min_interval = float(fwd.get("min_interval_seconds", 2))
        min_move = float(fwd.get("min_movement_meters", 5))
        heartbeat = float(fwd.get("stationary_heartbeat_seconds", 45))
        last = self.dedupe.last_sent.get(key)
        if last and fwd.get("duplicate_suppression", True) and not event.emergency:
            plat, plon, pts = last
            dt = now_m - pts
            dist = _haversine_m(plat, plon, event.latitude, event.longitude)
            if dt < min_interval:
                obs.forwarding_status = ForwardingStatus.DROPPED.value
                obs.forwarding_reason = "RATE LIMITED"
                db.add(obs)
                db.commit()
                return PipelineResult(obs, False, "RATE LIMITED")
            if dist < min_move and dt < heartbeat:
                obs.forwarding_status = ForwardingStatus.DROPPED.value
                obs.forwarding_reason = "DUPLICATE / STATIONARY"
                db.add(obs)
                db.commit()
                return PipelineResult(obs, False, "DUPLICATE / STATIONARY")

        servers = list(db.scalars(select(TakServer).where(TakServer.enabled.is_(True))))
        first_xml = None
        queued = 0
        for server in servers:
            style = resolve_style(
                server=server,
                identity=identity,
                radio_id=event.radio_id,
                source_alias=event.source_alias,
            )
            stale_s = style["stale_seconds"] or int(fwd.get("stale_seconds", DEFAULT_STALE_SECONDS))
            ce_m = event.accuracy_m if event.accuracy_m is not None else style["default_ce_meters"]
            cot_xml = build_cot_xml(
                radio_id=event.radio_id,
                latitude=event.latitude,
                longitude=event.longitude,
                observed_at=event.observed_at,
                system_id=event.system_id,
                callsign=style["callsign"],
                cot_type=style["cot_type"],
                stale_seconds=stale_s,
                altitude_m=event.altitude_m,
                accuracy_m=event.accuracy_m,
                default_ce_m=float(ce_m),
                remarks=style["remarks"],
                how=style["how"],
                uid=cot_uid,
                iconset_path=style["iconset_path"] or None,
                marker_color=style["marker_color"],
            )
            if first_xml is None:
                first_xml = cot_xml
            if tak_registry.enqueue_for(server.id, cot_xml, cot_uid, observation_id=None):
                queued += 1
            else:
                # No live manager yet — still stash on registry-wide for later reconnect
                tak_registry.enqueue_all(cot_xml, cot_uid)

        if not servers:
            # Fallback single CoT using defaults
            first_xml = build_cot_xml(
                radio_id=event.radio_id,
                latitude=event.latitude,
                longitude=event.longitude,
                observed_at=event.observed_at,
                system_id=event.system_id,
                callsign=identity.callsign or event.source_alias or event.radio_id,
                cot_type=identity.cot_type or DETECTION_COT_TYPE,
                stale_seconds=identity.stale_seconds
                or int(fwd.get("stale_seconds", DEFAULT_STALE_SECONDS)),
                altitude_m=event.altitude_m,
                accuracy_m=event.accuracy_m,
                default_ce_m=float(fwd.get("default_ce_meters", 20)),
                remarks=identity.remarks,
                uid=cot_uid,
            )
            tak_registry.enqueue_all(first_xml, cot_uid)

        obs.forwarding_status = ForwardingStatus.PENDING.value
        obs.forwarding_reason = "QUEUED"
        db.add(obs)
        db.commit()
        db.refresh(obs)

        self.dedupe.last_sent[key] = (event.latitude, event.longitude, now_m)
        self._emit(
            {
                "type": "queued",
                "radio_id": event.radio_id,
                "callsign": identity.callsign,
                "lat": event.latitude,
                "lon": event.longitude,
                "protocol": event.protocol,
                "cot_uid": cot_uid,
                "observation_id": obs.id,
                "servers_queued": queued or len(servers),
            }
        )
        return PipelineResult(obs, True, "QUEUED", cot_xml=first_xml, cot_uid=cot_uid)


pipeline = LocationPipeline()
