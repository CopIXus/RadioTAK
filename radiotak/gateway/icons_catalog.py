"""Curated TAK / CloudTAK marker icons for RadioTAK appearance picker.

CloudTAK stores iconsets in its DB; ATAK only renders ``usericon`` paths when that
iconset is installed on the device. Each catalog entry therefore carries:

- ``iconset_path`` — CoT ``usericon@iconsetpath`` (CloudTAK / ATAK with iconset)
- ``type2525b`` — CoT ``type`` used when the custom icon is missing (avoids a-n-G green square)
- ``shape`` — SVG preview + RadioTAK map glyph (star, disc, triangle, …)
"""

from __future__ import annotations

from typing import Any

# CloudTAK default "Points" / Hiking iconset UUID (widely used on DFPC CloudTAK).
CLOUDTAK_POINTS_UID = "34ae1613-9645-4222-a9d2-e5f243dea2865"

MARKER_ICONS: list[dict[str, Any]] = [
    {
        "id": "cloudtak-hiking-star",
        "label": "Star (CloudTAK Hiking)",
        "group": "CloudTAK",
        "iconset_path": f"{CLOUDTAK_POINTS_UID}:Hiking/star",
        "type2525b": "a-f-G-U-U-S-R",
        "how": "h-g-i-g-o",
        "shape": "star",
        "hint": "CloudTAK Gnd/RADIO UNIT + Hiking/star. ATAK needs the iconset or shows 2525 radio.",
    },
    {
        "id": "cloudtak-hiking-circle",
        "label": "Circle (CloudTAK Hiking)",
        "group": "CloudTAK",
        "iconset_path": f"{CLOUDTAK_POINTS_UID}:Hiking/circle",
        "type2525b": "a-f-G-U-U-S-R",
        "how": "h-g-i-g-o",
        "shape": "disc",
        "hint": "CloudTAK Hiking/circle point.",
    },
    {
        "id": "cloudtak-hiking-triangle",
        "label": "Triangle (CloudTAK Hiking)",
        "group": "CloudTAK",
        "iconset_path": f"{CLOUDTAK_POINTS_UID}:Hiking/triangle",
        "type2525b": "a-f-G-U-U-S-R",
        "how": "h-g-i-g-o",
        "shape": "triangle",
        "hint": "CloudTAK Hiking/triangle point.",
    },
    {
        "id": "cloudtak-hiking-square",
        "label": "Square (CloudTAK Hiking)",
        "group": "CloudTAK",
        "iconset_path": f"{CLOUDTAK_POINTS_UID}:Hiking/square",
        "type2525b": "a-f-G-U-U-S-R",
        "how": "h-g-i-g-o",
        "shape": "square",
        "hint": "CloudTAK Hiking/square point.",
    },
    {
        "id": "atak-spot-map",
        "label": "Colored spot (ATAK Spot Map)",
        "group": "ATAK-safe",
        "iconset_path": "",
        "type2525b": "b-m-p-s-m",
        "how": "h-g-i-g-o",
        "shape": "disc",
        "hint": "No custom iconset — ATAK/CloudTAK tint the Spot Map marker from marker color.",
    },
    {
        "id": "friendly-radio-2525",
        "label": "Friendly radio unit (2525)",
        "group": "ATAK-safe",
        "iconset_path": "",
        "type2525b": "a-f-G-U-U-S-R",
        "how": "h-g-i-g-o",
        "shape": "radio",
        "hint": "MIL-STD friendly ground radio unit — works on ATAK without iconsets.",
    },
    {
        "id": "neutral-ground",
        "label": "Neutral ground (named marker)",
        "group": "ATAK-safe",
        "iconset_path": "",
        "type2525b": "a-n-G",
        "how": "m-g",
        "shape": "square",
        "hint": "Default RadioTAK type — appears as a green square in ATAK without a custom icon.",
    },
]

COT_TYPE_CHOICES: list[tuple[str, str]] = [
    ("a-f-G-U-U-S-R", "Friendly radio unit (Gnd/RADIO UNIT)"),
    ("a-n-G", "Neutral ground (named marker, not a contact)"),
    ("a-u-G", "Unknown ground (named marker, not a contact)"),
    ("a-f-G-E-V", "Friendly vehicle"),
    ("a-h-G", "Hostile ground"),
    ("a-f-G-U-C", "Friendly unit (shows as ATAK contact)"),
    ("b-m-p-s-m", "Spot Map point (colored ATAK spot)"),
]


def list_marker_icons() -> list[dict[str, Any]]:
    return list(MARKER_ICONS)


def find_icon_by_path(iconset_path: str | None) -> dict[str, Any] | None:
    path = (iconset_path or "").strip()
    if not path:
        return None
    for icon in MARKER_ICONS:
        if icon.get("iconset_path") == path:
            return icon
    return None


def find_icon_by_id(icon_id: str | None) -> dict[str, Any] | None:
    want = (icon_id or "").strip()
    if not want:
        return None
    for icon in MARKER_ICONS:
        if icon.get("id") == want:
            return icon
    return None


def shape_for_path(iconset_path: str | None, cot_type: str | None = None) -> str:
    """Map iconset path / CoT type to a RadioTAK map glyph name."""
    found = find_icon_by_path(iconset_path)
    if found:
        return str(found.get("shape") or "disc")
    path = (iconset_path or "").lower()
    if "star" in path:
        return "star"
    if "triangle" in path:
        return "triangle"
    if "square" in path:
        return "square"
    if "circle" in path or "disc" in path:
        return "disc"
    ctype = (cot_type or "").strip()
    if ctype == "a-f-G-U-U-S-R":
        return "radio"
    if ctype == "b-m-p-s-m":
        return "disc"
    if ctype.startswith("a-n-"):
        return "square"
    return "disc"
