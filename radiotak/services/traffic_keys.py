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
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from radiotak.config import get_settings
from radiotak.db import TrafficKey, utcnow
from radiotak.services.secrets import SecretStore

# P25 ALGID (TIA-102) plus Motorola ADP.
ALGORITHMS: dict[str, dict[str, Any]] = {
    "DES-OFB": {"algid": 0x81, "bytes": 8, "label": "DES-OFB / DES-XL (P25 0x81)"},
    "AES-256": {"algid": 0x84, "bytes": 32, "label": "AES-256 (P25 0x84)"},
    "AES-128": {"algid": 0x85, "bytes": 16, "label": "AES-128 (P25 0x85)"},
    "ADP": {"algid": 0xAA, "bytes": 5, "label": "Motorola ADP / RC4 (0xAA)"},
    "OTHER": {"algid": None, "bytes": None, "label": "Other (enter ALGID + hex)"},
}

# Short names for Live Events / Units. Unknown IDs stay "ALGID 0xNN".
ALGID_NAMES: dict[int, str] = {
    0x80: "Clear",
    0x81: "DES-OFB / DES-XL",
    0x84: "AES-256",
    0x85: "AES-128",
    0xAA: "ADP",
}
ALGID_STORE: dict[int, str] = {
    0x81: "DES-OFB",
    0x84: "AES-256",
    0x85: "AES-128",
    0xAA: "ADP",
}
# TIA-102 registry values used when deciding decimal vs hex (e.g. "84" vs 132).
_KNOWN_ALGIDS = frozenset(
    {0x80, 0x81, 0x83, 0x84, 0x85, 0x86, 0x89, 0x9F, 0xAA, *ALGID_NAMES}
)

_HEX_RE = re.compile(r"[^0-9A-Fa-f]")
_ALG_KEY = re.compile(
    r"(?:ALG(?:ORITHM)?(?:\s*ID)?|ALGID)\s*[:=]\s*(?:0x)?([0-9A-Fa-f]+)"
    r".*?(?:KEY(?:\s*ID)?|KID)\s*[:=]\s*(?:0x)?([0-9A-Fa-f]+)",
    re.IGNORECASE | re.DOTALL,
)
_ALG_ONLY = re.compile(
    r"(?:ALG(?:ORITHM)?(?:\s*ID)?|ALGID)\s*[:=]\s*(?:0x)?([0-9A-Fa-f]+)",
    re.IGNORECASE,
)
_KID_ONLY = re.compile(
    r"(?:KEY(?:\s*ID)?|KID)\s*[:=]\s*(?:0x)?([0-9A-Fa-f]+)",
    re.IGNORECASE,
)
_MI_RE = re.compile(
    r"(?:\bMI\b|MESSAGE\s*INDICATOR)\s*[:=]\s*(?:0x)?([0-9A-Fa-f]{6,})",
    re.IGNORECASE,
)

CLEAR = "CLEAR"
ENCRYPTED_METADATA_ONLY = "ENCRYPTED_METADATA_ONLY"
ENCRYPTED_KEY_NOT_AVAILABLE = "ENCRYPTED_KEY_NOT_AVAILABLE"
ENCRYPTED_AUTHORIZED_KEY_AVAILABLE = "ENCRYPTED_AUTHORIZED_KEY_AVAILABLE"
UNSUPPORTED_ENCRYPTION_ALGORITHM = "UNSUPPORTED_ENCRYPTION_ALGORITHM"


def algorithm_choices() -> list[tuple[str, str]]:
    return [(key, meta["label"]) for key, meta in ALGORITHMS.items()]


