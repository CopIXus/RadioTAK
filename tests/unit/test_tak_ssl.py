"""TAK CoT TLS context: trust enrolled CA, skip hostname match."""

from __future__ import annotations

import ssl
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from radiotak.gateway.tak import build_tak_ssl_context


def _ca_pem(tmp_path: Path) -> Path:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "TAK-CA")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    path = tmp_path / "ca.pem"
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return path


def test_ssl_context_requires_ca_but_skips_hostname(tmp_path):
    ca = _ca_pem(tmp_path)
    ctx = build_tak_ssl_context(ca_path=str(ca), tls_verify=True)
    assert ctx.check_hostname is False
    assert ctx.verify_mode == ssl.CERT_REQUIRED


def test_ssl_context_without_ca_does_not_verify(tmp_path):
    ctx = build_tak_ssl_context(ca_path=None, tls_verify=True)
    assert ctx.check_hostname is False
    assert ctx.verify_mode == ssl.CERT_NONE
