"""Authorized traffic-key store (hex never returned after save)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("RADIOTAK_DATA_DIR", str(Path(__file__).resolve().parents[2] / ".data-test"))

AES256 = "A1" * 32


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
    yield db, tmp_path
    db.close()


def test_validate_aes256_length():
    from radiotak.services.traffic_keys import validate_key

    with pytest.raises(ValueError, match="32 bytes"):
        validate_key(algorithm="AES-256", key_hex="00" * 16)
    algo, algid, hex_key, length = validate_key(algorithm="AES-256", key_hex=AES256)
    assert algo == "AES-256"
    assert algid == 0x84
    assert length == 32
    assert hex_key == AES256


def test_add_and_match_key(db_env):
    db, tmp_path = db_env
    from radiotak.services.traffic_keys import (
        add_key,
        decoder_keyfile_path,
        list_keys,
        matching_key,
    )

    row = add_key(
        db,
        label="County AES",
        protocol="P25",
        algorithm="AES-256",
        key_id=1,
        key_hex=AES256,
    )
    assert row["algorithm_id"] == 0x84
    assert row["key_id"] == 1
    assert "key_hex" not in row
    public = list_keys(db)
    assert len(public) == 1
    assert matching_key(db, 0x84, 1)["id"] == row["id"]
    path = decoder_keyfile_path()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["keys"][0]["key_hex"] == AES256
    assert payload["keys"][0]["algorithm_id"] == 132


def test_duplicate_kid_rejected(db_env):
    db, _ = db_env
    from radiotak.services.traffic_keys import add_key

    add_key(db, label="A", protocol="P25", algorithm="AES-256", key_id=1, key_hex=AES256)
    with pytest.raises(ValueError, match="already stored"):
        add_key(db, label="B", protocol="P25", algorithm="AES-256", key_id=1, key_hex="B2" * 32)


def test_pipeline_marks_key_loaded(db_env):
    db, _ = db_env
    from radiotak.gateway.pipeline import LocationPipeline
    from radiotak.services.traffic_keys import add_key

    add_key(db, label="County AES", protocol="P25", algorithm="AES-256", key_id=1, key_hex=AES256)
    pipe = LocationPipeline()
    result = pipe.process_dict(
        db,
        {
            "schema": "sdr2tak.decode.v1",
            "radio_id": "9",
            "talkgroup": "100",
            "encrypted": True,
            "algorithm_id": 132,
            "key_id": 1,
            "observed_at": "2026-09-04T15:00:00Z",
        },
    )
    assert "key on file" in result.reason
