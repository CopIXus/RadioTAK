"""Unit tests for CoT and schema."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from radiotak.gateway import LocationEventIn, stable_cot_uid
from radiotak.gateway.cot import build_cot_xml


def test_stable_uid():
    assert stable_cot_uid("TN-P25", "1234567") == "RADIOTAK-TN-P25-1234567"
    assert stable_cot_uid(None, "1") == "RADIOTAK-UNK-1"


def test_cot_contains_callsign_and_coords():
    xml = build_cot_xml(
        radio_id="1234567",
        latitude=36.29531,
        longitude=-82.27922,
        observed_at=datetime(2026, 9, 3, 15, 42, 17, tzinfo=timezone.utc),
        system_id="TN-P25",
        callsign="Unit 214",
        stale_seconds=120,
    )
    assert 'uid="RADIOTAK-TN-P25-1234567"' in xml
    assert 'callsign="Unit 214"' in xml
    assert 'lat="36.295310"' in xml
    assert 'lon="-82.279220"' in xml
    assert 'stale="2026-09-03T15:44:17Z"' in xml


def test_schema_rejects_null_island():
    with pytest.raises(ValidationError):
        LocationEventIn.model_validate(
            {
                "schema": "sdr2tak.location.v1",
                "radio_id": "1",
                "latitude": 0,
                "longitude": 0,
                "observed_at": "2026-09-03T15:42:17Z",
            }
        )


def test_schema_rejects_bad_lat():
    with pytest.raises(ValidationError):
        LocationEventIn.model_validate(
            {
                "schema": "sdr2tak.location.v1",
                "radio_id": "1",
                "latitude": 999,
                "longitude": -82,
                "observed_at": "2026-09-03T15:42:17Z",
            }
        )


def test_schema_accepts_valid():
    ev = LocationEventIn.model_validate(
        {
            "schema": "sdr2tak.location.v1",
            "radio_id": "1234567",
            "latitude": 36.29531,
            "longitude": -82.27922,
            "observed_at": "2026-09-03T15:42:17.315Z",
            "protocol": "P25",
        }
    )
    assert ev.radio_id == "1234567"
    assert ev.observed_at.tzinfo is not None
