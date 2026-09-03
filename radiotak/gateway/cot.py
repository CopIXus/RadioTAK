"""Cursor-on-Target XML generation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from xml.etree.ElementTree import Element, SubElement, tostring

from radiotak.gateway import stable_cot_uid


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
    cot_type: str = "a-f-G-U-C",
    stale_seconds: int = 120,
    altitude_m: Optional[float] = None,
    accuracy_m: Optional[float] = None,
    default_ce_m: float = 20.0,
    remarks: Optional[str] = None,
    how: str = "m-g",
    uid: Optional[str] = None,
) -> str:
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
        SubElement(detail, "contact", {"callsign": callsign})
    remark_text = remarks or (
        f"Location source: authorized radio telemetry via RadioTAK (radio_id={radio_id})"
    )
    SubElement(detail, "remarks").text = remark_text
    return tostring(event, encoding="unicode")