def coerce_algid(raw: str | int | None) -> int | None:
    """Parse an ALGID from decoder JSON (decimal, 0x-prefixed, or 2-digit hex)."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if 0 <= raw <= 0xFFFF else None
    text = str(raw).strip()
    if not text:
        return None
    if text.lower().startswith("0x"):
        try:
            value = int(text, 16)
        except ValueError:
            return None
        return value if 0 <= value <= 0xFFFF else None
    try:
        dec = int(text, 10)
    except ValueError:
        try:
            value = int(text, 16)
        except ValueError:
            return None
        return value if 0 <= value <= 0xFFFF else None
    if dec in _KNOWN_ALGIDS or dec > 255:
        return dec if 0 <= dec <= 0xFFFF else None
    if re.fullmatch(r"[0-9A-Fa-f]{1,2}", text):
        hx = int(text, 16)
        if hx in _KNOWN_ALGIDS:
            return hx
    return dec if 0 <= dec <= 0xFFFF else None


def coerce_kid(raw: str | int | None) -> int | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        return None
    try:
        return parse_int_id(raw, name="Key ID")
    except ValueError:
        return None


def parse_message_indicator(
    message_indicator: str | None = None,
    message_indicator_hex: str | None = None,
    details: str | None = None,
) -> str | None:
    """Return MI hex only when the decoder actually supplied it. Never invent."""
    for raw in (message_indicator, message_indicator_hex):
        text = str(raw or "").strip().upper().removeprefix("0X")
        if len(text) >= 6 and all(c in "0123456789ABCDEF" for c in text):
            return text
    if not details:
        return None
    match = _MI_RE.search(details)
    if not match:
        return None
    return match.group(1).upper()


def decrypt_state(
    *,
    encrypted: bool,
    algid: int | None,
    key_id: int | None,
    key_loaded: bool,
) -> str:
    """Explicit encryption state. Does not imply any unknown-key recovery."""
    if not encrypted:
        return CLEAR
    if algid is None and key_id is None:
        return ENCRYPTED_METADATA_ONLY
    if algid is not None and algid not in _KNOWN_ALGIDS and algid != 0x80:
        if not key_loaded:
            return UNSUPPORTED_ENCRYPTION_ALGORITHM
    if key_loaded:
        return ENCRYPTED_AUTHORIZED_KEY_AVAILABLE
    return ENCRYPTED_KEY_NOT_AVAILABLE


def parse_ids_from_details(details: str | None) -> tuple[int | None, int | None]:
    """Pull ALGID / KID from SDRTrunk call-details text when JSON fields are empty."""
    if not details:
        return None, None
    match = _ALG_KEY.search(details)
    if match:
        return coerce_algid(match.group(1)), coerce_kid(match.group(2))
    alg_m = _ALG_ONLY.search(details)
    kid_m = _KID_ONLY.search(details)
    alg = coerce_algid(alg_m.group(1)) if alg_m else None
    kid = coerce_kid(kid_m.group(1)) if kid_m else None
    return alg, kid


def resolve_encryption_ids(
    *,
    algorithm_id: str | int | None = None,
    algorithm_id_hex: str | int | None = None,
    key_id: str | int | None = None,
    details: str | None = None,
) -> tuple[int | None, int | None]:
    """Prefer structured decoder fields; fall back to the details string."""
    alg = coerce_algid(algorithm_id)
    if alg is None:
        alg = coerce_algid(algorithm_id_hex)
    kid = coerce_kid(key_id)
    if alg is None or kid is None:
        d_alg, d_kid = parse_ids_from_details(details)
        if alg is None:
            alg = d_alg
        if kid is None:
            kid = d_kid
    return alg, kid


def describe_cipher(algid: str | int | None) -> dict[str, Any]:
    parsed = coerce_algid(algid)
    if parsed is None:
        return {
            "algorithm": None,
            "name": None,
            "algid": None,
            "algid_hex": None,
            "label": "",
        }
    hex_s = f"{parsed:02X}"
    store = ALGID_STORE.get(parsed)
    if parsed in ALGID_NAMES:
        name = ALGID_NAMES[parsed]
        label = f"{name} 0x{hex_s}"
    else:
        name = f"ALGID 0x{hex_s}"
        label = name
    return {
        "algorithm": store or "OTHER",
        "name": name,
        "algid": parsed,
        "algid_hex": hex_s,
        "label": label,
    }


def encrypted_badge(
    *,
    algid: str | int | None,
    key_id: str | int | None,
    key_loaded: bool = False,
) -> str:
    bits = ["Encrypted"]
    cipher = describe_cipher(algid)
    if cipher["label"]:
        bits.append(cipher["label"])
    kid = coerce_kid(key_id)
    if kid is not None:
        bits.append(f"KID {kid}")
    if key_loaded:
        bits.append("key on file")
    return " · ".join(bits)


def encrypted_reason(
    *,
    talkgroup: str | None,
    algid: str | int | None,
    key_id: str | int | None,
    key_loaded: bool,
) -> str:
    tg = (str(talkgroup).strip() if talkgroup is not None else "") or None
    head = f"ENCRYPTED TG {tg}" if tg else "ENCRYPTED CALL"
    cipher = describe_cipher(algid)
    kid = coerce_kid(key_id)
    if cipher["algid"] is None and kid is None:
        return f"{head} · cipher ID not in this event"
    slot_bits: list[str] = []
    if cipher["label"]:
        slot_bits.append(cipher["label"])
    if kid is not None:
        slot_bits.append(f"KID {kid}")
    slot = " ".join(slot_bits)
    status = "key on file" if key_loaded else "no matching key"
    return f"{head} · {slot} · {status}"


def collect_heard_keysets(
    *,
    identities: list[Any] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    buckets: dict[tuple[int, int, str], dict[str, Any]] = {}

    def _add(
        alg_raw: str | int | None,
        kid_raw: str | int | None,
        talkgroup: str | None,
        key_loaded: bool = False,
    ) -> None:
        algid = coerce_algid(alg_raw)
        kid = coerce_kid(kid_raw)
        if algid is None or kid is None:
            return
        tg = str(talkgroup).strip() if talkgroup else ""
        key = (algid, kid, tg)
        cipher = describe_cipher(algid)
        rec = buckets.get(key)
        if rec:
            rec["key_loaded"] = rec["key_loaded"] or bool(key_loaded)
            return
        algo = cipher["algorithm"] or "OTHER"
        query = f"alg={quote(algo)}&kid={kid}"
        if algo == "OTHER":
            query += f"&algid={quote('0x' + cipher['algid_hex'])}"
        buckets[key] = {
            "algorithm": algo,
            "name": cipher["name"],
            "algid": algid,
            "algid_hex": cipher["algid_hex"],
            "key_id": kid,
            "talkgroup": tg or None,
            "label": cipher["label"],
            "key_loaded": bool(key_loaded),
            "fill_href": f"/modules/sdr?{query}#traffic-keys",
        }

    for ident in identities or []:
        if not getattr(ident, "last_encrypted", False):
            continue
        _add(
            getattr(ident, "last_encryption_algorithm", None),
            getattr(ident, "last_encryption_key_id", None),
            getattr(ident, "last_talkgroup_id", None),
            bool(getattr(ident, "last_key_loaded", False)),
        )
    for event in events or []:
        if not (event.get("encrypted") or event.get("type") == "encrypted"):
            continue
        _add(
            event.get("algorithm_id"),
            event.get("key_id"),
            event.get("talkgroup"),
            bool(event.get("key_loaded")),
        )
    return sorted(
        buckets.values(), key=lambda row: (row["algid"], row["key_id"], row["talkgroup"] or "")
    )


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
