"""API smoke tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("RADIOTAK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RADIOTAK_BIND_HTTPS", "false")
    import radiotak.db as dbmod
    from radiotak.config import reload_settings

    reload_settings()
    dbmod._engine = None
    dbmod._SessionLocal = None
    from radiotak.auth import save_auth
    from radiotak.db import init_db
    from radiotak.main import create_app

    init_db()
    save_auth("admin", "testpass123")
    app = create_app()
    with TestClient(app, base_url="http://test") as c:
        yield c


def _login(client: TestClient):
    r = client.get("/login")
    assert r.status_code == 200
    csrf = r.cookies.get("radiotak_login_csrf")
    assert csrf
    r = client.post(
        "/login",
        data={"username": "admin", "password": "testpass123", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert r.status_code in (303, 302)
    return r


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_login_csrf_rejected(client):
    client.get("/login")
    r = client.post(
        "/login",
        data={"username": "admin", "password": "testpass123", "csrf_token": "bad"},
        follow_redirects=False,
    )
    assert r.status_code == 401


def test_login_and_dashboard(client):
    _login(client)
    r = client.get("/")
    assert r.status_code == 200
    assert b"Console" in r.content


def test_help_and_customization_pages(client):
    _login(client)
    assert client.get("/help").status_code == 200
    assert client.get("/customization").status_code == 200


def test_branding_logo_404_without_upload(client):
    r = client.get("/branding/logo")
    assert r.status_code == 404


def test_logo_upload_and_public_fetch(client):
    _login(client)
    # get session csrf from a page
    page = client.get("/customization")
    assert page.status_code == 200
    # Extract csrf from cookie session is harder; post with form from settings cookie
    # Authenticated requests use session csrf in HTML — pull from body
    import re

    m = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert m
    csrf = m.group(1)
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    r = client.post(
        "/customization/logo",
        data={"csrf_token": csrf},
        files={"logo": ("logo.png", png, "image/png")},
        follow_redirects=False,
    )
    assert r.status_code in (303, 302)
    r = client.get("/branding/logo")
    assert r.status_code == 200


def test_status_includes_gauges(client):
    _login(client)
    r = client.get("/api/v1/status")
    assert r.status_code == 200
    body = r.json()
    assert "gauges" in body
    assert "stats" in body
    assert "spectrum" in body
