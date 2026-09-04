"""SDRTrunk build detection — stock vs CopIXus fork (exporters present)."""

from __future__ import annotations

import zipfile
from types import SimpleNamespace

from modules.sdr_location_gateway.sdrtrunk import build


def _fake_app(tmp_path, jar_name: str, *, exporters: bool, marker: str | None = None):
    app = tmp_path / "sdrtrunk" / "app"
    lib = app / "lib"
    lib.mkdir(parents=True)
    with zipfile.ZipFile(lib / jar_name, "w") as z:
        z.writestr("io/github/dsheirer/gui/SDRTrunk.class", b"")
        if exporters:
            z.writestr("io/github/dsheirer/export/DftFrameExporter.class", b"")
    if marker:
        (app / ".radiotak-fork").write_text(marker + "\n", encoding="utf-8")
    return SimpleNamespace(data_dir=tmp_path)


def test_expected_tag_comes_from_install_script():
    tag = build.expected_fork_tag()
    assert tag and tag.startswith("v0.6.") and "radiotak" in tag


def test_not_installed(tmp_path):
    info = build.sdrtrunk_build_info(SimpleNamespace(data_dir=tmp_path))
    assert info["installed"] is False
    assert info["has_exporters"] is False
    assert build.build_label(info) == "SDRTrunk not installed"


def test_stock_build_needs_upgrade(tmp_path):
    settings = _fake_app(tmp_path, "sdr-trunk-0.6.1.jar", exporters=False)
    info = build.sdrtrunk_build_info(settings)
    assert info["installed"] is True
    assert info["version"] == "0.6.1"
    assert info["fork_tag"] is None
    assert info["has_exporters"] is False
    assert info["upgrade_available"] is True
    assert "stock" in build.build_label(info)


def test_fork_build_current(tmp_path):
    tag = build.expected_fork_tag()
    settings = _fake_app(tmp_path, f"sdr-trunk-{tag[1:]}.jar", exporters=True, marker=tag)
    info = build.sdrtrunk_build_info(settings)
    assert info["has_exporters"] is True
    assert info["fork_tag"] == tag
    assert info["upgrade_available"] is False
    assert "CopIXus exporters" in build.build_label(info)


def test_hand_installed_fork_without_marker_still_detected(tmp_path):
    settings = _fake_app(tmp_path, "sdr-trunk-0.6.2-radiotak.1.jar", exporters=True)
    info = build.sdrtrunk_build_info(settings)
    assert info["has_exporters"] is True
    # no marker → tag unknown → installer will re-stamp it, so an upgrade is offered
    assert info["upgrade_available"] is True


def test_older_fork_tag_offers_upgrade(tmp_path):
    settings = _fake_app(tmp_path, "sdr-trunk-0.6.2-radiotak.0.jar", exporters=True, marker="v0.6.2-radiotak.0")
    info = build.sdrtrunk_build_info(settings)
    assert info["has_exporters"] is True
    assert info["upgrade_available"] is True


def test_geo_stats_counters_shape():
    from modules.sdr_location_gateway.sdrtrunk.adapter import geo_stats

    s = geo_stats()
    assert set(s) == {
        "clients",
        "connections_total",
        "lines_received",
        "gps_received",
        "decode_received",
        "encrypted_received",
        "last_line_age",
    }
