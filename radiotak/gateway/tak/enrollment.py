"""TAK certificate enrollment helpers (PyTAK + manual import)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, pkcs12

from radiotak.services.secrets import SecretStore

log = logging.getLogger("radiotak.enrollment")


def parse_certificate_meta(cert_pem: bytes | str) -> dict[str, Any]:
    from cryptography.hazmat.primitives import hashes

    if isinstance(cert_pem, str):
        cert_pem = cert_pem.encode()
    cert = x509.load_pem_x509_certificate(cert_pem)
    not_before = getattr(cert, "not_valid_before_utc", None) or cert.not_valid_before.replace(
        tzinfo=timezone.utc
    )
    not_after = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after.replace(
        tzinfo=timezone.utc
    )
    return {
        "subject": cert.subject.rfc4514_string(),
        "issuer": cert.issuer.rfc4514_string(),
        "serial": format(cert.serial_number, "x"),
        "not_before": not_before,
        "not_after": not_after,
        "fingerprint": cert.fingerprint(hashes.SHA256()).hex(),
    }


def certificate_expiry_warning(not_after: datetime) -> Optional[str]:
    now = datetime.now(timezone.utc)
    if not_after.tzinfo is None:
        not_after = not_after.replace(tzinfo=timezone.utc)
    days = (not_after - now).days
    if days < 0:
        return "expired"
    if days <= 7:
        return "7 days"
    if days <= 14:
        return "14 days"
    if days <= 30:
        return "30 days"
    return None


async def enroll_with_pytak(
    host: str,
    username: str,
    password: str,
    server_id: str,
    store: Optional[SecretStore] = None,
) -> dict[str, Any]:
    """Enroll via pytak.enroll_tak and store cert material."""
    store = store or SecretStore()
    try:
        import pytak
    except ImportError as exc:
        raise RuntimeError("pytak is required for enrollment") from exc

    enroll = getattr(pytak, "enroll_tak", None)
    if enroll is None:
        # Fallback: some pytak versions nest enrollment
        raise RuntimeError("pytak.enroll_tak not available in this PyTAK version")

    cert_path, passphrase = await enroll(host=host, username=username, password=password)
    cert_path = Path(cert_path)
    data = cert_path.read_bytes()
    dest = store.write_bytes(f"{server_id}/client.p12", data)
    if passphrase:
        store.write_text(f"{server_id}/p12_password", passphrase)

    # Try extract PEM
    try:
        key, cert, additional = pkcs12.load_key_and_certificates(
            data, passphrase.encode() if passphrase else None
        )
        if cert:
            pem = cert.public_bytes(Encoding.PEM)
            store.write_bytes(f"{server_id}/client.pem", pem)
            meta = parse_certificate_meta(pem)
        else:
            meta = {}
        if key:
            key_pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
            store.write_bytes(f"{server_id}/client.key", key_pem)
        if additional:
            chain = b"".join(c.public_bytes(Encoding.PEM) for c in additional)
            store.write_bytes(f"{server_id}/ca.pem", chain)
    except Exception as exc:  # noqa: BLE001
        log.warning("PKCS12 extract partial: %s", exc)
        meta = {}

    return {
        "pkcs12_path": str(dest),
        "passphrase_ref": f"{server_id}/p12_password" if passphrase else None,
        "meta": meta,
    }


def import_pem_pair(
    server_id: str,
    cert_pem: bytes,
    key_pem: bytes,
    ca_pem: Optional[bytes] = None,
    store: Optional[SecretStore] = None,
) -> dict[str, Any]:
    store = store or SecretStore()
    store.write_bytes(f"{server_id}/client.pem", cert_pem)
    store.write_bytes(f"{server_id}/client.key", key_pem)
    if ca_pem:
        store.write_bytes(f"{server_id}/ca.pem", ca_pem)
    meta = parse_certificate_meta(cert_pem)
    return {"meta": meta}


def import_pkcs12(
    server_id: str,
    p12_bytes: bytes,
    password: Optional[str] = None,
    store: Optional[SecretStore] = None,
) -> dict[str, Any]:
    store = store or SecretStore()
    store.write_bytes(f"{server_id}/client.p12", p12_bytes)
    if password:
        store.write_text(f"{server_id}/p12_password", password)
    key, cert, additional = pkcs12.load_key_and_certificates(
        p12_bytes, password.encode() if password else None
    )
    meta: dict[str, Any] = {}
    if cert:
        pem = cert.public_bytes(Encoding.PEM)
        store.write_bytes(f"{server_id}/client.pem", pem)
        meta = parse_certificate_meta(pem)
    if key:
        key_pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        store.write_bytes(f"{server_id}/client.key", key_pem)
    if additional:
        chain = b"".join(c.public_bytes(Encoding.PEM) for c in additional)
        store.write_bytes(f"{server_id}/ca.pem", chain)
    return {"meta": meta}
