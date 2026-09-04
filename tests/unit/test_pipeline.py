"""Pipeline allowlist / forward tests."""

from __future__ import annotations

import os
from datetime import UTC
from pathlib import Path

import pytest

# Isolate data dir before importing app modules that touch settings
os.environ.setdefault("RADIOTAK_DATA_DIR", str(Path(__file__).resolve().parents[2] / ".data-test"))


@pytest.fixture()
def db_env(tmp_path, monkeypatch):
    monkeypatch.setenv("RADIOTAK_DATA_DIR", str(tmp_path))
    import radiotak.db as dbmod
    from radiotak.config import reload_settings

    reload_settings()
    dbmod._engine = None
    dbmod._SessionLocal = None
    from radiotak.db import RadioIdentity, get_session_factory, init_db

    init_db()
    Session = get_session_factory()
    db = Session()
    db.add(
        RadioIdentity(
            radio_id="1234567",
            system_id="TN-P25",
            callsign="UNIT-214",
            forward_to_tak=True,
            enabled=True,
        )
    )
    db.commit()
    yield db
    db.close()


def test_unknown_blocked(db_env):
    from radiotak.gateway.pipeline import LocationPipeline

    pipe = LocationPipeline()
    result = pipe.process_dict(
        db_env,
        {
            "schema": "sdr2tak.location.v1",
            "radio_id": "9999999",
            "system_id": "TN-P25",
            "latitude": 36.3,
            "longitude": -82.28,
            "observed_at": "2026-09-03T15:42:20Z",
        },
    )
    assert result.forwarded is False
    assert "NOT APPROVED" in result.reason


def test_approved_queued(db_env):
    from datetime import datetime

    from radiotak.gateway.pipeline import LocationPipeline

    pipe = LocationPipeline()
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = pipe.process_dict(
        db_env,
        {
            "schema": "sdr2tak.location.v1",
            "radio_id": "1234567",
            "system_id": "TN-P25",
            "latitude": 36.29531,
            "longitude": -82.27922,
            "observed_at": now,
            "protocol": "P25",
        },
    )
    assert result.forwarded is True
    assert result.cot_xml is not None
    assert "UNIT-214" in result.cot_xml
    assert result.cot_uid == "RADIOTAK-TN-P25-1234567"
