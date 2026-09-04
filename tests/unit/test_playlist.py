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
    assert 'version="2"' in xml
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
