"""Map APRS packets (aprslib / TNC2) to RadioTAK location NDJSON or message dicts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

KNOTS_TO_MPS = 0.514444
FEET_TO_M = 0.3048


def _observed_at(packet: dict[str, Any]) -> str:
    ts = packet.get("timestamp")
    if isinstance(ts, int | float) and ts > 0:
        return datetime.fromtimestamp(float(ts), tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _callsign(packet: dict[str, Any]) -> str:
    return str(packet.get("from") or packet.get("source") or "").strip().upper()


def position_to_ndjson(packet: dict[str, Any], *, source: str = "rf") -> dict[str, Any] | None:
    """Build ``sdr2tak.location.v1`` from an aprslib position/object/item packet."""
    lat = packet.get("latitude")
    lon = packet.get("longitude")
    if lat is None or lon is None:
        return None
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return None
    if abs(lat_f) < 1e-9 and abs(lon_f) < 1e-9:
        return None
    call = _callsign(packet)
    if not call:
        return None

    speed_mps = None
    if packet.get("speed") is not None:
        try:
            speed_mps = float(packet["speed"]) * KNOTS_TO_MPS
        except (TypeError, ValueError):
            speed_mps = None

    heading = None
    course = packet.get("course")
    if course is not None:
        try:
            heading = float(course) % 360.0
        except (TypeError, ValueError):
            heading = None

    altitude_m = None
    if packet.get("altitude") is not None:
        try:
            # aprslib altitude is feet when present
            altitude_m = float(packet["altitude"]) * FEET_TO_M
        except (TypeError, ValueError):
            altitude_m = None

    raw_type = str(packet.get("format") or packet.get("symbol") or "position")
    return {
        "schema": "sdr2tak.location.v1",
        "decoder": "direwolf",
        "protocol": "APRS",
        "system_id": "APRS",
        "system_name": "APRS",
        "radio_id": call,
        "source_alias": call,
        "latitude": lat_f,
        "longitude": lon_f,
        "altitude_m": altitude_m,
        "speed_mps": speed_mps,
        "heading_deg": heading,
        "observed_at": _observed_at(packet),
        "raw_event_type": f"aprs_{raw_type}_{source}",
        "emergency": bool(packet.get("emergency")),
    }


def message_from_packet(packet: dict[str, Any], *, source: str = "rf") -> dict[str, Any] | None:
    """Extract an APRS text message for GeoChat."""
    if str(packet.get("format") or "") != "message":
        return None
    text = packet.get("message_text")
    if not text:
        return None
    call = _callsign(packet)
    if not call:
        return None
    addressee = str(packet.get("addresse") or packet.get("to") or "").strip()
    body = str(text).strip()
    if addressee:
        body = f"To {addressee}: {body}"
    lat = packet.get("latitude")
    lon = packet.get("longitude")
    try:
        lat_f = float(lat) if lat is not None else 0.0
        lon_f = float(lon) if lon is not None else 0.0
    except (TypeError, ValueError):
        lat_f, lon_f = 0.0, 0.0
    msg_no = packet.get("msgNo") or packet.get("message_number")
    return {
        "from": call,
        "body": body,
        "addressee": addressee,
        "message_id": f"APRS-{call}-{msg_no or int(datetime.now(UTC).timestamp() * 1000)}",
        "latitude": lat_f,
        "longitude": lon_f,
        "source": source,
        "observed_at": _observed_at(packet),
    }


def parse_tnc2(line: str) -> dict[str, Any] | None:
    """Parse a TNC2 monitor line with aprslib."""
    try:
        import aprslib
    except ImportError:
        return None
    line = (line or "").strip()
    if not line or line.startswith("#"):
        return None
    try:
        return aprslib.parse(line)
    except Exception:  # noqa: BLE001
        return None
