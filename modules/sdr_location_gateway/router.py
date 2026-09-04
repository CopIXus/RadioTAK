"""SDR Location Gateway module routes."""

from __future__ import annotations

import time
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from radiotak.db import RadioIdentity, RadioSystem, SdrDevice, get_session_factory
from radiotak.gateway.events import event_bus
from radiotak.platform import get_platform
from radiotak.services import modules as modules_svc
from radiotak.services import traffic_keys as keys_svc
from radiotak.services.audit import write_audit
from radiotak.web.deps import TEMPLATES, base_context, redirect, require_auth, verify_csrf

from .sdrtrunk.build import build_label, sdrtrunk_build_info
from .sdrtrunk.playlist import (
    assign_listen_states,
    frequencies_to_text,
    is_listening,
    parse_frequencies,
    reapply_tuner_center_from_playlist,
    rebuild_default_playlist,
    set_row_listening,
)

router = APIRouter(prefix="/modules/sdr", tags=["sdr"])


def _tuner_count(live_devices=None) -> int:
    if live_devices is None:
        live_devices = get_platform().list_sdr_devices()
    return len(live_devices or [])


def _rebuild_playlist(db):
    rows = list(db.scalars(select(RadioSystem).order_by(RadioSystem.name)))
    devices = list(db.scalars(select(SdrDevice).order_by(SdrDevice.name)))
    return rebuild_default_playlist(rows, devices=devices, tuner_count=_tuner_count())


def _restart_decoder() -> tuple[int, str]:
    """Stop SDRTrunk, restamp tuner LO onto the listening CC, then start.

    systemd restart is not enough: on shutdown SDRTrunk writes
    tuner_configuration.json back to 101.1 MHz if no channel claimed the stick.
    """
    plat = get_platform()
    if plat.service_active("sdrtrunk"):
        plat.service_action("sdrtrunk", "stop")
    reapply_tuner_center_from_playlist()
    return plat.service_action("sdrtrunk", "start")


def _service_active() -> bool:
    return get_platform().service_active("sdrtrunk")


def _decoder_build() -> dict:
    info = sdrtrunk_build_info()
    info["label"] = build_label(info)
    info["upgrading"] = bool(modules_svc.decoder_upgrade_state().get("running"))
    return info


def _feed_status() -> dict:
    """Live counters for the :29501 spectrum and :29500 GPS feeds."""
    from .sdrtrunk.adapter import geo_stats
    from .sdrtrunk.spectrum import spectrum_hub

    now = time.time()
    spec_age = None
    if spectrum_hub.last_frame_at is not None:
        spec_age = round(now - spectrum_hub.last_frame_at, 1)
    geo = geo_stats()
    return {
        "spectrum": {
            "clients": spectrum_hub.clients,
            "frames_received": spectrum_hub.frames_received,
            "last_frame_age": spec_age,
            "live": spec_age is not None and spec_age < 5.0,
        },
        "geo": geo,
    }


