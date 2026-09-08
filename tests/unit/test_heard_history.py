"""Clear observed radios and encryption archive."""

from __future__ import annotations

import os
from datetime import UTC, datetime
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


def test_clear_heard_history_keeps_approved(db_env):
    from sqlalchemy import func, select

    from radiotak.db import EncryptedTrafficEvent, LocationObservation, RadioIdentity
    from radiotak.gateway.events import event_bus
    from radiotak.services.heard_history import clear_heard_history

    db_env.add(
        RadioIdentity(radio_id="OBS1", forward_to_tak=False, observation_count=3)
    )
    db_env.add(
        RadioIdentity(radio_id="OK1", forward_to_tak=True, callsign="Keep")
    )
    db_env.add(
        LocationObservation(
            radio_id="OBS1",
            latitude=36.1,
            longitude=-82.1,
            observed_at=datetime.now(UTC),
        )
    )
    db_env.add(
        EncryptedTrafficEvent(
            observed_at=datetime.now(UTC),
            source_radio_id="OBS1",
            encrypted=True,
        )
    )
    db_env.commit()
    event_bus.clear()
    event_bus.publish({"type": "encrypted", "radio_id": "OBS1"})

    counts = clear_heard_history(db_env)

    assert counts["observed"] == 1
    assert counts["encryption"] == 1
    assert counts["locations"] == 1
    assert counts["live_events"] == 1
    remaining = list(db_env.scalars(select(RadioIdentity)))
    assert [r.radio_id for r in remaining] == ["OK1"]
    assert db_env.scalar(select(func.count()).select_from(EncryptedTrafficEvent)) == 0
    assert db_env.scalar(select(func.count()).select_from(LocationObservation)) == 0
    assert list(event_bus.history) == []
