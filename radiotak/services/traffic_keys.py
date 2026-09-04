"""Authorized P25/DMR traffic-key store.

Key material is written under secrets/ (0600). Metadata (ALGID, KID, label) lives
in the database. A decoder key file is published next to SDRTrunk.properties so a
patched SDRTrunk can match heard Key IDs — SDRTrunk itself still does not decrypt.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from radiotak.config import get_settings
from radiotak.db import TrafficKey, utcnow
from radiotak.services.secrets import SecretStore

# P25 ALGID (TIA-102) plus Motorola ADP.
ALGORITHMS: dict[str, dict[str, Any]] = {
    "DES-OFB": {"algid": 0x81, "bytes": 8, "label": "DES-OFB (P25 0x81)"},
    "AES-256": {"algid": 0x84, "bytes": 32, "label": "AES-256 (P25 0x84)"},
    "AES-128": {"algid": 0x85, "bytes": 16, "label": "AES-128 (P25 0x85)"},
    "ADP": {"algid": 0xAA, "bytes": 5, "label": "Motorola ADP / RC4 (0xAA)"},
    "OTHER": {"algid": None, "bytes": None, "label": "Other (enter ALGID + hex)"},
}

_HEX_RE = re.compile(r"[^0-9A-Fa-f]")


def algorithm_choices() -> list[tuple[str, str]]:
    return [(key, meta["label"]) for key, meta in ALGORITHMS.items()]


def decoder_keyfile_path(settings=None) -> Path:
    if settings is None:
        settings = get_settings()
    return Path(settings.data_dir) / "SDRTrunk" / "traffic_keys.json"


def _secret_name(key_id: str) -> str:
    return f"traffic_keys/{key_id}.hex"


def normalize_hex(raw: str) -> str:
    text = _HEX_RE.sub("", (raw or "").strip())
    if text.lower().startswith("0x"):
        text = text[2:]
    text = text.upper()
    if not text:
        raise ValueError("Enter the key as hexadecimal")
    if len(text) % 2:
        raise ValueError("Hex key must have an even number of digits")
    return text


def parse_int_id(raw: str | int, *, name: str, hex_ok: bool = True) -> int:
    if isinstance(raw, int):
        value = raw
    else:
        text = str(raw or "").strip().lower()
        if not text:
            raise ValueError(f"{name} is required")
        try:
            value = int(text, 16) if hex_ok and text.startswith("0x") else int(text, 10)
        except ValueError as exc:
            if hex_ok:
                try:
                    value = int(text, 16)
                except ValueError:
                    raise ValueError(f"Invalid {name}") from exc
            else:
                raise ValueError(f"Invalid {name}") from exc
    if value < 0 or value > 0xFFFF:
        raise ValueError(f"{name} must be 0–65535")
    return value


def validate_key(
    *,
    algorithm: str,
    key_hex: str,
    algorithm_id: str | int | None = None,
) -> tuple[str, int, str, int]:
    algo = (algorithm or "AES-256").strip().upper()
    if algo not in ALGORITHMS:
        raise ValueError("Unknown algorithm")
    meta = ALGORITHMS[algo]
    hex_key = normalize_hex(key_hex)
    length = len(hex_key) // 2
    expected = meta["bytes"]
    if expected is not None and length != expected:
        raise ValueError(
            f"{algo} keys are {expected} bytes ({expected * 2} hex digits), got {length}"
        )
    if expected is None and not (1 <= length <= 64):
        raise ValueError("Key length must be 1–64 bytes")
    if meta["algid"] is not None:
        algid = int(meta["algid"])
    else:
        if algorithm_id is None or str(algorithm_id).strip() == "":
            raise ValueError("ALGID is required for Other")
        algid = parse_int_id(algorithm_id, name="ALGID")
        if algid == 0x80:
            raise ValueError("ALGID 0x80 is unencrypted — no key needed")
    return algo, algid, hex_key, length


def list_keys(db: Session) -> list[dict[str, Any]]:
    rows = list(db.scalars(select(TrafficKey).order_by(TrafficKey.created_at.desc())))
    return [_public_view(row) for row in rows]


def add_key(
    db: Session,
    *,
    label: str,
    protocol: str,
    algorithm: str,
    key_id: str | int,
    key_hex: str,
    algorithm_id: str | int | None = None,
) -> dict[str, Any]:
    name = (label or "").strip() or f"Key {key_id}"
    proto = (protocol or "P25").strip().upper() or "P25"
    kid = parse_int_id(key_id, name="Key ID")
    algo, algid, hex_key, length = validate_key(
        algorithm=algorithm, key_hex=key_hex, algorithm_id=algorithm_id
    )
    existing = db.scalar(
        select(TrafficKey).where(TrafficKey.algorithm_id == algid, TrafficKey.key_id == kid)
    )
    if existing:
        raise ValueError(f"A key for ALGID {algid:#04x} / KID {kid} is already stored")
    row = TrafficKey(
        label=name,
        protocol=proto,
        algorithm=algo,
        algorithm_id=algid,
        key_id=kid,
        key_length_bytes=length,
        secret_ref="",
    )
    db.add(row)
    db.flush()
    ref = _secret_name(row.id)
    SecretStore().write_text(ref, hex_key + "\n")
    row.secret_ref = ref
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    write_decoder_keyfile(db)
    return _public_view(row)


def delete_key(db: Session, key_id: str) -> bool:
    row = db.get(TrafficKey, key_id)
    if not row:
        return False
    if row.secret_ref:
        try:
            SecretStore().delete(row.secret_ref)
        except Exception:  # noqa: BLE001
            pass
    db.delete(row)
    db.commit()
    write_decoder_keyfile(db)
    return True


def write_decoder_keyfile(db: Session | None = None, settings=None) -> Path:
    """Publish keys for the decoder. File mode 0600. Never log contents."""
    close = False
    if db is None:
        from radiotak.db import get_session_factory

        db = get_session_factory()()
        close = True
    try:
        rows = list(
            db.scalars(select(TrafficKey).order_by(TrafficKey.algorithm_id, TrafficKey.key_id))
        )
        store = SecretStore()
        keys: list[dict[str, Any]] = []
        for row in rows:
            hex_key = store.read_text(row.secret_ref) if row.secret_ref else None
            if not hex_key:
                continue
            keys.append(
                {
                    "id": row.id,
                    "label": row.label,
                    "protocol": row.protocol,
                    "algorithm": row.algorithm,
                    "algorithm_id": row.algorithm_id,
                    "algorithm_id_hex": f"{row.algorithm_id:02X}",
                    "key_id": row.key_id,
                    "key_hex": hex_key.strip(),
                }
            )
        path = decoder_keyfile_path(settings)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": "radiotak.traffic_keys.v1",
            "note": (
                "Authorized traffic keys from RadioTAK. SDRTrunk matches ALGID+KID on "
                "encrypted calls; it does not decrypt audio unless a future decoder "
                "build applies the key."
            ),
            "keys": keys,
        }
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        try:
            if os.name != "nt":
                os.chmod(path, 0o600)
        except OSError:
            pass
        return path
    finally:
        if close:
            db.close()


def matching_key(
    db: Session,
    algorithm_id: str | int | None,
    key_id: str | int | None,
) -> dict[str, Any] | None:
    if algorithm_id is None or key_id is None:
        return None
    try:
        alg = parse_int_id(algorithm_id, name="ALGID")
        kid = parse_int_id(key_id, name="Key ID")
    except ValueError:
        return None
    row = db.scalar(
        select(TrafficKey).where(TrafficKey.algorithm_id == alg, TrafficKey.key_id == kid)
    )
    return _public_view(row) if row else None


def _public_view(row: TrafficKey) -> dict[str, Any]:
    return {
        "id": row.id,
        "label": row.label,
        "protocol": row.protocol,
        "algorithm": row.algorithm,
        "algorithm_id": row.algorithm_id,
        "algorithm_id_hex": f"{row.algorithm_id:02X}",
        "key_id": row.key_id,
        "key_length_bytes": row.key_length_bytes,
        "created_at": row.created_at,
    }
