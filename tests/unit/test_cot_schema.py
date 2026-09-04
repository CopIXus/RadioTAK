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
    assert 'type="a-n-G"' in xml
    assert "endpoint=" not in xml
    assert "__group" not in xml


def test_detection_default_stale_is_20_minutes():
    xml = build_cot_xml(
        radio_id="1",
        latitude=36.0,
        longitude=-82.0,
        observed_at=datetime(2026, 9, 3, 15, 42, 17, tzinfo=timezone.utc),
        callsign="Engine 4",
    )
    assert 'stale="2026-09-03T16:02:17Z"' in xml
    assert 'callsign="Engine 4"' in xml
    assert "endpoint=" not in xml


def test_presence_is_sa_contact():
    from radiotak.gateway.cot import build_presence_xml

    xml = build_presence_xml(
        uid="RadioTAK-edc90911",
        callsign="CarterCo-RadioTAK",
        latitude=36.3,
        longitude=-82.3,
        group_name="TN Law Enforcement Mutual Aid",
        version="26.0904.0943",
    )
    assert 'uid="RadioTAK-edc90911"' in xml
    assert 'type="a-f-G-U-C"' in xml
    assert 'callsign="CarterCo-RadioTAK"' in xml
    assert 'endpoint="*:-1:stcp"' in xml
    assert 'name="TN Law Enforcement Mutual Aid"' in xml
    assert 'platform="RadioTAK"' in xml


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


def test_decode_schema_does_not_need_gps():
    from radiotak.gateway import DecodeEventIn

    ev = DecodeEventIn.model_validate(
        {
            "schema": "sdr2tak.decode.v1",
            "radio_id": "5550001",
            "encrypted": True,
            "talkgroup": "11025",
            "algorithm_id": 132,
            "key_id": 1,
            "observed_at": "2026-09-04T15:00:00Z",
        }
    )
    assert ev.encrypted is True
    assert ev.talkgroup == "11025"
    assert ev.algorithm_id == "132"
