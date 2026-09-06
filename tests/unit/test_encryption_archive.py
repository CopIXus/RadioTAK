"""Encrypted traffic archive — metadata capture only, no key recovery."""

from __future__ import annotations

import os
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


def _event(**extra):
    payload = {
        "schema": "sdr2tak.decode.v1",
        "radio_id": "4061799",
        "talkgroup": "30008",
        "protocol": "APCO25",
        "encrypted": True,
        "algorithm_id": 170,
        "key_id": 12,
        "system_id": "2A5",
        "wacn": "BEE00",
        "nac": "2AC",
        "site_id": "50",
        "rfss": "2",
        "frequency_hz": 854562500,
        "timeslot": 1,
        "p25_phase": "2",
        "observed_at": "2026-09-05T23:12:14Z",
    }
    payload.update(extra)
    return payload


def test_archive_stores_system_and_cipher_metadata(db_env):
    from sqlalchemy import select

    from radiotak.db import EncryptedTrafficEvent
    from radiotak.gateway.pipeline import LocationPipeline
    from radiotak.services.traffic_keys import ENCRYPTED_KEY_NOT_AVAILABLE

    pipe = LocationPipeline()
    result = pipe.process_dict(db_env, _event())
    assert result.heard is True
    row = db_env.scalar(select(EncryptedTrafficEvent))
    assert row is not None
    assert row.source_radio_id == "4061799"
    assert row.talkgroup_id == "30008"
    assert row.system_id == "2A5"
    assert row.wacn == "BEE00"
    assert row.nac == "2AC"
    assert row.site_id == "50"
    assert row.algorithm_id == 0xAA
    assert row.key_id == 12
    assert row.decrypt_state == ENCRYPTED_KEY_NOT_AVAILABLE
    assert row.raw_event_json["schema"] == "sdr2tak.decode.v1"
    assert "key_hex" not in (row.raw_event_json or {})


def test_archive_stores_identifier_context_and_session(db_env):
    from sqlalchemy import select

    from radiotak.db import CaptureSession, EncryptedTrafficEvent, RadioSystem
    from radiotak.gateway.pipeline import LocationPipeline

    db_env.add(
        RadioSystem(
            name="Demo Simulcast",
            protocol="P25_LSM",
            config={"site": "50", "frequencies_hz": [854562500], "auto_start": True},
        )
    )
    db_env.commit()
    pipe = LocationPipeline()
    pipe.process_dict(
        db_env,
        _event(
            source_type="RADIO",
            destination_type="TALKGROUP",
            uplink_frequency_hz=809562500,
            encryption_header_present=True,
            emergency=True,
            unit_status="0",
            lra="1",
        ),
    )
    row = db_env.scalar(select(EncryptedTrafficEvent))
    assert row.source_type == "RADIO"
    assert row.destination_type == "TALKGROUP"
    assert row.uplink_frequency_hz == 809562500
    assert row.encryption_header_present is True
    assert row.emergency is True
    assert row.lra == "1"
    session = db_env.scalar(select(CaptureSession))
    assert session is not None
    assert session.system == "Demo Simulcast"
    assert session.site == "50"
    assert session.control_channel == "854562500"


def test_archive_dedupes_same_call_window(db_env):
    from sqlalchemy import select, func

    from radiotak.db import EncryptedTrafficEvent
    from radiotak.gateway.pipeline import LocationPipeline

    pipe = LocationPipeline()
    pipe.process_dict(db_env, _event(observed_at="2026-09-05T23:12:14Z"))
    pipe.process_dict(db_env, _event(observed_at="2026-09-05T23:12:20Z"))
    count = db_env.scalar(select(func.count()).select_from(EncryptedTrafficEvent))
    assert count == 1
    row = db_env.scalar(select(EncryptedTrafficEvent))
    assert row.hear_count == 2


def test_mi_is_stored_only_when_present(db_env):
    from sqlalchemy import select

    from radiotak.db import EncryptedTrafficEvent
    from radiotak.gateway.pipeline import LocationPipeline

    pipe = LocationPipeline()
    pipe.process_dict(
        db_env,
        _event(
            details="CALL_ENCRYPTED ALG: 0x81 KEY ID: 14 MI: 0A1B2C3D4E5F607182",
            algorithm_id=None,
            key_id=None,
        ),
    )
    row = db_env.scalar(select(EncryptedTrafficEvent))
    assert row.message_indicator == "0A1B2C3D4E5F607182"
    assert row.algorithm_id == 0x81
    assert row.key_id == 14


def test_authorized_key_sets_decrypt_state(db_env):
    from radiotak.gateway.pipeline import LocationPipeline
    from radiotak.services.traffic_keys import (
        ENCRYPTED_AUTHORIZED_KEY_AVAILABLE,
        add_key,
    )

    add_key(
        db_env,
        label="ADP 12",
        protocol="P25",
        algorithm="ADP",
        key_id=12,
        key_hex="AA" * 5,
    )
    seen = []
    pipe = LocationPipeline()
    pipe.add_listener(seen.append)
    result = pipe.process_dict(db_env, _event())
    assert "key on file" in result.reason
    assert seen[0]["decrypt_state"] == ENCRYPTED_AUTHORIZED_KEY_AVAILABLE


def test_export_jsonl_omits_secrets(db_env):
    from radiotak.gateway.pipeline import LocationPipeline
    from radiotak.services.encryption_archive import export_events

    pipe = LocationPipeline()
    pipe.process_dict(db_env, _event())
    name, media, payload = export_events(db_env, fmt="jsonl")
    text = payload.decode("utf-8")
    assert "4061799" in text
    assert "key_hex" not in text
    assert name.endswith(".jsonl")
    assert "json" in media