def _page(request: Request, **extra):
    devices = get_platform().list_sdr_devices()
    Session = get_session_factory()
    db = Session()
    try:
        saved = list(db.scalars(select(SdrDevice).order_by(SdrDevice.name)))
        systems = list(db.scalars(select(RadioSystem).order_by(RadioSystem.name)))
        keys = keys_svc.list_keys(db)
        identities = list(db.scalars(select(RadioIdentity)))
        heard_keysets = keys_svc.collect_heard_keysets(
            identities=identities, events=list(event_bus.history)
        )
        for item in heard_keysets:
            if keys_svc.matching_key(db, item["algid"], item["key_id"]):
                item["key_loaded"] = True
    finally:
        db.close()
    form_alg = (request.query_params.get("alg") or "AES-256").strip().upper()
    if form_alg not in {k for k, _ in keys_svc.algorithm_choices()}:
        form_alg = "AES-256"
    form_kid = (request.query_params.get("kid") or "").strip()
    form_algid = (request.query_params.get("algid") or "").strip()
    form_label = ""
    if form_kid and request.query_params.get("alg"):
        form_label = f"{form_alg} KID {form_kid}"
    tuner_count = _tuner_count(devices)
    flags = [is_listening(s) for s in systems]
    states = assign_listen_states(flags, tuner_count)
    system_views = []
    cc_markers: list[int] = []
    listening_count = 0
    starved_count = 0
    for s, state in zip(systems, states, strict=True):
        cfg = s.config or {}
        freqs = cfg.get("frequencies_hz") or []
        listening = state != "off"
        if listening:
            listening_count += 1
        if state == "starved":
            starved_count += 1
        if state == "active":
            for hz in freqs:
                try:
                    cc_markers.append(int(hz))
                except (TypeError, ValueError):
                    continue
        system_views.append(
            {
                "id": s.id,
                "name": s.name,
                "enabled": s.enabled,
                "listening": listening,
                "listen_state": state,
                "protocol": s.protocol,
                "site": cfg.get("site") or "1",
                "auto_start": bool(cfg.get("auto_start", True)),
                "frequencies_text": frequencies_to_text(freqs),
                "freq_count": len(freqs),
            }
        )
    return TEMPLATES.TemplateResponse(
        request,
        "sdr_module.html",
        base_context(
            request,
            nav="sdr",
            devices=devices,
            saved=saved,
            systems=system_views,
            decoder_running=_service_active(),
            decoder_build=_decoder_build(),
            listening_count=listening_count,
            starved_count=starved_count,
            tuner_count=tuner_count,
            cc_markers_hz=cc_markers,
            traffic_keys=keys,
            key_algorithms=keys_svc.algorithm_choices(),
            heard_keysets=heard_keysets,
            form_alg=form_alg,
            form_kid=form_kid,
            form_algid=form_algid,
            form_label=form_label,
            **extra,
        ),
    )


@router.get("", response_class=HTMLResponse)
async def sdr_page(request: Request, _user=Depends(require_auth)):
    return _page(
        request,
        message=request.query_params.get("msg"),
        error=request.query_params.get("err"),
    )


@router.get("/status.json")
async def sdr_status_json(_user=Depends(require_auth)):
    """Polled by the SDR page: is the decoder build right, and are frames arriving?"""
    return {
        "decoder_running": _service_active(),
        "build": _decoder_build(),
        "feed": _feed_status(),
        "upgrade": modules_svc.decoder_upgrade_state(),
    }


@router.post("/upgrade")
async def sdr_upgrade(request: Request, csrf_token: str = Form(""), _user=Depends(require_auth)):
    """Re-run the module installer to pull the CopIXus SDRTrunk build with the exporters."""
    verify_csrf(request, csrf_token)
    if not modules_svc.is_installed(modules_svc.SDR_MODULE_ID):
        return redirect(
            "/modules/sdr?err=" + quote("Install the SDR Location Gateway from Marketplace first")
        )
    if modules_svc.upgrade_decoder_async(reason="manual"):
        return redirect(
            "/modules/sdr?msg="
            + quote(
                "Decoder upgrade started — downloading the CopIXus SDRTrunk build; this page refreshes when it lands"
            )
        )
    return redirect("/modules/sdr?msg=" + quote("Decoder upgrade already running"))


@router.post("/discover")
async def sdr_discover(request: Request, csrf_token: str = Form(""), _user=Depends(require_auth)):
    verify_csrf(request, csrf_token)
    devices = get_platform().list_sdr_devices()
    Session = get_session_factory()
    db = Session()
    added = 0
    try:
        existing = list(db.scalars(select(SdrDevice)))
        for d in devices:
            found = False
            for row in existing:
                if row.usb_path == d.get("usb_path") or (
                    d.get("serial_number") and row.serial_number == d.get("serial_number")
                ):
                    found = True
                    row.name = d.get("name") or row.name
                    row.driver = d.get("driver") or row.driver
                    break
            if not found:
                db.add(
                    SdrDevice(
                        name=d.get("name") or "SDR",
                        driver=d.get("driver") or "rtl",
                        serial_number=d.get("serial_number"),
                        usb_path=d.get("usb_path"),
                    )
                )
                added += 1
        db.commit()
    finally:
        db.close()
    return redirect(f"/modules/sdr?msg={quote(f'Discovery complete ({added} new)')}")


