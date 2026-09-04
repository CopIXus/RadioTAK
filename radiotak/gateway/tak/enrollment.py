"""TAK certificate enrollment helpers (Marti TLS + manual import)."""

from __future__ import annotations

import json
import logging
import secrets
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    pkcs12,
)

from radiotak.services.secrets import SecretStore

log = logging.getLogger("radiotak.enrollment")

_OID_MAP = {
    "CN": x509.NameOID.COMMON_NAME,
    "O": x509.NameOID.ORGANIZATION_NAME,
    "OU": x509.NameOID.ORGANIZATIONAL_UNIT_NAME,
    "C": x509.NameOID.COUNTRY_NAME,
    "ST": x509.NameOID.STATE_OR_PROVINCE_NAME,
    "L": x509.NameOID.LOCALITY_NAME,
}


def parse_certificate_meta(cert_pem: bytes | str) -> dict[str, Any]:
    if isinstance(cert_pem, str):
        cert_pem = cert_pem.encode()
    cert = x509.load_pem_x509_certificate(cert_pem)
    not_before = getattr(cert, "not_valid_before_utc", None) or cert.not_valid_before.replace(
        tzinfo=UTC
    )
    not_after = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after.replace(
        tzinfo=UTC
    )
    return {
        "subject": cert.subject.rfc4514_string(),
        "issuer": cert.issuer.rfc4514_string(),
        "serial": format(cert.serial_number, "x"),
        "not_before": not_before,
        "not_after": not_after,
        "fingerprint": cert.fingerprint(hashes.SHA256()).hex(),
    }


def certificate_expiry_warning(not_after: datetime) -> str | None:
    now = datetime.now(UTC)
    if not_after.tzinfo is None:
        not_after = not_after.replace(tzinfo=UTC)
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


def _xml_local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _host_for_url(host: str) -> str:
    raw = (host or "").strip()
    if "://" in raw:
        parsed = urlparse(raw)
        raw = parsed.hostname or raw
    if raw.startswith("[") and "]" in raw:
        return raw
    if raw.count(":") > 1:
        return f"[{raw}]"
    return raw


def parse_tls_config_xml(xml_content: str) -> dict[str, str]:
    """Parse TAK `/Marti/api/tls/config` into subject attribute names."""
    root = ET.fromstring(xml_content)
    config: dict[str, str] = {}
    for elem in root.iter():
        if _xml_local(elem.tag) in {"nameEntry", "entry"}:
            name = (elem.get("name") or "").strip()
            value = (elem.get("value") or "").strip()
            if name and value:
                config[name] = value
    return config


def fix_pem_certificate(raw: str) -> bytes:
    """Normalize headerless or poorly wrapped PEM into a loadable certificate."""
    content = (raw or "").replace("\\n", "\n").replace("\\r", "\r")
    content = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not content:
        raise ValueError("empty certificate payload")
    if not content.startswith("-----BEGIN"):
        data = "".join(content.split())
        lines = ["-----BEGIN CERTIFICATE-----"]
        lines.extend(data[i : i + 64] for i in range(0, len(data), 64))
        lines.append("-----END CERTIFICATE-----")
        content = "\n".join(lines) + "\n"
    return content.encode("utf-8")


def generate_key_and_csr(username: str, config: dict[str, str]) -> tuple[rsa.RSAPrivateKey, bytes]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    attrs: list[x509.NameAttribute] = [
        x509.NameAttribute(x509.NameOID.COMMON_NAME, username),
    ]
    for key, oid in _OID_MAP.items():
        if key == "CN":
            continue
        value = (config.get(key) or "").strip()
        if not value:
            continue
        if key == "C" and len(value) != 2:
            log.warning("Skipping invalid country code from TAK config: %r", value)
            continue
        attrs.append(x509.NameAttribute(oid, value))
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name(attrs))
        .sign(private_key, hashes.SHA256())
    )
    return private_key, csr.public_bytes(serialization.Encoding.PEM)


def parse_v2_json_certs(payload: dict[str, Any]) -> tuple[bytes, list[bytes]]:
    signed = payload.get("signedCert") or payload.get("signed_cert")
    if not signed:
        raise RuntimeError("TAK enrollment response missing signedCert")
    cert_pem = fix_pem_certificate(str(signed))
    ca_pems: list[bytes] = []
    idx = 0
    while f"ca{idx}" in payload:
        value = payload.get(f"ca{idx}")
        if value:
            ca_pems.append(fix_pem_certificate(str(value)))
        idx += 1
    extra = payload.get("caCert") or payload.get("ca_cert")
    if extra:
        ca_pems.append(fix_pem_certificate(str(extra)))
    return cert_pem, ca_pems


