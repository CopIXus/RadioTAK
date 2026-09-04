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
    assert b"/static/img/logo.png" in r.content
    assert b'id="update-pill"' in r.content


def test_product_logo_static(client):
    r = client.get("/static/img/logo.png")
    assert r.status_code == 200
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_favicon_is_product_logo(client):
    r = client.get("/branding/favicon")
    assert r.status_code == 200
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_login_shows_product_branding(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert b"/static/img/logo.png" in r.content
    assert b"RadioTAK" in r.content


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


def test_banner_shows_when_text_configured(client):
    _login(client)
    from radiotak.services.settings_store import update_settings

    update_settings(
        {
            "customization": {
                "banner_text": "Carter County TN Radio TAK",
                "banner_enabled": False,
                "banner_opt_out": False,
            }
        }
    )
    r = client.get("/")
    assert r.status_code == 200
    assert b"custom-banner" in r.content
    assert b"Carter County TN Radio TAK" in r.content


def test_banner_hidden_when_opted_out(client):
    _login(client)
    from radiotak.services.settings_store import update_settings

    update_settings(
        {
            "customization": {
                "banner_text": "Hidden Banner",
                "banner_enabled": False,
                "banner_opt_out": True,
            }
        }
    )
    r = client.get("/")
    assert r.status_code == 200
    assert b"Hidden Banner" not in r.content


def test_custom_title_goes_to_banner_not_sidebar(client):
    _login(client)
    from radiotak.services.settings_store import update_settings

    update_settings({"title": "Carter County", "customization": {"banner_opt_out": False}})
    r = client.get("/")
    assert r.status_code == 200
    html = r.text
    start = html.find('class="sidebar-logo"')
    end = html.find('class="nav-item"', start)
    sidebar = html[start:end]
    assert start != -1 and end != -1
    assert "RadioTAK" in sidebar
    assert "Carter County" not in sidebar
    assert "/static/img/logo.png" in sidebar
    assert 'id="update-pill"' in sidebar
    assert "custom-banner" in html
    assert "Carter County" in html


def test_status_includes_gauges(client):
    _login(client)
    r = client.get("/api/v1/status")
    assert r.status_code == 200
    body = r.json()
    assert "gauges" in body
    assert "stats" in body
    assert "spectrum" in body


def test_sdr_page_reports_decoder_build_and_feed_status(client):
    _login(client)
    page = client.get("/modules/sdr")
    assert page.status_code == 200
    assert b"Decoder build" in page.content
    assert b"sdr-feed-status" in page.content
    r = client.get("/modules/sdr/status.json")
    assert r.status_code == 200
    body = r.json()
    assert body["build"]["installed"] is False
    assert body["feed"]["spectrum"]["frames_received"] >= 0
    assert body["feed"]["geo"]["lines_received"] >= 0
    assert body["upgrade"]["running"] is False


def test_tak_enroll_page_has_password_reveal(client):
    import re

    _login(client)
    page = client.get("/tak")
    assert page.status_code == 200
    m = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert m
    r = client.post(
        "/tak/add",
        data={
            "csrf_token": m.group(1),
            "name": "TN TAK",
            "host": "takserver.example.net",
            "cot_port": 8089,
            "enrollment_port": 8446,
            "api_port": 8443,
            "callsign": "RadioTAK",
        },
        follow_redirects=False,
    )
    assert r.status_code in (303, 302)
    loc = r.headers.get("location") or ""
    assert loc.startswith("/tak/")
    detail = client.get(loc)
    assert detail.status_code == 200
    server_id = loc.split("/tak/", 1)[1].split("?", 1)[0]
    assert b'data-password-toggle' in detail.content
    assert b'id_enroll_password' in detail.content
    assert f'/tak/{server_id}/enroll'.encode() in detail.content
