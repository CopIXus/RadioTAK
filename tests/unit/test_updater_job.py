"""Tests for update job state and git-permission repair helpers."""

from __future__ import annotations

import time

import pytest

from radiotak.services import updater


@pytest.fixture
def isolated_updater(tmp_path, monkeypatch):
    monkeypatch.setenv("RADIOTAK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RADIOTAK_INSTALL_DIR", str(tmp_path))
    from radiotak.config import reload_settings

    reload_settings()
    updater._job_thread = None
    (tmp_path / "VERSION").write_text("26.0904.1000\n", encoding="utf-8")
    yield updater
    updater._job_thread = None
    reload_settings()


def test_idle_update_state(isolated_updater):
    data = isolated_updater.load_update_state()
    assert data["state"] == "idle"
    payload = isolated_updater.update_status_payload()
    assert payload["update"]["state"] == "idle"
    assert payload["installed"] == "26.0904.1000"


def test_reconcile_restarting_marks_done(isolated_updater):
    isolated_updater.save_update_state(
        {
            "state": "restarting",
            "log": "restarting…\n",
            "from_version": "26.0904.1000",
        }
    )
    isolated_updater.reconcile_update_state_on_startup()
    data = isolated_updater.load_update_state()
    assert data["state"] == "done"
    assert data["to_version"] == "26.0904.1000"
    assert "Console is back" in data["log"]


def test_reconcile_running_marks_failed(isolated_updater):
    isolated_updater.save_update_state({"state": "running", "log": "mid-update\n"})
    isolated_updater.reconcile_update_state_on_startup()
    data = isolated_updater.load_update_state()
    assert data["state"] == "failed"
    assert "interrupted" in (data.get("error") or "").lower()


def test_start_update_job_streams_and_completes(isolated_updater, monkeypatch):
    def fake_update_now(branch=None, on_line=None):
        if on_line:
            on_line("Repairing repository permissions")
            on_line("$ git fetch")
            on_line("VERSION stamped: 26.0904.1030")
        return 0, "ok"

    monkeypatch.setattr(isolated_updater, "update_now", fake_update_now)
    started = isolated_updater.start_update_job()
    assert started.get("state") in ("running", "done")
    deadline = time.time() + 3
    data = isolated_updater.load_update_state()
    while data.get("state") in ("running", "restarting") and time.time() < deadline:
        time.sleep(0.05)
        data = isolated_updater.load_update_state()
    assert data["state"] == "done"
    assert "Repairing repository permissions" in data["log"]
    assert "VERSION stamped" in data["log"]


def test_start_update_job_rejects_second_worker(isolated_updater, monkeypatch):
    released = {"go": False}

    def slow_update_now(branch=None, on_line=None):
        if on_line:
            on_line("working")
        while not released["go"]:
            time.sleep(0.02)
        return 0, "ok"

    monkeypatch.setattr(isolated_updater, "update_now", slow_update_now)
    first = isolated_updater.start_update_job()
    second = isolated_updater.start_update_job()
    assert first.get("state") == "running"
    assert second.get("state") == "running"
    released["go"] = True
    deadline = time.time() + 3
    while isolated_updater.load_update_state().get("state") == "running" and time.time() < deadline:
        time.sleep(0.05)
    assert isolated_updater.load_update_state()["state"] == "done"
