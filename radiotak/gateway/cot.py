"""Cursor-on-Target XML generation."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
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
    "build_geochat_xml",
    "build_presence_xml",
]


def _fmt(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_cot_xml(
    *,
    radio_id: str,
    latitude: float,
    longitude: float,
    observed_at: datetime,
    system_id: str | None = None,
    callsign: str | None = None,
    cot_type: str = DETECTION_COT_TYPE,
    stale_seconds: int = DEFAULT_STALE_SECONDS,
    altitude_m: float | None = None,
    accuracy_m: float | None = None,
    default_ce_m: float = 20.0,
    remarks: str | None = None,
    how: str = "m-g",
    uid: str | None = None,
    iconset_path: str | None = None,
    marker_color: str | None = None,
    as_contact: bool = False,
    group_name: str | None = None,
    group_role: str = "Team Member",
) -> str:
    """Build a detection CoT. Named on the map via callsign; not an ATAK contact unless as_contact."""
    uid = uid or stable_cot_uid(system_id, radio_id)
    start = observed_at if observed_at.tzinfo else observed_at.replace(tzinfo=UTC)
    stale = start + timedelta(seconds=stale_seconds)
    now = datetime.now(UTC)

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
    group_name: str | None = None,
    group_role: str = "Team Member",
    version: str = "0.0.0",
    how: str = "m-g",
) -> str:
    """Self SA so TAK Server lists RadioTAK as a connected client with this callsign."""
    now = datetime.now(UTC)
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


def build_geochat_xml(
    *,
    sender_uid: str,
    sender_callsign: str,
    message_body: str,
    chatroom: str = "APRS",
    message_id: str | None = None,
    latitude: float = 0.0,
    longitude: float = 0.0,
    altitude_m: float | None = None,
    stale_seconds: int = 3600,
    how: str = "h-g-i-g-o",
    marti_dest_group: str | None = None,
    link_uid: str | None = None,
    link_type: str = "a-f-G-U-C",
) -> str:
    """Build an ATAK GeoChat CoT (``b-t-f``), matching TN SAM Node-RED shape.

    UID form: ``GeoChat.{senderUid}.{chatroom}.{msgId}``.
    Optional ``<marti><dest group="…"/></marti>`` when the enrolled server
    uses Marti channel routing (same pattern as drone room alerts).
    """
    now = datetime.now(UTC)
    stale = now + timedelta(seconds=stale_seconds)
    msg_id = (message_id or f"APRS-{int(now.timestamp() * 1000)}").replace(" ", "")
    uid = f"GeoChat.{sender_uid}.{chatroom}.{msg_id}"
    hae = altitude_m if altitude_m is not None else 9999999.0
    now_s = _fmt(now)

    event = Element(
        "event",
        {
            "version": "2.0",
            "uid": uid,
            "type": "b-t-f",
            "how": how,
            "time": now_s,
            "start": now_s,
            "stale": _fmt(stale),
        },
    )
    SubElement(
        event,
        "point",
        {
            "lat": f"{latitude:.6f}" if abs(latitude) > 1e-9 or abs(longitude) > 1e-9 else "0",
            "lon": f"{longitude:.6f}" if abs(latitude) > 1e-9 or abs(longitude) > 1e-9 else "0",
            "hae": f"{hae:.1f}",
            "ce": "9999999.0",
            "le": "9999999.0",
        },
    )
    detail = SubElement(event, "detail")
    chat = SubElement(
        detail,
        "__chat",
        {
            "parent": "RootContactGroup",
            "groupOwner": "false",
            "messageId": msg_id,
            "chatroom": chatroom,
            "id": chatroom,
            "senderCallsign": sender_callsign,
        },
    )
    SubElement(
        chat,
        "chatgrp",
        {"uid0": sender_uid, "uid1": chatroom, "id": chatroom},
    )
    SubElement(
        detail,
        "link",
        {"uid": link_uid or sender_uid, "type": link_type, "relation": "p-p"},
    )
    remarks = SubElement(
        detail,
        "remarks",
        {
            "source": f"BAO.F.ATAK.{sender_uid}",
            "to": chatroom,
            "time": now_s,
        },
    )
    remarks.text = message_body
    SubElement(detail, "contact", {"callsign": sender_callsign})
    if marti_dest_group:
        marti = SubElement(detail, "marti")
        SubElement(marti, "dest", {"group": marti_dest_group})
    return tostring(event, encoding="unicode")


def build_disconnect_xml(*, uid: str, callsign: str) -> str:
    now = datetime.now(UTC)
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
