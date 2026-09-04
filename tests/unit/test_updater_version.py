"""Tests for date-stamped versioning helpers."""

from __future__ import annotations

import re

from radiotak.services import updater


def test_version_stamp_now_format():
    stamp = updater.version_stamp_now()
    assert re.match(r"^\d{2}\.\d{4}\.\d{4}$", stamp)


def test_version_stamp_from_git_matches_format():
    from radiotak.config import reload_settings

    reload_settings()
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


def test_stamp_from_iso_normalizes_to_utc():
    assert updater.stamp_from_iso("2026-09-04T12:42:00Z") == "26.0904.1242"
    # 14:25 EDT is 18:25 UTC
    assert updater.stamp_from_iso("2026-09-04T14:25:00-04:00") == "26.0904.1825"
    assert updater.stamp_from_iso("not-a-date") is None


def test_version_is_newer_compares_stamp_parts():
    assert updater.version_is_newer("26.0904.1425", "26.0904.1242")
    assert not updater.version_is_newer("26.0904.1242", "26.0904.1425")
    assert not updater.version_is_newer("26.0904.1425", "26.0904.1425")
    assert not updater.version_is_newer("0.1.0", "0.1.1")


def test_update_not_offered_when_local_stamp_is_newer():
    # Installed 14:25 vs GitHub VERSION 12:42 — same day, local is ahead.
    assert not updater.compute_update_available(
        installed="26.0904.1425",
        latest="26.0904.1242",
        local_sha="aaa",
        remote_sha="bbb",
        remote_ahead_by=None,
    )


def test_update_not_offered_when_shas_match_even_if_stamps_differ():
    assert not updater.compute_update_available(
        installed="26.0904.1425",
        latest="26.0904.1242",
        local_sha="abc123",
        remote_sha="ABC123",
        remote_ahead_by=99,
    )


def test_update_offered_when_github_is_ahead():
    assert updater.compute_update_available(
        installed="26.0904.1242",
        latest="26.0904.1242",
        local_sha="aaa",
        remote_sha="bbb",
        remote_ahead_by=2,
    )


def test_update_offered_when_remote_stamp_is_newer_without_sha():
    assert updater.compute_update_available(
        installed="26.0904.1242",
        latest="26.0904.1500",
        local_sha=None,
        remote_sha=None,
        remote_ahead_by=None,
    )


def test_update_not_offered_when_github_is_not_ahead():
    assert not updater.compute_update_available(
        installed="26.0904.1425",
        latest="26.0904.1242",
        local_sha="aaa",
        remote_sha="bbb",
        remote_ahead_by=0,
    )
