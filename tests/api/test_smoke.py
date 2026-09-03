"""API smoke tests."""

from __future__ import annotations

import os
from pathlib import Path

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


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_login_and_dashboard(client):
    r = client.get("/login")
    assert r.status_code == 200
    r = client.post(
        "/login",
        data={"username": "admin", "password": "testpass123", "csrf_token": ""},
        follow_redirects=False,
    )
    assert r.status_code in (303, 302)
    r = client.get("/")
    assert r.status_code == 200
    assert b"Console" in r.content
