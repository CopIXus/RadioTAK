"""TAK certificate enrollment helpers."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

os.environ.setdefault("RADIOTAK_DATA_DIR", str(Path(__file__).resolve().parents[2] / ".data-test"))


def _self_signed(cn: str):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, cn)])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=2))
        .sign(key, hashes.SHA256())
    )
    return key, cert


def _headerless_pem(cert: x509.Certificate) -> str:
    pem = cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")
    return "".join(line.strip() for line in pem.splitlines() if not line.startswith("-----"))


@pytest.fixture()
def secrets_env(tmp_path, monkeypatch):
    monkeypatch.setenv("RADIOTAK_DATA_DIR", str(tmp_path))
    import radiotak.db as dbmod
    from radiotak.config import reload_settings

    reload_settings()
    dbmod._engine = None
    dbmod._SessionLocal = None
    from radiotak.services.secrets import SecretStore

    return SecretStore()


def test_secret_store_keeps_server_subdirectory(secrets_env):
    path = secrets_env.write_text("abc-123/client.pem", "hello")
    assert path.parent.name == "abc-123"
    assert path.name == "client.pem"
    assert secrets_env.path_for("abc-123/client.pem") == path
    with pytest.raises(ValueError):
        secrets_env.path_for("../escape.pem")


def test_parse_tls_config_and_csr():
    from radiotak.gateway.tak.enrollment import generate_key_and_csr, parse_tls_config_xml

    xml = """
    <ns2:certificateConfig xmlns:ns2="http://bbn.com/marti/xml/config">
      <nameEntries>
        <nameEntry name="O" value="TAK"/>
        <nameEntry name="OU" value="TAK"/>
        <nameEntry name="C" value="US"/>
      </nameEntries>
    </ns2:certificateConfig>
    """
    config = parse_tls_config_xml(xml)
    assert config == {"O": "TAK", "OU": "TAK", "C": "US"}
    _key, csr_pem = generate_key_and_csr("gateway-user", config)
    csr = x509.load_pem_x509_csr(csr_pem)
    subject = csr.subject.rfc4514_string()
    assert "CN=gateway-user" in subject
    assert "O=TAK" in subject


def test_fix_and_parse_enrollment_payloads():
    from radiotak.gateway.tak.enrollment import (
        fix_pem_certificate,
        parse_enrollment_xml_certs,
        parse_v2_json_certs,
    )

    _key, cert = _self_signed("client")
    _cakey, ca = _self_signed("TAK-CA")
    signed = _headerless_pem(cert)
    ca_body = _headerless_pem(ca)
    loaded = x509.load_pem_x509_certificate(fix_pem_certificate(signed))
    assert loaded.subject.rfc4514_string() == cert.subject.rfc4514_string()

    cert_pem, ca_pems = parse_v2_json_certs({"signedCert": signed, "ca0": ca_body})
    assert x509.load_pem_x509_certificate(cert_pem)
    assert len(ca_pems) == 1

    xml = f"<enrollment><signedCert>{signed}</signedCert><caCert>{ca_body}</caCert></enrollment>"
    xml_cert, xml_cas = parse_enrollment_xml_certs(xml)
    assert x509.load_pem_x509_certificate(xml_cert)
    assert len(xml_cas) == 1


@pytest.mark.asyncio
async def test_enroll_client_stores_pem_and_p12(secrets_env):
    from radiotak.gateway.tak.enrollment import enroll_client

    ca_key, ca_cert = _self_signed("TAK-CA")
    config_xml = (
        "<certificateConfig><nameEntries>"
        '<nameEntry name="O" value="TAK"/>'
        "</nameEntries></certificateConfig>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/Marti/api/tls/config"):
            user = request.headers.get("authorization", "")
            assert user.lower().startswith("basic ")
            return httpx.Response(200, text=config_xml)
        if request.url.path.endswith("/Marti/api/tls/signClient/v2"):
            assert request.url.params.get("clientUid") == "RadioTAK-test"
            csr = x509.load_pem_x509_csr(request.content)
            now = datetime.now(UTC)
            signed = (
                x509.CertificateBuilder()
                .subject_name(csr.subject)
                .issuer_name(ca_cert.subject)
                .public_key(csr.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now)
                .not_valid_after(now + timedelta(days=2))
                .sign(ca_key, hashes.SHA256())
            )
            return httpx.Response(
                200,
                json={"signedCert": _headerless_pem(signed), "ca0": _headerless_pem(ca_cert)},
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await enroll_client(
            "tak.example.com",
            "gateway-user",
            "s3cret",
            "srv-1",
            store=secrets_env,
            enrollment_port=8446,
            tls_verify=False,
            client_uid="RadioTAK-test",
            httpx_client=client,
        )

    assert Path(result["cert_path"]).is_file()
    assert Path(result["key_path"]).is_file()
    assert Path(result["pkcs12_path"]).is_file()
    assert Path(result["ca_path"]).is_file()
    assert result["meta"]["subject"]


@pytest.mark.asyncio
async def test_enroll_client_rejects_bad_password(secrets_env):
    from radiotak.gateway.tak.enrollment import enroll_client

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Unauthorized")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(RuntimeError, match="username or password rejected"):
            await enroll_client(
                "tak.example.com",
                "bad-user",
                "wrong",
                "srv-1",
                store=secrets_env,
                httpx_client=client,
            )
