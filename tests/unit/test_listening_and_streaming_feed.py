"""Listening helpers and streaming-feed TAK profile."""

from __future__ import annotations

import io
import os
import zipfile
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


def test_listening_summary_empty(db_env, monkeypatch):
    from radiotak.services import listening as lis

    monkeypatch.setattr(lis, "sdr_installed", lambda: False)
    monkeypatch.setattr(lis, "aprs_installed", lambda: False)
    snap = lis.listening_summary(db_env)
    assert snap["any_listening"] is False
    assert snap["sources"] == []


def test_exclusivity_conflict_messages(monkeypatch):
    from radiotak.services import listening as lis

    monkeypatch.setattr(lis, "sdrtrunk_active", lambda: True)
    monkeypatch.setattr(lis, "direwolf_active", lambda: False)
    assert lis.exclusivity_conflict(want_aprs_rf=True)
    assert lis.ensure_aprs_rf(confirm=False)
    monkeypatch.setattr(lis, "stop_sdrtrunk", lambda: (0, "ok"))
    assert lis.ensure_aprs_rf(confirm=True) is None


def test_streaming_feed_skips_groups_and_presence():
    from radiotak.gateway.tak import TakConnectionManager

    mgr = TakConnectionManager(
        server_id="x",
        host="example",
        cot_port=8099,
        dry_run=True,
        connection_profile="streaming_feed",
        send_presence=False,
        active_groups=["Radio_WRITE"],
    )
    assert mgr.is_streaming_feed is True


@pytest.mark.asyncio
async def test_streaming_feed_dry_run_no_presence():
    from radiotak.gateway.tak import ConnectionState, TakConnectionManager

    mgr = TakConnectionManager(
        server_id="sf",
        host="example",
        cot_port=8099,
        dry_run=True,
        connection_profile="streaming_feed",
        send_presence=False,
    )
    await mgr.start()
    # Give the pump one tick
    import asyncio

    await asyncio.sleep(0.15)
    assert mgr.state == ConnectionState.CONNECTED
    # Presence would bump cot_generated periodically; without it, only queue drains
    before = mgr.metrics.cot_generated
    await asyncio.sleep(0.2)
    assert mgr.metrics.cot_generated == before
    await mgr.stop()


def test_import_integration_cert_zip_encrypted_key(tmp_path, monkeypatch):
    """Portal keys are often PKCS#8 encrypted; import must unwrap for ssl."""
    import datetime as dt

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    from radiotak.config import get_settings, reload_settings
    from radiotak.gateway.tak.enrollment import import_integration_cert_zip
    from radiotak.gateway.tak import build_tak_ssl_context

    monkeypatch.setenv("RADIOTAK_DATA_DIR", str(tmp_path))
    reload_settings()

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "nodered-enc")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(dt.datetime.now(dt.UTC) - dt.timedelta(days=1))
        .not_valid_after(dt.datetime.now(dt.UTC) + dt.timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(b"atakatak"),
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("nodered-enc.pem", pem)
        zf.writestr("nodered-enc.key", key_pem)
    import_integration_cert_zip("srv-enc", buf.getvalue(), password="atakatak")
    secrets = get_settings().secrets_dir / "srv-enc"
    # Must load without a password after normalize
    build_tak_ssl_context(
        cert_path=str(secrets / "client.pem"),
        key_path=str(secrets / "client.key"),
        tls_verify=False,
    )


def test_import_integration_cert_zip_pem(tmp_path, monkeypatch):
    import datetime as dt

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    from radiotak.config import reload_settings
    from radiotak.gateway.tak.enrollment import import_integration_cert_zip

    monkeypatch.setenv("RADIOTAK_DATA_DIR", str(tmp_path))
    reload_settings()

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "nodered-test")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(dt.datetime.now(dt.UTC) - dt.timedelta(days=1))
        .not_valid_after(dt.datetime.now(dt.UTC) + dt.timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("nodered-test.pem", pem)
        zf.writestr("nodered-test.key", key_pem)
    result = import_integration_cert_zip("srv1", buf.getvalue())
    assert result["meta"]["subject"]
    secrets = Path(tmp_path) / "secrets" / "srv1"
    # SecretStore resolves under settings.secrets_dir
    from radiotak.config import get_settings

    secrets = get_settings().secrets_dir / "srv1"
    assert (secrets / "client.pem").exists()
    assert (secrets / "client.key").exists()


def test_pipeline_status_aprs_only(monkeypatch):
    from radiotak.web.routers import _pipeline_status

    listening = {
        "sources": [
            {
                "id": "aprs",
                "name": "APRS",
                "listening": True,
                "listen_state": "is_only",
            }
        ],
        "sdr_installed": False,
        "aprs_installed": True,
        "sdrtrunk_active": False,
        "direwolf_active": False,
        "aprs": {"is_connected": True},
    }
    steps = _pipeline_status(
        listening=listening,
        stats={"total_hears": 0, "approved": 0, "observed": 0},
        servers=[],
        connected=False,
    )
    assert steps[0]["key"] == "sources"
    assert steps[0]["state"] == "Listening"
    assert steps[1]["detail"] == "APRS-IS"
    assert steps[3]["key"] == "tak"
