"""Device timezone resolution and display formatting."""

from __future__ import annotations

from datetime import UTC, datetime

from radiotak.services import timezone as tzmod


def test_generic_os_zone_needs_selection(monkeypatch):
    monkeypatch.setattr(tzmod, "read_os_timezone", lambda: "UTC")
    monkeypatch.setattr(tzmod, "configured_timezone", lambda: None)
    assert tzmod.needs_timezone_selection()
    assert tzmod.display_timezone() == "UTC"
    assert not tzmod.is_local_zone("UTC")
    assert not tzmod.is_local_zone("Etc/UTC")


def test_os_local_zone_used_when_no_override(monkeypatch):
    monkeypatch.setattr(tzmod, "read_os_timezone", lambda: "America/Chicago")
    monkeypatch.setattr(tzmod, "configured_timezone", lambda: None)
    assert not tzmod.needs_timezone_selection()
    assert tzmod.display_timezone() == "America/Chicago"


def test_settings_override_when_os_is_utc(monkeypatch):
    monkeypatch.setattr(tzmod, "read_os_timezone", lambda: "UTC")
    monkeypatch.setattr(tzmod, "configured_timezone", lambda: "America/New_York")
    assert not tzmod.needs_timezone_selection()
    assert tzmod.display_timezone() == "America/New_York"


def test_settings_override_wins_over_os(monkeypatch):
    monkeypatch.setattr(tzmod, "read_os_timezone", lambda: "America/Chicago")
    monkeypatch.setattr(tzmod, "configured_timezone", lambda: "America/New_York")
    assert tzmod.display_timezone() == "America/New_York"


def test_format_display_uses_configured_zone(monkeypatch):
    monkeypatch.setattr(tzmod, "display_timezone", lambda: "America/New_York")
    dt = datetime(2026, 9, 6, 4, 5, 6, tzinfo=UTC)
    assert tzmod.format_display(dt) == "2026-09-06 00:05:06"
    assert tzmod.to_iso(dt) == "2026-09-06T04:05:06Z"


def test_format_display_accepts_iso_string(monkeypatch):
    monkeypatch.setattr(tzmod, "display_timezone", lambda: "America/Chicago")
    assert tzmod.format_display("2026-09-06T05:05:06Z") == "2026-09-06 00:05:06"


def test_windows_tz_name_normalizes():
    assert tzmod.normalize_zone("Eastern Standard Time") == "America/New_York"


def test_invalid_zone_rejected():
    assert tzmod.normalize_zone("Not/A_Zone") is None
    assert tzmod.normalize_zone("America/New_York; rm -rf") is None
    ok, msg = tzmod.apply_timezone("bogus")
    assert not ok
    assert "Invalid" in msg


def test_timezone_choices_include_preferred():
    choices = dict(tzmod.timezone_choices())
    assert "America/New_York" in choices
    assert "UTC" in choices


def test_settings_template_timezone_select():
    from pathlib import Path
    from types import SimpleNamespace

    from jinja2 import Environment, FileSystemLoader

    templates = Path(__file__).resolve().parents[2] / "radiotak" / "web" / "templates"
    env = Environment(loader=FileSystemLoader(str(templates)))
    env.filters["localtime"] = lambda v, seconds=True: str(v) if v else ""
    env.filters["iso_utc"] = lambda v: str(v) if v else ""
    html = env.get_template("settings.html").render(
        request=SimpleNamespace(query_params={}),
        cfg={"github_branch": "main", "forwarding": {}},
        tz={
            "display": "America/New_York",
            "os": "UTC",
            "needs_selection": True,
            "choices": [
                ("America/New_York", "America/New York"),
                ("UTC", "UTC"),
                ("America/Chicago", "America/Chicago"),
            ],
            "preferred": ["America/New_York", "UTC"],
            "now": "2026-09-06 00:00:00",
        },
        csrf_token="x",
        title="RadioTAK",
        message=None,
        help_json="{}",
        display_timezone="America/New_York",
    )
    assert 'name="display_timezone"' in html
    assert "America/New_York" in html
    assert "no local time zone" in html
    assert "RADIOTAK_TZ" in html


def test_setup_template_timezone_when_os_is_generic():
    from pathlib import Path
    from types import SimpleNamespace

    from jinja2 import Environment, FileSystemLoader

    templates = Path(__file__).resolve().parents[2] / "radiotak" / "web" / "templates"
    env = Environment(loader=FileSystemLoader(str(templates)))
    html = env.get_template("setup.html").render(
        request=SimpleNamespace(query_params={}),
        tz={
            "display": "UTC",
            "os": "UTC",
            "needs_selection": True,
            "choices": [("America/New_York", "America/New York"), ("UTC", "UTC")],
            "preferred": ["America/New_York", "UTC"],
        },
        error=None,
        title="RadioTAK",
        help_json="{}",
        hide_sidebar=True,
        display_timezone="UTC",
    )
    assert 'name="display_timezone"' in html
    assert "no local time zone" in html
