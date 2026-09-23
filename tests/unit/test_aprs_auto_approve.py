"""APRS auto-approve units for TAK with default stale."""

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


def test_auto_approve_creates_forwarding_unit_with_default_stale(db_env):
    from modules.aprs_rf_gateway.service import ensure_aprs_unit_approved

    identity = ensure_aprs_unit_approved(db_env, "W4TEST-9", alias="W4TEST-9")
    assert identity.forward_to_tak is True
    assert identity.enabled is True
    assert identity.system_id == "APRS"
    assert identity.stale_seconds == 0
    assert identity.callsign == "W4TEST-9"


def test_auto_approve_respects_disabled_unit(db_env):
    from modules.aprs_rf_gateway.service import ensure_aprs_unit_approved
    from radiotak.db import RadioIdentity

    row = RadioIdentity(
        radio_id="N0BLOCK-1",
        system_id="APRS",
        enabled=False,
        forward_to_tak=False,
        stale_seconds=600,
    )
    db_env.add(row)
    db_env.commit()

    identity = ensure_aprs_unit_approved(db_env, "N0BLOCK-1")
    assert identity.enabled is False
    assert identity.forward_to_tak is False
    assert identity.stale_seconds == 600


def test_position_with_auto_approve_forwards(db_env, monkeypatch):
    from modules.aprs_rf_gateway import service as aprs_service
    from radiotak.gateway.identities import find_identity

    monkeypatch.setattr(
        aprs_service,
        "load_settings",
        lambda: {"auto_approve_units": True, "enable_rf": True, "enable_is": False},
    )

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    ok = aprs_service._handle_position(
        {
            "schema": "sdr2tak.location.v1",
            "decoder": "direwolf",
            "protocol": "APRS",
            "system_id": "APRS",
            "radio_id": "KD4FPQ-9",
            "source_alias": "KD4FPQ-9",
            "latitude": 36.35,
            "longitude": -82.21,
            "observed_at": now,
        },
        {"auto_approve_units": True},
    )
    assert ok is True
    identity = find_identity(db_env, "KD4FPQ-9", "APRS")
    assert identity is not None
    assert identity.forward_to_tak is True
    assert identity.stale_seconds == 0


def test_position_without_auto_approve_still_observes(db_env):
    from modules.aprs_rf_gateway import service as aprs_service
    from radiotak.gateway.identities import find_identity

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    ok = aprs_service._handle_position(
        {
            "schema": "sdr2tak.location.v1",
            "decoder": "direwolf",
            "protocol": "APRS",
            "system_id": "APRS",
            "radio_id": "W4OBS-7",
            "source_alias": "W4OBS-7",
            "latitude": 36.3,
            "longitude": -82.2,
            "observed_at": now,
        },
        {"auto_approve_units": False},
    )
    assert ok is True  # counted as processed; pipeline may block forward
    identity = find_identity(db_env, "W4OBS-7", "APRS")
    assert identity is not None
    assert identity.forward_to_tak is False
