"""Unit tests for CoT markers, spectrum frames, playlist tuner, marker style."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

from radiotak.gateway.cot import build_cot_xml
from radiotak.gateway.marker_style import argb_from_hex, feet_to_meters, resolve_style
from radiotak.web.help_text import HELP, help_keys


def test_cot_includes_usericon_and_color():
    xml = build_cot_xml(
        radio_id="1",
        latitude=36.0,
        longitude=-82.0,
        observed_at=datetime(2026, 9, 4, 12, 0, 0, tzinfo=UTC),
        callsign="Radio",
        iconset_path="abc:Hiking/star",
        marker_color="#1100ff",
        how="m-g",
        default_ce_m=609.6,
    )
    assert 'iconsetpath="abc:Hiking/star"' in xml
    assert 'argb="ff1100ff"' in xml
    assert 'callsign="Radio"' in xml
    assert 'ce="609.6"' in xml


def test_feet_to_meters_and_argb():
    assert abs(feet_to_meters(2000) - 609.6) < 0.1
    assert argb_from_hex("#1100ff") == "ff1100ff"
    assert argb_from_hex("#abc") == "ffaabbcc"


def test_resolve_style_unit_overrides_server():
    server = SimpleNamespace(
        default_callsign="Radio",
        cot_type_default="a-f-G-U-C",
        iconset_path="uuid:Hiking/star",
        marker_color="#1100ff",
        cot_how="m-g",
        default_ce_feet=2000,
        callsign="GW",
    )
    identity = SimpleNamespace(
        callsign="Engine 4",
        cot_type="a-f-G-E-V-C",
        remarks=None,
        stale_seconds=90,
    )
    style = resolve_style(server=server, identity=identity, radio_id="9")
    assert style["callsign"] == "Engine 4"
    assert style["cot_type"] == "a-f-G-E-V-C"
    assert style["marker_color"] == "#1100ff"
    assert style["iconset_path"] == "uuid:Hiking/star"
    assert style["stale_seconds"] == 90


def test_resolve_style_zero_stale_uses_global():
    server = SimpleNamespace(
        default_callsign="Radio",
        cot_type_default="a-n-G",
        iconset_path="",
        marker_color="#06b6d4",
        cot_how="m-g",
        default_ce_feet=2000,
        callsign="GW",
    )
    identity = SimpleNamespace(
        callsign="Engine 4",
        cot_type="",
        remarks=None,
        stale_seconds=0,
    )
    style = resolve_style(server=server, identity=identity, radio_id="9")
    assert style["cot_type"] == "a-n-G"
    assert style["stale_seconds"] is None


def test_spectrum_parse_and_downsample():
    from modules.sdr_location_gateway.sdrtrunk.spectrum import spectrum_hub

    bins = list(range(1024))
    frame = spectrum_hub.parse_frame(
        '{"bins": ' + str(bins) + ', "f_min": 850e6, "f_max": 860e6, "cc_hz": [851012500]}'
    )
    assert frame is not None
    assert len(frame["bins"]) == 512
    assert frame["cc_hz"] == [851012500]
    assert frame["f_min"] == 850e6
    assert "panel_f_min" not in frame


def test_apply_tuner_center_frequency(tmp_path):
    from types import SimpleNamespace

    from modules.sdr_location_gateway.sdrtrunk.playlist import (
        apply_tuner_center_frequency,
        listening_center_hz,
    )

    cfg_dir = tmp_path / "SDRTrunk" / "configuration"
    cfg_dir.mkdir(parents=True)
    path = cfg_dir / "tuner_configuration.json"
    path.write_text(
        '{"disabledTuners": [], "tunerConfigurations": ['
        '{"type": "r820TTunerConfiguration", "uniqueID": "RTL", "frequency": 101100000}'
        "]}\n",
        encoding="utf-8",
    )
    settings = SimpleNamespace(data_dir=tmp_path)
    out = apply_tuner_center_frequency(854562500, settings)
    assert out == path
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["tunerConfigurations"][0]["frequency"] == 854562500
    assert listening_center_hz(
        [{"auto_start": True, "frequencies_hz": [854562500, 856737500]}]
    ) == 854562500
    assert apply_tuner_center_frequency(854562500, SimpleNamespace(data_dir=tmp_path / "missing")) is None


def test_playlist_preferred_tuner(tmp_path):
    from modules.sdr_location_gateway.sdrtrunk.playlist import systems_from_db_rows, write_playlist

    system = SimpleNamespace(
        enabled=True,
        name="County",
        protocol="P25",
        config={"site": "1", "frequencies_hz": [851012500], "auto_start": True},
    )
    device = SimpleNamespace(
        enabled=True,
        serial_number="00000001",
        name="RTL",
    )
    systems = systems_from_db_rows([system], devices=[device])
    assert systems[0]["preferred_tuner"] == "00000001"
    path = write_playlist(tmp_path / "default.xml", systems)
    text = path.read_text(encoding="utf-8")
    assert "preferred_tuner" in text
    assert "00000001" in text

    nameless = SimpleNamespace(enabled=True, serial_number=None, name="Realtek Semiconductor Corp. RTL2838 DVB-T")
    systems = systems_from_db_rows([system], devices=[nameless])
    assert not systems[0].get("preferred_tuner")
    text = write_playlist(tmp_path / "no-serial.xml", systems).read_text(encoding="utf-8")
    assert "preferred_tuner" not in text


def test_help_registry_nonempty():
    assert "tak.host" in help_keys()
    assert HELP["tak.host"]["what"]
