"""Units page GPS filter markup."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "radiotak" / "web" / "templates"


def _unit(**kwargs):
    defaults = dict(
        id="1",
        radio_id="1015461",
        callsign=None,
        agency=None,
        system_id=None,
        observation_count=1,
        last_observed_at="2026-09-05",
        has_gps=False,
        last_encrypted=False,
        encryption_badge=None,
        last_talkgroup_id=None,
        hear_kind="heard",
        hear_label="Heard TG 15188 — no GPS",
        last_latitude=None,
        last_longitude=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_units_template_exposes_gps_filter():
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    env.filters["localtime"] = lambda v, seconds=True: str(v) if v else ""
    env.filters["iso_utc"] = lambda v: str(v) if v else ""
    html = env.get_template("units.html").render(
        approved=[],
        observed=[
            _unit(id="1", radio_id="1015461", has_gps=True, last_latitude=35.1, last_longitude=-85.5),
            _unit(id="2", radio_id="1015468", last_talkgroup_id="15188"),
        ],
        csrf_token="x",
        title="RadioTAK",
        message=None,
    )
    assert 'data-gps-filter="yes"' in html
    assert 'data-gps-filter="no"' in html
    assert "Has GPS" in html
    assert "No GPS" in html
    assert 'data-gps="yes"' in html
    assert 'data-gps="no"' in html
    assert "1015461" in html
    assert "1015468" in html
    assert "radiotak.units.gpsFilter" in html
