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
    assert "AES-256 0x84" in result.reason
    assert "KID 1" in result.reason


def test_describe_cipher_known_and_unknown():
    from radiotak.services.traffic_keys import describe_cipher

    adp = describe_cipher(0xAA)
    assert adp["name"] == "ADP"
    assert adp["algid_hex"] == "AA"
    assert adp["algorithm"] == "ADP"
    assert adp["label"] == "ADP 0xAA"
    aes = describe_cipher("84")
    assert aes["algid"] == 0x84
    assert aes["name"] == "AES-256"
    assert describe_cipher(132)["name"] == "AES-256"
    unknown = describe_cipher(0x9F)
    assert unknown["label"] == "ALGID 0x9F"
    assert unknown["algorithm"] == "OTHER"
    assert describe_cipher(None)["label"] == ""


def test_resolve_ids_from_details_and_hex_fields():
    from radiotak.services.traffic_keys import resolve_encryption_ids

    alg, kid = resolve_encryption_ids(
        details="ENCRYPTED ALG: AA KEY ID: 12 TG 30008",
    )
    assert alg == 0xAA
    assert kid == 12
    alg, kid = resolve_encryption_ids(algorithm_id_hex="AA", key_id="12")
    assert alg == 0xAA
    assert kid == 12
    alg, kid = resolve_encryption_ids(algorithm_id=132, algorithm_id_hex="84", key_id=1)
    assert alg == 0x84
    assert kid == 1


def test_encrypted_reason_three_states():
    from radiotak.services.traffic_keys import encrypted_reason

    missing = encrypted_reason(talkgroup="30008", algid=None, key_id=None, key_loaded=False)
    assert "cipher ID not in this event" in missing
    assert "no matching key" not in missing
    unmatched = encrypted_reason(talkgroup="30008", algid=0xAA, key_id=12, key_loaded=False)
    assert unmatched == "ENCRYPTED TG 30008 · ADP 0xAA KID 12 · no matching key"
    matched = encrypted_reason(talkgroup="30008", algid=0xAA, key_id=12, key_loaded=True)
    assert matched == "ENCRYPTED TG 30008 · ADP 0xAA KID 12 · key on file"


def test_collect_heard_keysets_distinct(db_env):
    db, _ = db_env
    from sqlalchemy import select

    from radiotak.db import RadioIdentity
    from radiotak.gateway.pipeline import LocationPipeline
    from radiotak.services.traffic_keys import collect_heard_keysets

    pipe = LocationPipeline()
    pipe.process_dict(
        db,
        {
            "schema": "sdr2tak.decode.v1",
            "radio_id": "4061872",
            "talkgroup": "30008",
            "protocol": "P25",
            "encrypted": True,
            "algorithm_id": 0xAA,
            "key_id": 12,
            "observed_at": "2026-09-04T15:00:00Z",
        },
    )
    identities = list(db.scalars(select(RadioIdentity)))
    rows = collect_heard_keysets(identities=identities, events=[])
    assert len(rows) == 1
    assert rows[0]["algorithm"] == "ADP"
    assert rows[0]["key_id"] == 12
    assert rows[0]["talkgroup"] == "30008"
    assert "alg=ADP" in rows[0]["fill_href"]
    assert "kid=12" in rows[0]["fill_href"]
