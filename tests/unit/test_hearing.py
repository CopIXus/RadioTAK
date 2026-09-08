"""Elapsed-time formatting for hearing gauges."""

from __future__ import annotations

from radiotak.services.hearing import format_elapsed


def test_format_elapsed_grows_units():
    assert format_elapsed(None) == "—"
    assert format_elapsed(0) == "0s"
    assert format_elapsed(12) == "12s"
    assert format_elapsed(12.4) == "12s"
    assert format_elapsed(59) == "59s"
    assert format_elapsed(60) == "1:00"
    assert format_elapsed(63) == "1:03"
    assert format_elapsed(3599) == "59:59"
    assert format_elapsed(3600) == "1:00:00"
    assert format_elapsed(2 * 3600 + 13 * 60 + 34) == "2:13:34"
    assert format_elapsed(86400) == "1d 00:00:00"
    assert format_elapsed(3 * 86400 + 23 * 3600 + 13 * 60 + 34) == "3d 23:13:34"
    assert format_elapsed(151734.4) == "1d 18:08:54"


def test_format_elapsed_rejects_junk():
    assert format_elapsed("nope") == "—"
    assert format_elapsed(-5) == "0s"


def test_snapshot_includes_formatted_age(monkeypatch):
    from radiotak.services import hearing as hearing_mod

    monkeypatch.setattr(hearing_mod.time, "time", lambda: 1_000.0)
    gauges = hearing_mod.HearingGauges()
    gauges.last_event_at = 1_000.0 - 151734.4
    monkeypatch.setattr(gauges, "messages_per_min", lambda: 0)
    snap = gauges.snapshot()
    assert snap["last_event_age"] == "1d 18:08:54"
    assert snap["last_event_age_s"] == 151734.4
