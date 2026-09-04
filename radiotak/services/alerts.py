"""Operational alert derivation and acknowledgement.

Alerts are computed from live system state (metrics, modules, TAK, hearing gauges)
so the dashboard can answer "what needs attention?" without reading raw logs.
Repeating conditions collapse to a single keyed alert; acknowledgements suppress
until the condition clears or the ack TTL expires.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from radiotak.gateway.events import status_bus
from radiotak.platform import get_platform
from radiotak.services import modules as modules_svc
from radiotak.services.hearing import hearing_gauges

SEVERITY_RANK = {"info": 0, "warning": 1, "error": 2, "critical": 3}


@dataclass
class Alert:
    id: str
    severity: str
    source: str
    title: str
    detail: str
    action: str | None = None
    href: str | None = None
    created_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.created_at is not None:
            d["created_at_iso"] = datetime.fromtimestamp(self.created_at, tz=UTC).isoformat()
        else:
            d["created_at_iso"] = None
        return d


class AlertStore:
    """In-memory ack state keyed by alert id."""

    def __init__(self, ack_ttl_s: float = 3600.0) -> None:
        self.ack_ttl_s = ack_ttl_s
        self._acked: dict[str, float] = {}
        self._seen: dict[str, float] = {}

    def acknowledge(self, alert_id: str) -> bool:
        if not alert_id:
            return False
        self._acked[alert_id] = time.time()
        status_bus.publish(
            {
                "type": "alert_acked",
                "alert_id": alert_id,
                "ts": time.time(),
            }
        )
        return True

    def is_acked(self, alert_id: str) -> bool:
        ts = self._acked.get(alert_id)
        if ts is None:
            return False
        if time.time() - ts > self.ack_ttl_s:
            self._acked.pop(alert_id, None)
            return False
        return True

    def note_seen(self, alert: Alert) -> None:
        if alert.id not in self._seen:
            status_bus.publish(
                {
                    "type": "alert",
                    "severity": alert.severity,
                    "source": alert.source,
                    "title": alert.title,
                    "detail": alert.detail,
                    "href": alert.href,
                    "ts": time.time(),
                }
            )
        self._seen[alert.id] = time.time()

    def prune_seen(self, active_ids: set[str]) -> None:
        for key in list(self._seen):
            if key not in active_ids:
                self._seen.pop(key, None)
                self._acked.pop(key, None)


alert_store = AlertStore()


def _metric_class(percent: float | None, warn: float = 80.0, bad: float = 92.0) -> str:
    if percent is None:
        return ""
    if percent >= bad:
        return "bad"
    if percent >= warn:
        return "warn"
    return "ok"


def metric_classes(metrics: dict[str, Any] | None) -> dict[str, str]:
    m = metrics or {}
    return {
        "cpu": _metric_class(m.get("cpu_percent"), warn=85.0, bad=95.0),
        "ram": _metric_class(m.get("ram_percent"), warn=80.0, bad=92.0),
        "disk": _metric_class(m.get("disk_percent"), warn=85.0, bad=95.0),
        "temp": _metric_class(m.get("temp_c"), warn=70.0, bad=80.0)
        if m.get("temp_c") is not None
        else "",
    }


def collect_alerts(
    *,
    metrics: dict[str, Any] | None = None,
    gauges: dict[str, Any] | None = None,
    sdr_installed: bool | None = None,
    decoder_running: bool | None = None,
    has_radio_system: bool = False,
    tak_servers: list[dict[str, Any]] | None = None,
    stats: dict[str, Any] | None = None,
    spectrum: dict[str, Any] | None = None,
    include_acked: bool = False,
) -> list[dict[str, Any]]:
    """Build the current alert list from operational state."""
    metrics = metrics if metrics is not None else get_platform().system_info()
    gauges = gauges if gauges is not None else hearing_gauges.snapshot()
    if sdr_installed is None:
        sdr_installed = modules_svc.is_installed("sdr_location_gateway")
    if decoder_running is None:
        decoder_running = bool(sdr_installed and get_platform().service_active("sdrtrunk"))
    tak_servers = tak_servers or []
    stats = stats or {}
    spectrum = spectrum or {}

    now = time.time()
    alerts: list[Alert] = []

    disk = metrics.get("disk_percent")
    if isinstance(disk, int | float):
        if disk >= 95:
            alerts.append(
                Alert(
                    id="host.disk.critical",
                    severity="critical",
                    source="System",
                    title="Disk nearly full",
                    detail=f"Disk usage is {disk}% — logs and SQLite may fail soon.",
                    action="Purge old logs from System, or free disk space on the host.",
                    href="/system",
                    created_at=now,
                )
            )
        elif disk >= 85:
            alerts.append(
                Alert(
                    id="host.disk.warning",
                    severity="warning",
                    source="System",
                    title="Disk usage high",
                    detail=f"Disk usage is {disk}%.",
                    action="Review retention settings or download/purge diagnostics.",
                    href="/system",
                    created_at=now,
                )
            )

    ram = metrics.get("ram_percent")
    if isinstance(ram, int | float) and ram >= 90:
        alerts.append(
            Alert(
                id="host.ram.high",
                severity="warning" if ram < 95 else "error",
                source="System",
                title="Memory usage high",
                detail=f"RAM usage is {ram}%.",
                action="Check decoder load on the SDR page; restart RadioTAK if needed.",
                href="/system",
                created_at=now,
            )
        )

    cpu = metrics.get("cpu_percent")
    if isinstance(cpu, int | float) and cpu >= 95:
        alerts.append(
            Alert(
                id="host.cpu.high",
                severity="warning",
                source="System",
                title="CPU saturated",
                detail=f"CPU usage is {cpu}%.",
                action="Reduce concurrent decoder load or check for runaway processes.",
                href="/system",
                created_at=now,
            )
        )

    temp = metrics.get("temp_c")
    if isinstance(temp, int | float) and temp >= 80:
        alerts.append(
            Alert(
                id="host.temp.critical",
                severity="critical",
                source="System",
                title="Host overheating",
                detail=f"CPU temperature is {temp:.1f} °C.",
                action="Improve cooling; throttle or stop the decoder if temperature keeps rising.",
                href="/system",
                created_at=now,
            )
        )
    elif isinstance(temp, int | float) and temp >= 70:
        alerts.append(
            Alert(
                id="host.temp.warning",
                severity="warning",
                source="System",
                title="Host temperature elevated",
                detail=f"CPU temperature is {temp:.1f} °C.",
                href="/system",
                created_at=now,
            )
        )

    if not sdr_installed:
        alerts.append(
            Alert(
                id="sdr.not_installed",
                severity="warning",
                source="SDR",
                title="SDR module not installed",
                detail="Location decoding requires the SDR Location Gateway module.",
                action="Install SDR Location Gateway from Marketplace.",
                href="/marketplace",
                created_at=now,
            )
        )
    elif not has_radio_system:
        alerts.append(
            Alert(
                id="sdr.no_system",
                severity="warning",
                source="SDR",
                title="No radio system configured",
                detail="Add at least one control-channel / system frequency.",
                action="Open SDR and add a radio system.",
                href="/modules/sdr",
                created_at=now,
            )
        )
    elif not decoder_running:
        alerts.append(
            Alert(
                id="decoder.stopped",
                severity="error",
                source="Decoder",
                title="Decoder not running",
                detail="A radio system is configured but SDRTrunk is not active.",
                action="Start the decoder on the SDR page.",
                href="/modules/sdr",
                created_at=now,
            )
        )
    else:
        age = gauges.get("last_event_age_s")
        if age is None or (isinstance(age, int | float) and age > 300):
            alerts.append(
                Alert(
                    id="decoder.no_traffic",
                    severity="warning",
                    source="Decoder",
                    title="No decoded traffic recently",
                    detail="Decoder is running but no location/hear events arrived in the last 5 minutes.",
                    action="Confirm control channel lock and SDR gain on the SDR page.",
                    href="/modules/sdr",
                    created_at=now,
                )
            )
        last_frame = spectrum.get("last_frame_age")
        if last_frame is not None and isinstance(last_frame, int | float) and last_frame > 30:
            alerts.append(
                Alert(
                    id="spectrum.stale",
                    severity="info",
                    source="SDR",
                    title="Spectrum feed idle",
                    detail=f"Last waterfall frame was {last_frame:.0f}s ago.",
                    href="/modules/sdr",
                    created_at=now,
                )
            )

    if not tak_servers:
        alerts.append(
            Alert(
                id="tak.not_configured",
                severity="warning",
                source="TAK",
                title="No TAK server configured",
                detail="Positions will not reach TAK until a server is added and enrolled.",
                action="Add a TAK server and enroll a certificate.",
                href="/tak",
                created_at=now,
            )
        )
    else:
        any_connected = False
        any_enabled = False
        for s in tak_servers:
            name = s.get("name") or s.get("id") or "TAK"
            sid = s.get("id")
            status = (s.get("status") or s.get("state") or "").lower()
            enabled = s.get("enabled", True)
            if enabled:
                any_enabled = True
            if status == "connected":
                any_connected = True
            err = s.get("last_error")
            if err:
                alerts.append(
                    Alert(
                        id=f"tak.error.{sid or name}",
                        severity="error",
                        source="TAK",
                        title=f"{name} connection error",
                        detail=str(err)[:240],
                        action="Open the server page and re-test or re-enroll.",
                        href=f"/tak/{sid}" if sid else "/tak",
                        created_at=now,
                    )
                )
            cert_after = s.get("certificate_not_after")
            if cert_after:
                try:
                    if isinstance(cert_after, str):
                        exp = datetime.fromisoformat(cert_after.replace("Z", "+00:00"))
                    elif isinstance(cert_after, datetime):
                        exp = cert_after if cert_after.tzinfo else cert_after.replace(tzinfo=UTC)
                    else:
                        exp = None
                    if exp is not None:
                        days = (exp - datetime.now(UTC)).total_seconds() / 86400.0
                        if days < 0:
                            alerts.append(
                                Alert(
                                    id=f"tak.cert.expired.{sid or name}",
                                    severity="critical",
                                    source="TAK",
                                    title=f"{name} certificate expired",
                                    detail="Client certificate is past its not-after date.",
                                    action="Re-enroll or import a new certificate.",
                                    href=f"/tak/{sid}" if sid else "/tak",
                                    created_at=now,
                                )
                            )
                        elif days < 14:
                            alerts.append(
                                Alert(
                                    id=f"tak.cert.expiring.{sid or name}",
                                    severity="warning",
                                    source="TAK",
                                    title=f"{name} certificate expiring soon",
                                    detail=f"Certificate expires in {days:.0f} day(s).",
                                    action="Plan re-enrollment before expiry.",
                                    href=f"/tak/{sid}" if sid else "/tak",
                                    created_at=now,
                                )
                            )
                except (TypeError, ValueError):
                    pass
        if any_enabled and not any_connected:
            alerts.append(
                Alert(
                    id="tak.disconnected",
                    severity="error",
                    source="TAK",
                    title="TAK not connected",
                    detail="Configured TAK server(s) are not in a connected state.",
                    action="Test connectivity and verify certificates on TAK Servers.",
                    href="/tak",
                    created_at=now,
                )
            )

    approved = int(stats.get("approved") or 0)
    observed = int(stats.get("observed") or 0)
    if observed > 0 and approved == 0:
        alerts.append(
            Alert(
                id="units.none_approved",
                severity="info",
                source="Units",
                title="No radios approved for TAK",
                detail=f"{observed} radio(s) observed; none are allowlisted for forwarding.",
                action="Approve authorized units on the Units page.",
                href="/units",
                created_at=now,
            )
        )

    active_ids = {a.id for a in alerts}
    for a in alerts:
        alert_store.note_seen(a)
    alert_store.prune_seen(active_ids)

    out: list[dict[str, Any]] = []
    for a in alerts:
        acked = alert_store.is_acked(a.id)
        if acked and not include_acked:
            continue
        row = a.to_dict()
        row["acked"] = acked
        out.append(row)

    out.sort(key=lambda r: (-SEVERITY_RANK.get(r["severity"], 0), r["title"]))
    return out


def alert_summary(alerts: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"critical": 0, "error": 0, "warning": 0, "info": 0, "total": 0}
    for a in alerts:
        if a.get("acked"):
            continue
        sev = a.get("severity") or "info"
        if sev in counts:
            counts[sev] += 1
        counts["total"] += 1
    return counts


def recent_ops_events(limit: int = 12) -> list[dict[str, Any]]:
    """Operational feed: status_bus plus notable event_bus entries."""
    from radiotak.gateway.events import event_bus

    notable_types = {
        "queued",
        "blocked",
        "encrypted",
        "alert",
        "alert_acked",
        "connected",
        "disconnected",
        "error",
    }
    rows: list[dict[str, Any]] = []
    for e in list(status_bus.history)[::-1]:
        rows.append(e)
        if len(rows) >= limit:
            return rows
    for e in list(event_bus.history)[::-1]:
        et = e.get("type") or ""
        if et in notable_types or e.get("encrypted"):
            rows.append(e)
        if len(rows) >= limit:
            break
    return rows[:limit]
