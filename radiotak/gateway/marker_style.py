"""Resolve CoT / map marker style from unit + TAK server settings."""

from __future__ import annotations

from typing import Any, Optional

from radiotak.gateway.constants import DETECTION_COT_TYPE

FEET_TO_METERS = 0.3048


def feet_to_meters(feet: float) -> float:
    return float(feet) * FEET_TO_METERS


def resolve_style(
    *,
    server: Any = None,
    identity: Any = None,
    radio_id: str = "",
    source_alias: Optional[str] = None,
) -> dict[str, Any]:
    """Unit fields override server defaults when present."""
    srv_callsign = getattr(server, "default_callsign", None) or getattr(server, "callsign", None) or "Radio"
    unit_callsign = getattr(identity, "callsign", None) if identity is not None else None
    callsign = unit_callsign or source_alias or srv_callsign or radio_id or "Radio"

    unit_type = (getattr(identity, "cot_type", None) or "").strip() if identity is not None else ""
    cot_type = unit_type or getattr(server, "cot_type_default", None) or DETECTION_COT_TYPE

    icon = getattr(server, "iconset_path", None) or ""
    color = getattr(server, "marker_color", None) or "#06b6d4"
    how = getattr(server, "cot_how", None) or "m-g"
    ce_feet = getattr(server, "default_ce_feet", None)
    if ce_feet is None:
        ce_feet = 2000
    remarks = getattr(identity, "remarks", None) if identity is not None else None
    unit_stale = getattr(identity, "stale_seconds", None) if identity is not None else None
    try:
        stale = int(unit_stale) if unit_stale else None
    except (TypeError, ValueError):
        stale = None
    if stale is not None and stale <= 0:
        stale = None

    return {
        "callsign": callsign,
        "cot_type": cot_type,
        "iconset_path": icon,
        "marker_color": color,
        "how": how,
        "default_ce_feet": float(ce_feet),
        "default_ce_meters": feet_to_meters(float(ce_feet)),
        "remarks": remarks,
        "stale_seconds": stale,
    }


def argb_from_hex(hex_color: str) -> str:
    """Return 8-digit ARGB hex (opaque) for CoT color elements."""
    h = (hex_color or "").strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        h = "06b6d4"
    return "ff" + h.lower()
