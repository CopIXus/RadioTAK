"""Decode events (encrypted / heard, no GPS) through the pipeline."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

os.environ.setdefault("RADIOTAK_DATA_DIR", str(Path(__file__).resolve().parents[2] / ".data-test"))


@pytest.fixture()
def db_env(tmp_path, monkeypatch):
    monkeypatch.setenv("RADIOTAK_DATA_DIR", str(tmp_path))
    import radiotak.db as dbmod
    from radiotak.config import reload_settings

    reload_settings()
    dbmod._engine = None
    dbmod._SessionLocal = None
    from radiotak.db import get_session_factory, init_db

    init_db()
    Session = get_session_factory()
    db = Session()
    yield db
    db.close()


def test_encrypted_call_creates_unit_without_gps(db_env):
    from sqlalchemy import select

    from radiotak.db import RadioIdentity
    from radiotak.gateway.identities import hear_status
    from radiotak.gateway.pipeline import LocationPipeline

    pipe = LocationPipeline()
    seen = []
    pipe.add_listener(seen.append)
    result = pipe.process_dict(
        db_env,
        {
            "schema": "sdr2tak.decode.v1",
            "radio_id": "5550001",
            "system_id": "TN-P25",
            "talkgroup": "11025",
            "protocol": "P25",
            "encrypted": True,
            "algorithm_id": 132,
            "key_id": 1,
            "observed_at": "2026-09-04T15:00:00Z",
        },
    )
    assert result.heard is True
    assert result.forwarded is False
    assert result.observation is None
    assert "ENCRYPTED" in result.reason
    assert "no matching key" in result.reason
    assert "AES-256 0x84" in result.reason
    assert "KID 1" in result.reason
    assert seen[0]["encryption_badge"] == "Encrypted · AES-256 0x84 · KID 1"
    assert seen[0]["algorithm_name"] == "AES-256"
    assert seen[0]["ts"] == pytest.approx(
        datetime(2026, 9, 4, 15, 0, tzinfo=UTC).timestamp()
    )
    identity = db_env.scalar(select(RadioIdentity).where(RadioIdentity.radio_id == "5550001"))
    assert identity.radio_id == "5550001"
    assert identity.last_encrypted is True
    assert identity.last_talkgroup_id == "11025"
    assert identity.last_latitude is None
    status = hear_status(identity)
    assert status["hear_kind"] == "encrypted"
    assert "no GPS" in status["hear_label"]
    assert seen and seen[0]["type"] == "encrypted"


def test_clear_call_without_gps_is_heard(db_env):
    from radiotak.gateway.identities import hear_status
    from radiotak.gateway.pipeline import LocationPipeline

    pipe = LocationPipeline()
    result = pipe.process_dict(
        db_env,
        {
            "schema": "sdr2tak.decode.v1",
            "radio_id": "5550002",
            "talkgroup": "12001",
            "encrypted": False,
            "observed_at": "2026-09-04T15:00:02Z",
        },
    )
    assert result.heard is True
    from sqlalchemy import select

    from radiotak.db import RadioIdentity

    identity = db_env.scalar(select(RadioIdentity).where(RadioIdentity.radio_id == "5550002"))
    status = hear_status(identity)
    assert status["hear_kind"] == "heard"
    assert identity.last_encrypted is False


def test_encrypted_then_gps_keeps_encrypted_badge(db_env):
    from datetime import datetime

    from sqlalchemy import select

    from radiotak.db import RadioIdentity
    from radiotak.gateway.identities import hear_status
    from radiotak.gateway.pipeline import LocationPipeline

    pipe = LocationPipeline()
    pipe.process_dict(
        db_env,
        {
            "schema": "sdr2tak.decode.v1",
            "radio_id": "1234567",
            "system_id": "TN-P25",
            "talkgroup": "11025",
            "encrypted": True,
            "observed_at": "2026-09-04T15:00:00Z",
        },
    )
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    gps = pipe.process_dict(
        db_env,
        {
            "schema": "sdr2tak.location.v1",
            "radio_id": "1234567",
            "system_id": "TN-P25",
            "latitude": 36.29531,
            "longitude": -82.27922,
            "observed_at": now,
        },
    )
    assert gps.forwarded is False  # not approved
    identity = db_env.scalar(select(RadioIdentity).where(RadioIdentity.radio_id == "1234567"))
    status = hear_status(identity)
    assert identity.last_encrypted is True
    assert status["has_gps"] is True
    assert status["hear_kind"] == "encrypted-gps"


def test_adp_from_details_when_json_ids_missing(db_env):
    from radiotak.gateway.pipeline import LocationPipeline

    pipe = LocationPipeline()
    seen = []
    pipe.add_listener(seen.append)
    result = pipe.process_dict(
        db_env,
        {
            "schema": "sdr2tak.decode.v1",
            "radio_id": "4061799",
            "talkgroup": "30008",
            "protocol": "P25",
            "encrypted": True,
            "details": "CALL_ENCRYPTED ALG: 0xAA KEY ID: 12",
            "observed_at": "2026-09-04T15:01:00Z",
        },
    )
    assert "ADP 0xAA" in result.reason
    assert "KID 12" in result.reason
    assert "no matching key" in result.reason
    assert seen[0]["algorithm_id"] == "AA"
    assert seen[0]["key_id"] == "12"
    assert "ADP 0xAA" in seen[0]["encryption_badge"]


def test_encrypted_call_archives_and_does_not_forward(db_env):
    from sqlalchemy import select

    from radiotak.db import EncryptedTrafficEvent
    from radiotak.gateway.pipeline import LocationPipeline

    pipe = LocationPipeline()
    result = pipe.process_dict(
        db_env,
        {
            "schema": "sdr2tak.decode.v1",
            "radio_id": "5550999",
            "talkgroup": "11025",
            "encrypted": True,
            "algorithm_id": 129,
            "key_id": 14,
            "site_id": "50",
            "observed_at": "2026-09-05T23:12:14Z",
        },
    )
    assert result.forwarded is False
    row = db_env.scalar(select(EncryptedTrafficEvent).where(EncryptedTrafficEvent.source_radio_id == "5550999"))
    assert row is not None
    assert row.site_id == "50"
    assert row.key_id == 14


def test_encrypted_without_cipher_ids(db_env):
    from radiotak.gateway.pipeline import LocationPipeline

    pipe = LocationPipeline()
    result = pipe.process_dict(
        db_env,
        {
            "schema": "sdr2tak.decode.v1",
            "radio_id": "4062000",
            "talkgroup": "30151",
            "encrypted": True,
            "observed_at": "2026-09-04T15:02:00Z",
        },
    )
    assert "cipher ID not in this event" in result.reason
    assert "no matching key" not in result.reason
