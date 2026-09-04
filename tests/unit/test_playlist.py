"""Playlist writer and frequency parsing."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("RADIOTAK_DATA_DIR", str(Path(__file__).resolve().parents[2] / ".data-test"))

import pytest

from modules.sdr_location_gateway.sdrtrunk.playlist import (
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
    assert "ignore_data_calls=\"false\"" in xml
    assert "851012500" in xml
    assert "851512500" in xml
    assert "sourceConfigTunerMultipleFrequency" in xml


def test_write_p25_wrapper(tmp_path):
    path = tmp_path / "legacy.xml"
    write_p25_playlist(path, system_name="Demo", control_channels_mhz=[851.0125])
    xml = path.read_text(encoding="utf-8")
    assert "851012500" in xml
    assert "sourceConfigTuner\"" in xml or 'type="sourceConfigTuner"' in xml


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
