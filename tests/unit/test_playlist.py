"""Playlist writer and frequency parsing."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("RADIOTAK_DATA_DIR", str(Path(__file__).resolve().parents[2] / ".data-test"))

import pytest

from modules.sdr_location_gateway.sdrtrunk.playlist import (
    ensure_export_properties,
    ensure_hide_calibration_dialog,
    hz_to_mhz_str,
    parse_frequencies,
    write_p25_playlist,
    write_playlist,
)


def test_parse_mhz_and_hz():
    assert parse_frequencies("851.0125") == [851012500]
    assert parse_frequencies("851.0125, 851.5125") == [851012500, 851512500]
    assert parse_frequencies("851012500") == [851012500]
    assert parse_frequencies("851.0125\n851.5125") == [851012500, 851512500]
    assert parse_frequencies("  ") == []


def test_parse_rejects_junk():
    with pytest.raises(ValueError):
        parse_frequencies("not-a-freq")
    with pytest.raises(ValueError):
        parse_frequencies("0")


def test_hz_to_mhz_str():
    assert hz_to_mhz_str(851012500) == "851.0125"
    assert hz_to_mhz_str(851000000) == "851"


def test_write_playlist_v2(tmp_path):
    path = tmp_path / "default.xml"
    write_playlist(
        path,
        [
            {
                "name": "County P25",
                "protocol": "P25",
                "site": "12",
                "frequencies_hz": [851012500, 851512500],
                "auto_start": True,
            }
        ],
    )
    xml = path.read_text(encoding="utf-8")
    assert 'version="4"' in xml
    assert 'name="County P25"' in xml
    assert 'type="decodeConfigP25Phase1"' in xml
    assert 'ignore_data_calls="false"' in xml
    assert "851012500" in xml
    assert "851512500" in xml
    assert "sourceConfigTunerMultipleFrequency" in xml


def test_write_p25_wrapper(tmp_path):
    path = tmp_path / "legacy.xml"
    write_p25_playlist(path, system_name="Demo", control_channels_mhz=[851.0125])
    xml = path.read_text(encoding="utf-8")
    assert "851012500" in xml
    assert 'sourceConfigTuner"' in xml or 'type="sourceConfigTuner"' in xml


def test_playlist_dir_is_sdrtrunk_home(tmp_path):
    from types import SimpleNamespace

    from modules.sdr_location_gateway.sdrtrunk.playlist import default_playlist_path

    settings = SimpleNamespace(data_dir=tmp_path)
    assert default_playlist_path(settings) == tmp_path / "SDRTrunk" / "playlist" / "default.xml"


def test_listen_toggle_skips_disabled(tmp_path):
    from types import SimpleNamespace

    from modules.sdr_location_gateway.sdrtrunk.playlist import (
        is_listening,
        set_row_listening,
        systems_from_db_rows,
        write_playlist,
    )

    row = SimpleNamespace(
        enabled=True,
        name="County",
        protocol="P25",
        config={"site": "1", "frequencies_hz": [851012500], "auto_start": True},
    )
    assert is_listening(row) is True
    set_row_listening(row, False)
    assert row.enabled is False
    assert row.config["auto_start"] is False
    assert is_listening(row) is False
    assert systems_from_db_rows([row]) == []

    set_row_listening(row, True)
    systems = systems_from_db_rows([row])
    assert len(systems) == 1
    path = write_playlist(tmp_path / "default.xml", systems)
    xml = path.read_text(encoding="utf-8")
    assert 'enabled="true"' in xml
    assert "851012500" in xml


def test_assign_listen_states_one_tuner():
    from modules.sdr_location_gateway.sdrtrunk.playlist import assign_listen_states

    assert assign_listen_states([False, False], 1) == ["off", "off"]
    assert assign_listen_states([True, False, True], 1) == ["active", "off", "starved"]
    assert assign_listen_states([True, True, True], 1) == ["active", "starved", "starved"]
    assert assign_listen_states([True, True, True], 2) == ["active", "active", "starved"]
    assert assign_listen_states([True, True], 2) == ["active", "active"]
    assert assign_listen_states([True], 0) == ["starved"]


def test_ensure_export_properties_appends_missing_keys(tmp_path):
    from types import SimpleNamespace

    settings = SimpleNamespace(data_dir=tmp_path)
    path = tmp_path / "SDRTrunk" / "SDRTrunk.properties"
    path.parent.mkdir(parents=True)
    path.write_text("spectral.display.enabled=true\n", encoding="utf-8")
    ensure_export_properties(settings)
    text = path.read_text(encoding="utf-8")
    assert "spectral.display.enabled=true" in text
    assert "spectrum_export_enabled=true" in text
    assert "spectrum_export_port=29501" in text
    assert "geo_event_export_port=29500" in text
    assert "traffic_keys_path=" in text
    assert str(tmp_path).replace("\\", "/") in text.replace("\\", "/")
    ensure_export_properties(settings)
    assert text.count("spectrum_export_enabled=true") == 1
    prefs = (
        tmp_path
        / ".java"
        / ".userPrefs"
        / "io"
        / "github"
        / "dsheirer"
        / "preference"
        / "calibration"
        / "prefs.xml"
    )
    assert prefs.is_file()
    prefs_text = prefs.read_text(encoding="utf-8")
    assert 'key="hide.calibration.dialog"' in prefs_text
    assert 'key="vector.enabled"' in prefs_text
    assert 'value="false"' in prefs_text


def test_ensure_hide_calibration_dialog_upserts(tmp_path):
    from types import SimpleNamespace

    from modules.sdr_location_gateway.sdrtrunk.playlist import vector_calibration_prefs_path

    settings = SimpleNamespace(data_dir=tmp_path)
    path = vector_calibration_prefs_path(settings)
    path.parent.mkdir(parents=True)
    path.write_text(
        '<?xml version="1.0"?>\n<map MAP_XML_VERSION="1.0">\n'
        '  <entry key="vector.enabled" value="true"/>\n</map>\n',
        encoding="utf-8",
    )
    ensure_hide_calibration_dialog(settings)
    text = path.read_text(encoding="utf-8")
    assert 'key="vector.enabled"' in text
    assert 'key="hide.calibration.dialog"' in text
    path.write_text(
        text.replace(
            'key="hide.calibration.dialog" value="true"',
            'key="hide.calibration.dialog" value="false"',
            1,
        ),
        encoding="utf-8",
    )
    ensure_hide_calibration_dialog(settings)
    assert 'key="hide.calibration.dialog" value="true"' in path.read_text(encoding="utf-8")
    assert 'key="vector.enabled" value="false"' in path.read_text(encoding="utf-8")


def test_east_tn_tacn_sample_json():
    import json

    sample_path = (
        Path(__file__).resolve().parents[2]
        / "modules"
        / "sdr_location_gateway"
        / "samples"
        / "east_tn_tacn.json"
    )
    data = json.loads(sample_path.read_text(encoding="utf-8"))
    by_id = {s["id"]: s for s in data["systems"]}

    eliz = by_id["elizabethton"]
    assert eliz["name"] == "TACN Elizabethton"
    assert eliz["protocol"] == "P25"
    assert eliz["site"] == "78"
    assert parse_frequencies("\n".join(eliz["frequencies_mhz"])) == [
        854437500,
        854037500,
    ]

    buffalo = by_id["buffalo_mtn"]
    assert buffalo["name"] == "TACN Buffalo Mtn"
    assert buffalo["protocol"] == "P25_LSM"
    assert buffalo["site"] == "51"
    assert parse_frequencies("\n".join(buffalo["frequencies_mhz"])) == [
        856237500,
        857237500,
    ]

    sullivan = by_id["sullivan_co"]
    assert sullivan["name"] == "TACN Sullivan Co Simulcast"
    assert sullivan["protocol"] == "P25_LSM"
    assert sullivan["site"] == "50"
    assert sullivan["nac"] == "2AC"
    assert parse_frequencies("\n".join(sullivan["frequencies_mhz"])) == [
        854562500,
        856737500,
    ]
    assert "856.2625" in sullivan["voice_not_cc_mhz"]

    tg_ids = {t["id"] for t in data["talkgroups"]}
    assert "1471" in tg_ids
    assert "4055" in tg_ids
    assert "30102" in tg_ids
    assert hz_to_mhz_str(854437500) == "854.4375"


def test_apply_tuner_slots_keeps_first_auto_start():
    from modules.sdr_location_gateway.sdrtrunk.playlist import apply_tuner_slots

    systems = [
        {"name": "A", "auto_start": True},
        {"name": "B", "auto_start": True},
        {"name": "C", "auto_start": True},
    ]
    apply_tuner_slots(systems, 1)
    assert systems[0]["auto_start"] is True
    assert systems[1]["auto_start"] is False
    assert systems[2]["auto_start"] is False