def parse_enrollment_xml_certs(xml_content: str | bytes) -> tuple[bytes, list[bytes]]:
    if isinstance(xml_content, bytes):
        xml_content = xml_content.decode("utf-8", errors="replace")
    root = ET.fromstring(xml_content)
    signed: str | None = None
    ca_values: list[str] = []
    for elem in root.iter():
        tag = _xml_local(elem.tag)
        text = (elem.text or "").strip()
        if not text:
            continue
        if tag == "signedCert":
            signed = text
        elif tag in {"caCert", "ca0", "ca1", "ca2"}:
            ca_values.append(text)
    if not signed:
        raise RuntimeError("TAK enrollment XML missing signedCert")
    return fix_pem_certificate(signed), [fix_pem_certificate(v) for v in ca_values]


def _decode_sign_response(response: httpx.Response) -> tuple[bytes, list[bytes]]:
    text = response.text
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            payload = response.json()
        except Exception:
            payload = json.loads(text)
        if isinstance(payload, dict):
            return parse_v2_json_certs(payload)
    if stripped.startswith("<"):
        return parse_enrollment_xml_certs(text)
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return parse_v2_json_certs(payload)
    except json.JSONDecodeError:
        pass
    raise RuntimeError("TAK enrollment returned an unrecognized certificate payload")


def _http_error(exc: httpx.HTTPStatusError) -> RuntimeError:
    status = exc.response.status_code
    if status in (401, 403):
        return RuntimeError("Enrollment failed: username or password rejected by TAK Server")
    snippet = (exc.response.text or "").strip().replace("\n", " ")[:180]
    extra = f": {snippet}" if snippet else ""
    return RuntimeError(f"Enrollment failed: HTTP {status} from TAK Server{extra}")


def _connect_error(exc: httpx.RequestError, base: str) -> RuntimeError:
    detail = str(exc)
    lowered = detail.lower()
    if any(token in lowered for token in ("certificate", "ssl", "tls", "verify")):
        return RuntimeError(
            "TLS verification failed while contacting the enrollment port. "
            "Uncheck Verify TLS for self-signed TAK Server certificates, then try again."
        )
    return RuntimeError(
        f"Could not reach TAK enrollment at {base} ({exc}). "
        "Check host, enrollment port (usually 8446), and Verify TLS."
    )


def _store_enrolled_material(
    store: SecretStore,
    server_id: str,
    private_key: rsa.RSAPrivateKey,
    cert_pem: bytes,
    ca_pems: list[bytes],
    passphrase: str,
) -> dict[str, Any]:
    cert = x509.load_pem_x509_certificate(cert_pem)
    ca_certs = [x509.load_pem_x509_certificate(pem) for pem in ca_pems]
    key_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    p12_bytes = pkcs12.serialize_key_and_certificates(
        name=b"RadioTAK",
        key=private_key,
        cert=cert,
        cas=ca_certs or None,
        encryption_algorithm=serialization.BestAvailableEncryption(passphrase.encode("utf-8")),
    )
    dest = store.write_bytes(f"{server_id}/client.p12", p12_bytes)
    store.write_text(f"{server_id}/p12_password", passphrase)
    store.write_bytes(f"{server_id}/client.pem", cert.public_bytes(Encoding.PEM))
    store.write_bytes(f"{server_id}/client.key", key_pem)
    ca_path = None
    if ca_pems:
        ca_path = store.write_bytes(f"{server_id}/ca.pem", b"".join(ca_pems))
    return {
        "pkcs12_path": str(dest),
        "passphrase_ref": f"{server_id}/p12_password",
        "ca_path": str(ca_path) if ca_path else None,
        "cert_path": str(store.path_for(f"{server_id}/client.pem")),
        "key_path": str(store.path_for(f"{server_id}/client.key")),
        "meta": parse_certificate_meta(cert.public_bytes(Encoding.PEM)),
    }