@router.post("/devices/{device_id}")
async def sdr_device_save(
    device_id: str,
    request: Request,
    name: str = Form(""),
    gain_mode: str = Form("auto"),
    gain: str = Form(""),
    ppm_correction: str = Form("0"),
    bias_tee: str | None = Form(None),
    enabled: str | None = Form(None),
    csrf_token: str = Form(""),
    _user=Depends(require_auth),
):
    verify_csrf(request, csrf_token)
    Session = get_session_factory()
    db = Session()
    try:
        row = db.get(SdrDevice, device_id)
        if row:
            row.name = name.strip() or row.name
            row.gain_mode = gain_mode.strip() or "auto"
            try:
                row.gain = float(gain) if gain.strip() else None
            except ValueError:
                row.gain = None
            try:
                row.ppm_correction = float(ppm_correction or 0)
            except ValueError:
                row.ppm_correction = 0.0
            row.bias_tee = bool(bias_tee)
            row.enabled = bool(enabled)
            db.commit()
            _rebuild_playlist(db)
    finally:
        db.close()
    return redirect("/modules/sdr?msg=Device+saved")


@router.post("/systems")
async def sdr_system_add(
    request: Request,
    name: str = Form(...),
    protocol: str = Form("P25"),
    site: str = Form("1"),
    frequencies: str = Form(...),
    auto_start: str | None = Form(None),
    apply_start: str | None = Form(None),
    csrf_token: str = Form(""),
    _user=Depends(require_auth),
):
    verify_csrf(request, csrf_token)
    try:
        freqs = parse_frequencies(frequencies)
    except ValueError as exc:
        return redirect(f"/modules/sdr?err={quote(str(exc))}")
    if not freqs:
        return redirect("/modules/sdr?err=" + quote("Enter at least one frequency in MHz"))
    Session = get_session_factory()
    db = Session()
    try:
        db.add(
            RadioSystem(
                name=name.strip(),
                protocol=protocol.strip() or "P25",
                enabled=True,
                config={
                    "site": (site or "1").strip(),
                    "frequencies_hz": freqs,
                    "auto_start": bool(auto_start),
                    "protocol": protocol.strip() or "P25",
                },
            )
        )
        db.commit()
        _rebuild_playlist(db)
    finally:
        db.close()
    if apply_start:
        _restart_decoder()
        return redirect(
            "/modules/sdr?msg=" + quote("System saved, playlist written, decoder restarted")
        )
    return redirect(
        "/modules/sdr?msg="
        + quote("System saved and playlist written. Start the decoder to listen.")
    )


@router.post("/systems/{system_id}")
async def sdr_system_update(
    system_id: str,
    request: Request,
    name: str = Form(...),
    protocol: str = Form("P25"),
    site: str = Form("1"),
    frequencies: str = Form(...),
    csrf_token: str = Form(""),
    _user=Depends(require_auth),
):
    verify_csrf(request, csrf_token)
    try:
        freqs = parse_frequencies(frequencies)
    except ValueError as exc:
        return redirect(f"/modules/sdr?err={quote(str(exc))}")
    Session = get_session_factory()
    db = Session()
    try:
        row = db.get(RadioSystem, system_id)
        if not row:
            return redirect("/modules/sdr?err=" + quote("System not found"))
        prev = dict(row.config or {})
        row.name = name.strip()
        row.protocol = protocol.strip() or "P25"
        row.config = {
            "site": (site or "1").strip(),
            "frequencies_hz": freqs,
            "auto_start": bool(prev.get("auto_start", True)),
            "protocol": protocol.strip() or "P25",
        }
        db.commit()
        _rebuild_playlist(db)
    finally:
        db.close()
    return redirect("/modules/sdr?msg=" + quote("System updated and playlist rewritten"))


@router.post("/systems/{system_id}/listen")
async def sdr_system_listen(
    system_id: str,
    request: Request,
    listen: str = Form("0"),
    csrf_token: str = Form(""),
    _user=Depends(require_auth),
):
    verify_csrf(request, csrf_token)
    on = listen.strip() in ("1", "true", "on", "yes")
    Session = get_session_factory()
    db = Session()
    name = "System"
    try:
        row = db.get(RadioSystem, system_id)
        if not row:
            return redirect("/modules/sdr?err=" + quote("System not found"))
        name = row.name
        set_row_listening(row, on)
        db.commit()
        _rebuild_playlist(db)
    finally:
        db.close()
    _restart_decoder()
    state = "listening" if on else "off"
    return redirect(
        "/modules/sdr?msg=" + quote(f"{name} {state} — playlist written, decoder restarted")
    )


