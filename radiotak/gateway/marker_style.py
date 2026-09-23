"""Resolve CoT / map marker style from unit + TAK server settings."""

from __future__ import annotations

from typing import Any

from radiotak.gateway.constants import DETECTION_COT_TYPE
from radiotak.gateway.icons_catalog import shape_for_path

FEET_TO_METERS = 0.3048


def feet_to_meters(feet: float) -> float:
    return float(feet) * FEET_TO_METERS


def resolve_style(
    *,
    server: Any = None,
    identity: Any = None,
    radio_id: str = "",
    source_alias: str | None = None,
) -> dict[str, Any]:
    """Unit fields override server defaults when present."""
    srv_callsign = (
        getattr(server, "default_callsign", None) or getattr(server, "callsign", None) or "Radio"
    )
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
        "shape": shape_for_path(icon, cot_type),
    }


def argb_from_hex(hex_color: str, *, alpha: int = 255) -> str:
    """Return signed 32-bit ARGB as a decimal string (ATAK / node-cot wire form).

    CloudTAK GeoJSON uses ``#RRGGBB``; node-cot packs opaque ARGB into a signed
    int32 on ``<color argb="…"/>``. Hex strings like ``ff0010eb`` are ignored by
    ATAK and break Spot Map coloring.
    """
    h = (hex_color or "").strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        h = "06b6d4"
    try:
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
    except ValueError:
        r, g, b = 0x06, 0xB6, 0xD4
    a = max(0, min(255, int(alpha)))
    unsigned = ((a & 0xFF) << 24) | (r << 16) | (g << 8) | b
    if unsigned >= 2**31:
        unsigned -= 2**32
    return str(unsigned)


def iconset_path_for_wire(
    iconset_path: str | None,
    *,
    cot_type: str | None = None,
    marker_color: str | None = None,
) -> str | None:
    """Normalize icon path to ATAK / node-cot wire form.

    CloudTAK stores ``UUID:Group/name``; the CoT stream must use
    ``UUID/Group/name.png``. Spot Map (``b-m-p-s-m``) uses the built-in
    ``COT_MAPPING_SPOTMAP/b-m-p-s-m/{signedARGB}`` path (works on ATAK without
    a custom iconset).
    """
    ctype = (cot_type or "").strip()
    if ctype == "b-m-p-s-m":
        return f"COT_MAPPING_SPOTMAP/b-m-p-s-m/{argb_from_hex(marker_color or '#06b6d4')}"

    path = (iconset_path or "").strip()
    if not path:
        return None
    # Already ATAK Spot Map path
    if path.startswith("COT_MAPPING_SPOTMAP/"):
        return path
    # CloudTAK storage form → wire form
    if ":" in path:
        path = path.replace(":", "/", 1)
        if not path.lower().endswith(".png"):
            path += ".png"
        return path
    if not path.lower().endswith(".png") and "/" in path:
        path += ".png"
    return path
