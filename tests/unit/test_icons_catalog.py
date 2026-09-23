"""Tests for marker icon catalog."""

from __future__ import annotations

from radiotak.gateway.icons_catalog import (
    CLOUDTAK_POINTS_UID,
    find_icon_by_id,
    find_icon_by_path,
    shape_for_path,
)
from radiotak.gateway.marker_style import resolve_style


def test_cloudtak_hiking_star_path():
    icon = find_icon_by_id("cloudtak-hiking-star")
    assert icon is not None
    assert icon["iconset_path"].startswith(CLOUDTAK_POINTS_UID)
    assert icon["iconset_path"].endswith(":Hiking/star")
    assert icon["type2525b"] == "a-f-G-U-U-S-R"
    assert find_icon_by_path(icon["iconset_path"])["id"] == "cloudtak-hiking-star"


def test_shape_for_star_path():
    path = f"{CLOUDTAK_POINTS_UID}:Hiking/star"
    assert shape_for_path(path) == "star"
    assert shape_for_path(None, "a-n-G") == "square"
    assert shape_for_path(None, "a-f-G-U-U-S-R") == "radio"


def test_resolve_style_includes_shape():
    class S:
        default_callsign = "Radio"
        cot_type_default = "a-f-G-U-U-S-R"
        iconset_path = f"{CLOUDTAK_POINTS_UID}:Hiking/star"
        marker_color = "#0010eb"
        cot_how = "h-g-i-g-o"
        default_ce_feet = 2000

    style = resolve_style(server=S(), radio_id="1")
    assert style["shape"] == "star"
    assert style["marker_color"] == "#0010eb"
    assert style["cot_type"] == "a-f-G-U-U-S-R"
