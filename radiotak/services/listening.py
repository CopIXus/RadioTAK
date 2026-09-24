"""Device listening sources: trunked SDR + APRS (RF / IS) and tuner exclusivity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from radiotak.db import RadioSystem, SdrDevice
from radiotak.platform import get_platform
from radiotak.services.modules import is_installed

SDR_UNIT = "sdrtrunk"
APRS_UNIT = "direwolf-aprs"


@dataclass
class ListeningSource:
    id: str
    kind: str  # trunked | aprs
    name: str
    protocol: str
    listening: bool
    listen_state: str  # off | active | starved | rf | is | is_only | stopped
    detail: str
    href: str
    manage_href: str


def sdr_installed() -> bool:
    return is_installed("sdr_location_gateway")


def aprs_installed() -> bool:
    return is_installed("aprs_rf_gateway")


def sdrtrunk_active() -> bool:
    return bool(sdr_installed() and get_platform().service_active(SDR_UNIT))


def direwolf_active() -> bool:
    return bool(aprs_installed() and get_platform().service_active(APRS_UNIT))


def tuner_count(db: Session | None = None) -> int:
    if db is not None:
        n = len(list(db.scalars(select(SdrDevice).where(SdrDevice.enabled.is_(True)))))
        if n:
            return n
    try:
        return len(get_platform().list_sdr_devices() or [])
    except Exception:  # noqa: BLE001
        return 0


def any_trunked_listening(db: Session) -> bool:
    if not sdr_installed():
        return False
    from modules.sdr_location_gateway.sdrtrunk.playlist import is_listening

    rows = list(db.scalars(select(RadioSystem)))
    return any(is_listening(r) for r in rows)


def aprs_status() -> dict[str, Any]:
    """APRS listening snapshot (settings + services)."""
    if not aprs_installed():
        return {
            "installed": False,
            "enable_rf": False,
            "enable_is": False,
            "rf_running": False,
            "is_connected": False,
            "listening": False,
            "auto_approve": False,
        }
    from modules.aprs_rf_gateway import service as aprs_service
    from modules.aprs_rf_gateway.settings import load_settings

    cfg = load_settings()
    snap = aprs_service.stats_snapshot()
    enable_rf = bool(cfg.get("enable_rf"))
    enable_is = bool(cfg.get("enable_is"))
    rf_running = bool(direwolf_active() and enable_rf)
    is_up = bool(snap.get("is_connected")) and enable_is
    return {
        "installed": True,
        "enable_rf": enable_rf,
        "enable_is": enable_is,
        "rf_running": rf_running,
        "is_connected": is_up,
        "listening": rf_running or is_up,
        "auto_approve": bool(cfg.get("auto_approve_units")),
        "mycall": cfg.get("mycall"),
        "packets_per_min": snap.get("packets_per_min") or 0,
        "kiss_connected": bool(snap.get("kiss_connected")),
        "gateway_running": bool(snap.get("running")),
    }


def any_source_listening(db: Session) -> bool:
    if any_trunked_listening(db) and sdrtrunk_active():
        return True
    st = aprs_status()
    return bool(st.get("listening"))


def list_listening_sources(db: Session) -> list[ListeningSource]:
    """Hub view-model: trunked RadioSystem rows + APRS card when installed."""
    sources: list[ListeningSource] = []
    if sdr_installed():
        from modules.sdr_location_gateway.sdrtrunk.playlist import (
            assign_listen_states,
            is_listening,
        )

        rows = list(db.scalars(select(RadioSystem).order_by(RadioSystem.name)))
        flags = [is_listening(r) for r in rows]
        states = assign_listen_states(flags, tuner_count(db))
        decoder_on = sdrtrunk_active()
        for row, state in zip(rows, states, strict=True):
            cfg = row.config or {}
            freqs = cfg.get("frequencies_hz") or []
            listening = state != "off"
            if listening and not decoder_on:
                detail = "Listen on — start decoder"
            elif state == "starved":
                detail = "Listening but no free tuner"
            elif state == "active":
                detail = f"{len(freqs)} CC · decoder running" if decoder_on else f"{len(freqs)} CC"
            else:
                detail = f"{len(freqs)} control channel(s)" if freqs else "No frequencies"
            sources.append(
                ListeningSource(
                    id=f"sdr:{row.id}",
                    kind="trunked",
                    name=row.name,
                    protocol=row.protocol or "P25",
                    listening=listening,
                    listen_state=state if listening else "off",
                    detail=detail,
                    href=f"/systems/sdr/{row.id}",
                    manage_href="/modules/sdr",
                )
            )

    if aprs_installed():
        st = aprs_status()
        if st["rf_running"] and st["is_connected"]:
            listen_state = "rf"
            detail = f"RF + IS · {st['packets_per_min']}/min · {st.get('mycall') or ''}"
        elif st["rf_running"]:
            listen_state = "rf"
            detail = f"Direwolf RF · {st['packets_per_min']}/min · {st.get('mycall') or ''}"
        elif st["is_connected"]:
            listen_state = "is_only"
            detail = f"APRS-IS only · {st['packets_per_min']}/min · {st.get('mycall') or ''}"
        elif st["enable_rf"] or st["enable_is"]:
            listen_state = "stopped"
            detail = "Configured but not connected"
        else:
            listen_state = "off"
            detail = "Enable RF and/or APRS-IS in settings"
        sources.append(
            ListeningSource(
                id="aprs",
                kind="aprs",
                name="APRS",
                protocol="APRS",
                listening=bool(st["listening"]),
                listen_state=listen_state,
                detail=detail.strip(),
                href="/modules/aprs",
                manage_href="/modules/aprs",
            )
        )
    return sources


def exclusivity_conflict(*, want_aprs_rf: bool = False, want_sdrtrunk: bool = False) -> str | None:
    """Return a human conflict message if RF front-end would collide.

    APRS-IS never needs the tuner and can always run alongside SDRTrunk.
    With two or more SDR devices, Direwolf can use ``rtl_device`` for a free stick
    while SDRTrunk keeps the other — no stop required.
    """
    devices = tuner_count()
    if want_aprs_rf and sdrtrunk_active():
        if devices >= 2:
            return None
        return (
            "SDRTrunk is using the only tuner. Starting APRS RF will stop SDRTrunk. "
            "Confirm to continue, add a second RTL-SDR (set RTL device index), "
            "or use APRS-IS only (internet) which does not need the dongle."
        )
    if want_sdrtrunk and direwolf_active():
        if devices >= 2:
            return None
        return (
            "Direwolf APRS is using the only tuner. Starting the trunked decoder will stop Direwolf. "
            "Confirm to continue, or add a second RTL-SDR."
        )
    return None


def stop_sdrtrunk() -> tuple[int, str]:
    if not sdr_installed():
        return 0, "SDR not installed"
    return get_platform().service_action(SDR_UNIT, "stop")


def stop_direwolf() -> tuple[int, str]:
    if not aprs_installed():
        return 0, "APRS not installed"
    return get_platform().service_action(APRS_UNIT, "stop")


def start_sdrtrunk() -> tuple[int, str]:
    return get_platform().service_action(SDR_UNIT, "start")


def start_direwolf() -> tuple[int, str]:
    return get_platform().service_action(APRS_UNIT, "start")


def ensure_sdrtrunk_for_listen(*, confirm: bool) -> str | None:
    """Stop Direwolf if needed before SDRTrunk listen/start. Returns error or None."""
    conflict = exclusivity_conflict(want_sdrtrunk=True)
    if not conflict:
        return None
    if not confirm:
        return conflict
    stop_direwolf()
    return None


def ensure_aprs_rf(*, confirm: bool) -> str | None:
    """Stop SDRTrunk if needed before Direwolf RF. Returns error or None."""
    conflict = exclusivity_conflict(want_aprs_rf=True)
    if not conflict:
        return None
    if not confirm:
        return conflict
    stop_sdrtrunk()
    return None


def listening_summary(db: Session) -> dict[str, Any]:
    sources = list_listening_sources(db)
    active = [s for s in sources if s.listening]
    aprs = aprs_status()
    return {
        "sources": [
            {
                "id": s.id,
                "kind": s.kind,
                "name": s.name,
                "protocol": s.protocol,
                "listening": s.listening,
                "listen_state": s.listen_state,
                "detail": s.detail,
                "href": s.href,
                "manage_href": s.manage_href,
            }
            for s in sources
        ],
        "any_listening": bool(active),
        "trunked_listening": any(s.kind == "trunked" and s.listening for s in sources),
        "aprs_listening": bool(aprs.get("listening")),
        "sdr_installed": sdr_installed(),
        "aprs_installed": aprs_installed(),
        "sdrtrunk_active": sdrtrunk_active(),
        "direwolf_active": direwolf_active(),
        "tuner_count": tuner_count(db),
        "aprs": aprs,
    }