async def enroll_client(
    host: str,
    username: str,
    password: str,
    server_id: str,
    store: SecretStore | None = None,
    enrollment_port: int = 8446,
    tls_verify: bool = False,
    client_uid: str = "RadioTAK",
    httpx_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Enroll a client certificate via TAK Server Marti TLS endpoints."""
    store = store or SecretStore()
    username = (username or "").strip()
    password = password or ""
    if not username or not password:
        raise RuntimeError("Enrollment username and password are required")

    base = f"https://{_host_for_url(host)}:{int(enrollment_port or 8446)}"
    auth = (username, password)
    verify: bool | str = bool(tls_verify)
    passphrase = secrets.token_urlsafe(18)
    client_uid = (client_uid or "RadioTAK").strip() or "RadioTAK"
    owns_client = httpx_client is None
    client = httpx_client or httpx.AsyncClient(verify=verify, timeout=45.0)
    try:
        try:
            config_resp = await client.get(f"{base}/Marti/api/tls/config", auth=auth)
            config_resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise _http_error(exc) from exc
        except httpx.RequestError as exc:
            raise _connect_error(exc, base) from exc

        try:
            config = parse_tls_config_xml(config_resp.text)
        except ET.ParseError:
            config = {}
        private_key, csr_pem = generate_key_and_csr(username, config)
        headers = {"Content-Type": "application/pkcs10"}
        params = {"clientUid": client_uid, "version": "4.10.0"}

        try:
            sign_resp = await client.post(
                f"{base}/Marti/api/tls/signClient/v2",
                params=params,
                content=csr_pem,
                headers=headers,
                auth=auth,
            )
            if sign_resp.status_code >= 400:
                log.info("signClient/v2 returned %s; trying v1", sign_resp.status_code)
                sign_resp = await client.post(
                    f"{base}/Marti/api/tls/signClient",
                    params=params,
                    content=csr_pem,
                    headers=headers,
                    auth=auth,
                )
            sign_resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise _http_error(exc) from exc
        except httpx.RequestError as exc:
            raise _connect_error(exc, base) from exc

        try:
            cert_pem, ca_pems = _decode_sign_response(sign_resp)
        except Exception as exc:  # noqa: BLE001
            # v1 may return a PKCS#12 blob instead of PEM/JSON.
            try:
                _key, cert, additional = pkcs12.load_key_and_certificates(
                    sign_resp.content, b"atakatak"
                )
            except Exception:
                raise RuntimeError(f"Could not parse TAK enrollment certificate: {exc}") from exc
            if cert is None:
                raise RuntimeError("TAK enrollment PKCS#12 contained no certificate") from exc
            cert_pem = cert.public_bytes(Encoding.PEM)
            ca_pems = [c.public_bytes(Encoding.PEM) for c in (additional or [])]

        return _store_enrolled_material(
            store, server_id, private_key, cert_pem, ca_pems, passphrase
        )
    finally:
        if owns_client:
            await client.aclose()


async def enroll_with_pytak(
    host: str,
    username: str,
    password: str,
    server_id: str,
    store: SecretStore | None = None,
    enrollment_port: int = 8446,
    tls_verify: bool = False,
    client_uid: str = "RadioTAK",
    httpx_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Enroll a TAK client certificate and store PEM / PKCS#12 material.

    RadioTAK talks to Marti TLS enrollment directly. PyTAK 7.0.x does not
    export ``enroll_tak``, so this no longer depends on that helper.
    """
    return await enroll_client(
        host,
        username,
        password,
        server_id,
        store=store,
        enrollment_port=enrollment_port,
        tls_verify=tls_verify,
        client_uid=client_uid,
        httpx_client=httpx_client,
    )


def import_pem_pair(
    server_id: str,
    cert_pem: bytes,
    key_pem: bytes,
    ca_pem: bytes | None = None,
    store: SecretStore | None = None,
) -> dict[str, Any]:
    store = store or SecretStore()
    store.write_bytes(f"{server_id}/client.pem", cert_pem)
    store.write_bytes(f"{server_id}/client.key", key_pem)
    ca_path = None
    if ca_pem:
        ca_path = store.write_bytes(f"{server_id}/ca.pem", ca_pem)
    meta = parse_certificate_meta(cert_pem)
    return {"meta": meta, "ca_path": str(ca_path) if ca_path else None}


def import_pkcs12(
    server_id: str,
    p12_bytes: bytes,
    password: str | None = None,
    store: SecretStore | None = None,
) -> dict[str, Any]:
    store = store or SecretStore()
    store.write_bytes(f"{server_id}/client.p12", p12_bytes)
    if password:
        store.write_text(f"{server_id}/p12_password", password)
    key, cert, additional = pkcs12.load_key_and_certificates(
        p12_bytes, password.encode() if password else None
    )
    meta: dict[str, Any] = {}
    ca_path = None
    if cert:
        pem = cert.public_bytes(Encoding.PEM)
        store.write_bytes(f"{server_id}/client.pem", pem)
        meta = parse_certificate_meta(pem)
    if key:
        key_pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        store.write_bytes(f"{server_id}/client.key", key_pem)
    if additional:
        chain = b"".join(c.public_bytes(Encoding.PEM) for c in additional)
        ca_path = store.write_bytes(f"{server_id}/ca.pem", chain)
    return {"meta": meta, "ca_path": str(ca_path) if ca_path else None}