@router.post("/systems/{system_id}/delete")
async def sdr_system_delete(
    system_id: str, request: Request, csrf_token: str = Form(""), _user=Depends(require_auth)
):
    verify_csrf(request, csrf_token)
    Session = get_session_factory()
    db = Session()
    try:
        row = db.get(RadioSystem, system_id)
        if row:
            db.delete(row)
            db.commit()
        _rebuild_playlist(db)
    finally:
        db.close()
    return redirect("/modules/sdr?msg=" + quote("System removed"))


@router.post("/keys")
async def sdr_key_add(
    request: Request,
    label: str = Form(""),
    protocol: str = Form("P25"),
    algorithm: str = Form("AES-256"),
    algorithm_id: str = Form(""),
    key_id: str = Form(...),
    key_hex: str = Form(...),
    csrf_token: str = Form(""),
    _user=Depends(require_auth),
):
    verify_csrf(request, csrf_token)
    actor = (getattr(request.state, "session", None) or {}).get("u") or "operator"
    Session = get_session_factory()
    db = Session()
    try:
        row = keys_svc.add_key(
            db,
            label=label,
            protocol=protocol,
            algorithm=algorithm,
            key_id=key_id,
            key_hex=key_hex,
            algorithm_id=algorithm_id or None,
        )
        _rebuild_playlist(db)
        write_audit(
            "traffic_key_add",
            actor=actor,
            target=row["id"],
            detail={"label": row["label"], "algorithm": row["algorithm"], "key_id": row["key_id"]},
        )
    except ValueError as exc:
        db.rollback()
        return redirect("/modules/sdr?err=" + quote(str(exc)))
    finally:
        db.close()
    if _service_active():
        _restart_decoder()
        return redirect(
            "/modules/sdr?msg="
            + quote(
                f"Stored {row['label']} (ALGID {row['algorithm_id_hex']} "
                f"KID {row['key_id']}) and restarted the decoder"
            )
        )
    return redirect(
        "/modules/sdr?msg="
        + quote(
            f"Stored {row['label']} (ALGID {row['algorithm_id_hex']} "
            f"KID {row['key_id']}). Start the decoder to load it."
        )
    )


@router.post("/keys/{key_id}/delete")
async def sdr_key_delete(
    key_id: str, request: Request, csrf_token: str = Form(""), _user=Depends(require_auth)
):
    verify_csrf(request, csrf_token)
    actor = (getattr(request.state, "session", None) or {}).get("u") or "operator"
    Session = get_session_factory()
    db = Session()
    deleted = False
    try:
        deleted = keys_svc.delete_key(db, key_id)
        if deleted:
            _rebuild_playlist(db)
            write_audit("traffic_key_delete", actor=actor, target=key_id)
    finally:
        db.close()
    if deleted and _service_active():
        _restart_decoder()
    return redirect("/modules/sdr?msg=" + quote("Key removed" if deleted else "Key not found"))


@router.post("/apply")
async def sdr_apply(
    request: Request,
    start: str | None = Form(None),
    csrf_token: str = Form(""),
    _user=Depends(require_auth),
):
    verify_csrf(request, csrf_token)
    Session = get_session_factory()
    db = Session()
    try:
        path = _rebuild_playlist(db)
    finally:
        db.close()
    if start:
        _restart_decoder()
        return redirect("/modules/sdr?msg=" + quote(f"Wrote {path.name} and restarted decoder"))
    return redirect("/modules/sdr?msg=" + quote(f"Wrote {path}"))


@router.post("/service/{action}")
async def sdr_service(
    action: str, request: Request, csrf_token: str = Form(""), _user=Depends(require_auth)
):
    verify_csrf(request, csrf_token)
    if action not in ("start", "stop", "restart"):
        return redirect("/modules/sdr?err=" + quote("bad action"))
    Session = get_session_factory()
    db = Session()
    try:
        if action in ("start", "restart"):
            _rebuild_playlist(db)
    finally:
        db.close()
    if action == "stop":
        code, out = get_platform().service_action("sdrtrunk", "stop")
    else:
        code, out = _restart_decoder()
    if code != 0:
        return redirect("/modules/sdr?err=" + quote(out or f"exit {code}"))
    return redirect(f"/modules/sdr?msg={quote(out or action)}")
