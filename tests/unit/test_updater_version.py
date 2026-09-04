"""Tests for date-stamped versioning helpers."""

from __future__ import annotations

import re

from radiotak.services import updater


def test_version_stamp_now_format():
    stamp = updater.version_stamp_now()
    assert re.match(r"^\d{2}\.\d{4}\.\d{4}$", stamp)


def test_version_stamp_from_git_matches_format():
    stamp = updater.version_stamp_from_git()
    assert stamp is not None
    assert re.match(r"^\d{2}\.\d{4}\.\d{4}$", stamp)


def test_current_version_prefers_stamp_file(tmp_path, monkeypatch):
    monkeypatch.setenv("RADIOTAK_INSTALL_DIR", str(tmp_path))
    from radiotak.config import reload_settings

    reload_settings()
    (tmp_path / "VERSION").write_text("26.0904.0836\n", encoding="utf-8")
    assert updater.current_version() == "26.0904.0836"


def test_legacy_semver_without_git_kept(tmp_path, monkeypatch):
    monkeypatch.setenv("RADIOTAK_INSTALL_DIR", str(tmp_path))
    from radiotak.config import reload_settings

    reload_settings()
    (tmp_path / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    assert updater.current_version() == "0.1.0"
