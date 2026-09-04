"""Event bus timestamps for Live Events."""

from __future__ import annotations

from radiotak.gateway.events import EventBus


def test_publish_stamps_missing_ts():
    bus = EventBus()
    bus.publish({"type": "heard", "radio_id": "4140091"})
    event = bus.history[0]
    assert event["type"] == "heard"
    assert isinstance(event["ts"], float)
    assert event["ts"] > 0


def test_publish_keeps_existing_ts():
    bus = EventBus()
    bus.publish({"type": "heard", "ts": 1756998000.0})
    assert bus.history[0]["ts"] == 1756998000.0
