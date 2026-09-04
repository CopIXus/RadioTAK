"""Unit tests for operational alert derivation."""

from __future__ import annotations

from radiotak.services.alerts import AlertStore, collect_alerts, metric_classes


def test_metric_classes_thresholds():
    classes = metric_classes({"cpu_percent": 50, "ram_percent": 85, "disk_percent": 96, "temp_c": 75})
    assert classes["cpu"] == "ok"
    assert classes["ram"] == "warn"
    assert classes["disk"] == "bad"
    assert classes["temp"] == "warn"


def test_collect_alerts_sdr_and_tak_missing():
    alerts = collect_alerts(
        metrics={"cpu_percent": 10, "ram_percent": 40, "disk_percent": 50, "temp_c": None},
        gauges={"last_event_age_s": None, "messages_per_min": 0},
        sdr_installed=False,
        decoder_running=False,
        has_radio_system=False,
        tak_servers=[],
        stats={"observed": 0, "approved": 0},
    )
    ids = {a["id"] for a in alerts}
    assert "sdr.not_installed" in ids
    assert "tak.not_configured" in ids


def test_alert_ack_suppresses_until_prune():
    store = AlertStore(ack_ttl_s=3600)
    assert store.acknowledge("sdr.not_installed")
    assert store.is_acked("sdr.not_installed")
    collect_alerts(
        metrics={"cpu_percent": 10, "ram_percent": 40, "disk_percent": 50},
        gauges={},
        sdr_installed=False,
        decoder_running=False,
        has_radio_system=False,
        tak_servers=[],
        stats={},
    )
    # Global store may already have ack from previous call in process — ensure filter works
    from radiotak.services import alerts as alerts_mod

    alerts_mod.alert_store.acknowledge("sdr.not_installed")
    filtered = collect_alerts(
        metrics={"cpu_percent": 10, "ram_percent": 40, "disk_percent": 50},
        gauges={},
        sdr_installed=False,
        decoder_running=False,
        has_radio_system=False,
        tak_servers=[],
        stats={},
        include_acked=False,
    )
    assert all(a["id"] != "sdr.not_installed" for a in filtered)


def test_decoder_stopped_when_system_configured():
    alerts = collect_alerts(
        metrics={"cpu_percent": 10, "ram_percent": 40, "disk_percent": 50},
        gauges={"last_event_age_s": None},
        sdr_installed=True,
        decoder_running=False,
        has_radio_system=True,
        tak_servers=[{"id": "1", "name": "Demo", "enabled": True, "status": "disconnected"}],
        stats={"observed": 3, "approved": 0},
    )
    ids = {a["id"] for a in alerts}
    assert "decoder.stopped" in ids
    assert "tak.disconnected" in ids
    assert "units.none_approved" in ids


def test_tak_connected_does_not_alert():
    alerts = collect_alerts(
        metrics={"cpu_percent": 10, "ram_percent": 40, "disk_percent": 50},
        gauges={"last_event_age_s": 2},
        sdr_installed=True,
        decoder_running=True,
        has_radio_system=True,
        tak_servers=[
            {
                "id": "1",
                "name": "TN TAK",
                "enabled": True,
                "status": "connected",
                "last_error": "Marti activebits 400 while connecting",
            }
        ],
        stats={"observed": 1, "approved": 1},
    )
    ids = {a["id"] for a in alerts}
    assert "tak.disconnected" not in ids
    assert not any(a["id"].startswith("tak.error.") for a in alerts)


def test_alert_timestamp_persists_while_condition_active():
    from radiotak.services import alerts as alerts_mod

    prev = alerts_mod.alert_store
    alerts_mod.alert_store = AlertStore()
    try:
        kwargs = dict(
            metrics={"cpu_percent": 10, "ram_percent": 40, "disk_percent": 50},
            gauges={},
            sdr_installed=False,
            decoder_running=False,
            has_radio_system=False,
            tak_servers=[],
            stats={},
        )
        first = collect_alerts(**kwargs)
        row = next(a for a in first if a["id"] == "tak.not_configured")
        assert row["created_at"] is not None
        assert row["created_at_iso"]
        assert row["created_at_display"]
        ts = row["created_at"]
        second = collect_alerts(**kwargs)
        again = next(a for a in second if a["id"] == "tak.not_configured")
        assert again["created_at"] == ts
    finally:
        alerts_mod.alert_store = prev
