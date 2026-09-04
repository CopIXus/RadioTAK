"""Cursor-on-Target XML generation."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from typing import Optional
from xml.etree.ElementTree import Element, SubElement, tostring

from radiotak.gateway import stable_cot_uid
from radiotak.gateway.constants import (
    DEFAULT_STALE_SECONDS,
    DETECTION_COT_TYPE,
    PRESENCE_STALE_SECONDS,
    SA_COT_TYPE,
    SA_ENDPOINT,
)
from radiotak.gateway.marker_style import argb_from_hex

__all__ = [
    "DEFAULT_STALE_SECONDS",
    "DETECTION_COT_TYPE",
    "PRESENCE_STALE_SECONDS",
    "SA_COT_TYPE",
    "SA_ENDPOINT",
    "build_cot_xml",
    "build_disconnect_xml",
    "build_presence_xml",
]


def _fmt(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_cot_xml(
    *,
    radio_id: str,
    latitude: float,
    longitude: float,
    observed_at: datetime,
    system_id: Optional[str] = None,
    callsign: Optional[str] = None,
    cot_type: str = DETECTION_COT_TYPE,
    stale_seconds: int = DEFAULT_STALE_SECONDS,
    altitude_m: Optional[float] = None,
    accuracy_m: Optional[float] = None,
    default_ce_m: float = 20.0,
    remarks: Optional[str] = None,
    how: str = "m-g",
    uid: Optional[str] = None,
    iconset_path: Optional[str] = None,
    marker_color: Optional[str] = None,
    as_contact: bool = False,
    group_name: Optional[str] = None,
    group_role: str = "Team Member",
) -> str:
    """Build a detection CoT. Named on the map via callsign; not an ATAK contact unless as_contact."""
    uid = uid or stable_cot_uid(system_id, radio_id)
    start = observed_at if observed_at.tzinfo else observed_at.replace(tzinfo=timezone.utc)
    stale = start + timedelta(seconds=stale_seconds)
    now = datetime.now(timezone.utc)

    event = Element(
        "event",
        {
            "version": "2.0",
            "uid": uid,
            "type": cot_type,
            "how": how,
            "time": _fmt(now),
            "start": _fmt(start),
            "stale": _fmt(stale),
        },
    )
    ce = accuracy_m if accuracy_m is not None else default_ce_m
    hae = altitude_m if altitude_m is not None else 0.0
    SubElement(
        event,
        "point",
        {
            "lat": f"{latitude:.6f}",
            "lon": f"{longitude:.6f}",
            "hae": f"{hae:.1f}",
            "ce": f"{ce:.1f}",
            "le": "9999999",
        },
    )
    detail = SubElement(event, "detail")
    if callsign:
        contact_attrs = {"callsign": callsign}
        if as_contact:
            contact_attrs["endpoint"] = SA_ENDPOINT
        SubElement(detail, "contact", contact_attrs)
    if as_contact and group_name:
        SubElement(detail, "__group", {"name": group_name, "role": group_role})
    if iconset_path:
        SubElement(detail, "usericon", {"iconsetpath": iconset_path})
    if marker_color:
        SubElement(detail, "color", {"argb": argb_from_hex(marker_color)})
    remark_text = remarks or (
        f"Location source: authorized radio telemetry via RadioTAK (radio_id={radio_id})"
    )
    SubElement(detail, "remarks").text = remark_text
    return tostring(event, encoding="unicode")


def build_presence_xml(
    *,
    uid: str,
    callsign: str,
    latitude: float = 0.0,
    longitude: float = 0.0,
    stale_seconds: int = PRESENCE_STALE_SECONDS,
    group_name: Optional[str] = None,
    group_role: str = "Team Member",
    version: str = "0.0.0",
    how: str = "m-g",
) -> str:
    """Self SA so TAK Server lists RadioTAK as a connected client with this callsign."""
    now = datetime.now(timezone.utc)
    stale = now + timedelta(seconds=stale_seconds)
    event = Element(
        "event",
        {
            "version": "2.0",
            "uid": uid,
            "type": SA_COT_TYPE,
            "how": how,
            "time": _fmt(now),
            "start": _fmt(now),
            "stale": _fmt(stale),
        },
    )
    SubElement(
        event,
        "point",
        {
            "lat": f"{latitude:.6f}",
            "lon": f"{longitude:.6f}",
            "hae": "0.0",
            "ce": "9999999",
            "le": "9999999",
        },
    )
    detail = SubElement(event, "detail")
    SubElement(detail, "contact", {"callsign": callsign, "endpoint": SA_ENDPOINT})
    SubElement(detail, "uid", {"Droid": callsign})
    if group_name:
        SubElement(detail, "__group", {"name": group_name, "role": group_role})
    SubElement(
        detail,
        "takv",
        {
            "device": "RadioTAK",
            "platform": "RadioTAK",
            "os": sys.platform,
            "version": version,
        },
    )
    SubElement(detail, "status", {"battery": "100"})
    SubElement(detail, "remarks").text = f"RadioTAK gateway ({callsign})"
    return tostring(event, encoding="unicode")


def build_disconnect_xml(*, uid: str, callsign: str) -> str:
    now = datetime.now(timezone.utc)
    stale = now + timedelta(seconds=10)
    event = Element(
        "event",
        {
            "version": "2.0",
            "uid": uid,
            "type": "t-x-d-d",
            "how": "m-g",
            "time": _fmt(now),
            "start": _fmt(now),
            "stale": _fmt(stale),
        },
    )
    SubElement(
        event,
        "point",
        {"lat": "0.000000", "lon": "0.000000", "hae": "0.0", "ce": "9999999", "le": "9999999"},
    )
    detail = SubElement(event, "detail")
    SubElement(detail, "link", {"uid": uid, "relation": "p-p", "type": SA_COT_TYPE})
    SubElement(detail, "contact", {"callsign": callsign})
    return tostring(event, encoding="unicode")
