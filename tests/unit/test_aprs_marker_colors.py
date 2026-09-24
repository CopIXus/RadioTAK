"""APRS RF vs IS marker colors and soft tuner exclusivity."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("RADIOTAK_DATA_DIR", str(Path(__file__).resolve().parents[2] / ".data-test"))


def test_aprs_transport_from_raw_event():
    from modules.aprs_rf_gateway.settings import aprs_transport_from_raw_event

    assert aprs_transport_from_raw_event("aprs_uncompressed_rf") == "rf"
    assert aprs_transport_from_raw_event("aprs_compressed_is") == "is"
    assert aprs_transport_from_raw_event("MOTOROLA_UNIT_GPS") is None
    assert aprs_transport_from_raw_event(None) is None


def test_marker_color_for_transport(tmp_path, monkeypatch):
    monkeypatch.setenv("RADIOTAK_DATA_DIR", str(tmp_path))
    from radiotak.config import reload_settings

    reload_settings()
    from modules.aprs_rf_gateway.settings import marker_color_for_transport, save_settings

    save_settings({"marker_color_rf": "#aabbcc", "marker_color_is": "#112233"})
    assert marker_color_for_transport("rf") == "#aabbcc"
    assert marker_color_for_transport("is") == "#112233"
    assert marker_color_for_transport(None) is None


def test_pipeline_aprs_color_override(tmp_path, monkeypatch):
    monkeypatch.setenv("RADIOTAK_DATA_DIR", str(tmp_path))
    from radiotak.config import reload_settings

    reload_settings()
    from modules.aprs_rf_gateway.settings import save_settings
    from radiotak.gateway import LocationEventIn
    from radiotak.gateway.pipeline import _aprs_marker_color

    save_settings({"marker_color_rf": "#22c55e", "marker_color_is": "#3b82f6"})
    rf = LocationEventIn(
        decoder="direwolf",
        protocol="APRS",
        system_id="APRS",
        radio_id="W4TEST-9",
        latitude=36.3,
        longitude=-82.3,
        observed_at="2026-09-23T16:00:00Z",
        raw_event_type="aprs_uncompressed_rf",
    )
    is_ev = rf.model_copy(update={"raw_event_type": "aprs_uncompressed_is"})
    other = rf.model_copy(update={"protocol": "P25", "system_id": "TN-P25", "raw_event_type": "GPS"})
    assert _aprs_marker_color(rf) == "#22c55e"
    assert _aprs_marker_color(is_ev) == "#3b82f6"
    assert _aprs_marker_color(other) is None


def test_exclusivity_allows_parallel_with_two_tuners(monkeypatch):
    from radiotak.services import listening as lis

    monkeypatch.setattr(lis, "sdrtrunk_active", lambda: True)
    monkeypatch.setattr(lis, "direwolf_active", lambda: True)
    monkeypatch.setattr(lis, "tuner_count", lambda: 2)
    assert lis.exclusivity_conflict(want_aprs_rf=True) is None
    assert lis.exclusivity_conflict(want_sdrtrunk=True) is None

    monkeypatch.setattr(lis, "tuner_count", lambda: 1)
    assert lis.exclusivity_conflict(want_aprs_rf=True)
    assert lis.exclusivity_conflict(want_sdrtrunk=True)


def test_save_settings_normalizes_colors(tmp_path, monkeypatch):
    monkeypatch.setenv("RADIOTAK_DATA_DIR", str(tmp_path))
    from radiotak.config import reload_settings

    reload_settings()
    from modules.aprs_rf_gateway.settings import load_settings, save_settings

    save_settings({"marker_color_rf": "not-a-color", "marker_color_is": "#FFF"})
    cfg = load_settings()
    assert cfg["marker_color_rf"] == "#22c55e"
    assert cfg["marker_color_is"] == "#3b82f6"
