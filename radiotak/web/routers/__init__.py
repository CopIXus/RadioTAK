"""Pages and API routers."""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func, select

from radiotak.auth import (
    check_rate_limit,
    clear_failed_logins,
    create_session_token,
    load_auth,
    needs_setup,
    record_failed_login,
    save_auth,
    verify_password,
)
from radiotak.config import get_settings
from radiotak.db import (
    ForwardingStatus,
    LocationObservation,
    RadioIdentity,
    TakServer,
    get_session_factory,
    init_db,
)
from radiotak.gateway.events import event_bus
from radiotak.gateway.tak import ConnectionState, TakConnectionManager, tak_registry
from radiotak.gateway.tak.enrollment import enroll_with_pytak, import_pkcs12
from radiotak.gateway.tak.marti import list_groups
from radiotak.platform import get_platform
from radiotak.services import diagnostics as diagnostics_svc
from radiotak.services import modules as modules_svc
from radiotak.services import retention as retention_svc
from radiotak.services import tailscale as tailscale_svc
from radiotak.services import updater as updater_svc
from radiotak.services.settings_store import load_settings_file, update_settings
from radiotak.web.deps import TEMPLATES, base_context, redirect, require_auth, verify_csrf

pages = APIRouter()
api = APIRouter(prefix="/api/v1")


# ----- Auth / setup -----


@pages.get("/setup", response_class=HTMLResponse)
async def setup_get(request: Request):
    if not needs_setup():
        return redirect("/login")
    return TEMPLATES.TemplateResponse(request, "setup.html", base_context(request, hide_sidebar=True),
    )


@pages.post("/setup")
async def setup_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
):
    if not needs_setup():
        return redirect("/login")
    error = None
    if password != password2:
        error = "Passwords do not match"
    elif len(password) < 8:
        error = "Password must be at least 8 characters"
    if error:
        return TEMPLATES.TemplateResponse(request, "setup.html", base_context(request, hide_sidebar=True, error=error),
            status_code=400,
        )
    save_auth(username, password)
    token = create_session_token(username)
    resp = redirect("/")
    settings = get_settings()
    resp.set_cookie(
        settings.session_cookie,
        token,
        httponly=True,
        secure=settings.bind_https,
        samesite="lax",
        max_age=settings.session_max_age,
    )
    return resp


@pages.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    if needs_setup():
        return redirect("/setup")
    # ephemeral csrf for login form
    token = create_session_token("_login_")
    data = __import__("radiotak.auth", fromlist=["decode_session_token"]).decode_session_token(token)
    ctx = base_context(request, hide_sidebar=True, csrf_token=(data or {}).get("csrf", ""))
    # stash login csrf in unsigned cookie companion via session token cookie temporarily
    resp = TEMPLATES.TemplateResponse(request, "login.html", ctx)
    settings = get_settings()
    resp.set_cookie("radiotak_login_csrf", (data or {}).get("csrf", ""), httponly=True, samesite="lax", max_age=600)
    return resp


@pages.post("/login")
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(""),
):
    if needs_setup():
        return redirect("/setup")
    ip = request.client.host if request.client else "unknown"
    settings = get_settings()
    if not check_rate_limit(ip):
        return TEMPLATES.TemplateResponse(request, "login.html", base_context(request, hide_sidebar=True, error="Too many attempts. Try again later."),
            status_code=429,
        )
    auth = load_auth()
    if not auth or auth.username != username or not verify_password(password, auth.password_hash):
        record_failed_login(ip)
        return TEMPLATES.TemplateResponse(request, "login.html", base_context(request, hide_sidebar=True, error="Invalid username or password"),
            status_code=401,
        )
    clear_failed_logins(ip)
    token = create_session_token(username)
    resp = redirect("/")
    resp.set_cookie(
        settings.session_cookie,
        token,
        httponly=True,
        secure=settings.bind_https,
        samesite="lax",
        max_age=settings.session_max_age,
    )
    resp.delete_cookie("radiotak_login_csrf")
    return resp


@pages.get("/logout")
async def logout():
    resp = redirect("/login")
    resp.delete_cookie(get_settings().session_cookie)
    return resp


# ----- Dashboard -----


@pages.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, _user=Depends(require_auth)):
    Session = get_session_factory()
    db = Session()
    try:
        observed = db.scalar(select(func.count()).select_from(RadioIdentity)) or 0
        approved = (
            db.scalar(
                select(func.count()).select_from(RadioIdentity).where(RadioIdentity.forward_to_tak.is_(True))
            )
            or 0
        )
        forwarded = (
            db.scalar(
                select(func.count())
                .select_from(LocationObservation)
                .where(LocationObservation.forwarding_status == ForwardingStatus.SENT.value)
            )
            or 0
        )
        blocked = (
            db.scalar(
                select(func.count())
                .select_from(LocationObservation)
                .where(LocationObservation.forwarding_status == ForwardingStatus.BLOCKED.value)
            )
            or 0
        )
        latest = list(
            db.scalars(
                select(RadioIdentity)
                .where(RadioIdentity.forward_to_tak.is_(True))
                .where(RadioIdentity.last_latitude.is_not(None))
                .order_by(RadioIdentity.last_observed_at.desc())
                .limit(50)
            )
        )
        servers = list(db.scalars(select(TakServer)))
    finally:
        db.close()

    latest_json = json.dumps(
        [
            {
                "radio_id": u.radio_id,
                "callsign": u.callsign,
                "lat": u.last_latitude,
                "lon": u.last_longitude,
            }
            for u in latest
        ]
    )
    connected = any(s.status == "connected" for s in servers)
    tak_status = "CONNECTED" if connected else ("CONFIGURED" if servers else "NOT CONFIGURED")
    sdr_on = modules_svc.is_installed("sdr_location_gateway")
    ctx = base_context(
        request,
        nav="dashboard",
        metrics=get_platform().system_info(),
        counts={"observed": observed, "approved": approved, "forwarded": forwarded, "blocked": blocked},
        latest_json=latest_json,
        sdr_summary="Install SDR Location Gateway from Marketplace" if not sdr_on else "Module installed",
        sdr_status="READY" if sdr_on else "NOT INSTALLED",
        sdr_status_class="status-running" if sdr_on else "status-idle",
        decoder_summary="Replay fixtures or connect SDRTrunk",
        decoder_status="IDLE",
        decoder_status_class="status-idle",
        tak_summary=f"{len(servers)} server(s)",
        tak_status=tak_status,
        tak_status_class="status-running" if connected else "status-idle",
    )
    return TEMPLATES.TemplateResponse(request, "dashboard.html", ctx)


# ----- Marketplace -----


@pages.get("/marketplace", response_class=HTMLResponse)
async def marketplace(request: Request, _user=Depends(require_auth)):
    return TEMPLATES.TemplateResponse(request, "marketplace.html", base_context(request, nav="marketplace", modules=modules_svc.list_modules()),
    )


@pages.post("/marketplace/{module_id}/install")
async def marketplace_install(
    module_id: str, request: Request, csrf_token: str = Form(""), _user=Depends(require_auth)
):
    verify_csrf(request, csrf_token)
    modules_svc.install_module(module_id)
    return redirect("/marketplace")


@pages.post("/marketplace/{module_id}/uninstall")
async def marketplace_uninstall(
    module_id: str, request: Request, csrf_token: str = Form(""), _user=Depends(require_auth)
):
    verify_csrf(request, csrf_token)
    modules_svc.uninstall_module(module_id)
    return redirect("/marketplace")


# ----- TAK -----


@pages.get("/tak", response_class=HTMLResponse)
async def tak_list(request: Request, _user=Depends(require_auth)):
    Session = get_session_factory()
    db = Session()
    try:
        servers = list(db.scalars(select(TakServer).order_by(TakServer.name)))
    finally:
        db.close()
    return TEMPLATES.TemplateResponse(request, "tak.html", base_context(request, nav="tak", servers=servers, message=request.query_params.get("msg"))
    )


@pages.post("/tak/add")
async def tak_add(
    request: Request,
    name: str = Form(...),
    host: str = Form(...),
    cot_port: int = Form(8089),
    enrollment_port: int = Form(8446),
    api_port: int = Form(8443),
    callsign: str = Form("RadioTAK"),
    csrf_token: str = Form(""),
    _user=Depends(require_auth),
):
    verify_csrf(request, csrf_token)
    Session = get_session_factory()
    db = Session()
    try:
        s = TakServer(
            name=name,
            host=host.strip(),
            cot_port=cot_port,
            enrollment_port=enrollment_port,
            api_port=api_port,
            callsign=callsign,
        )
        db.add(s)
        db.commit()
        db.refresh(s)
        sid = s.id
    finally:
        db.close()
    # Start dry-run manager until certs exist
    mgr = TakConnectionManager(server_id=sid, host=host.strip(), cot_port=cot_port, callsign=callsign, dry_run=True)
    tak_registry.upsert(mgr)
    return redirect(f"/tak/{sid}")


@pages.get("/tak/{server_id}", response_class=HTMLResponse)
async def tak_detail(server_id: str, request: Request, _user=Depends(require_auth)):
    Session = get_session_factory()
    db = Session()
    try:
        server = db.get(TakServer, server_id)
        if not server:
            return redirect("/tak")
    finally:
        db.close()
    groups = []
    settings = get_settings()
    cert = settings.secrets_dir / server_id / "client.pem"
    key = settings.secrets_dir / server_id / "client.key"
    if cert.exists() and key.exists():
        try:
            groups = await list_groups(
                server.host,
                api_port=server.api_port,
                cert=(str(cert), str(key)),
                verify=False,
            )
        except Exception:  # noqa: BLE001
            groups = []
    return TEMPLATES.TemplateResponse(request, "tak_detail.html", base_context(
            request,
            nav="tak",
            server=server,
            groups=groups,
            message=request.query_params.get("msg"),
            error=request.query_params.get("err"),
        ),
    )


@pages.post("/tak/{server_id}/enroll")
async def tak_enroll(
    server_id: str,
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    tls_verify: Optional[str] = Form(None),
    csrf_token: str = Form(""),
    _user=Depends(require_auth),
):
    verify_csrf(request, csrf_token)
    Session = get_session_factory()
    db = Session()
    try:
        server = db.get(TakServer, server_id)
        if not server:
            return redirect("/tak")
        try:
            result = await enroll_with_pytak(server.host, username, password, server_id)
            meta = result.get("meta") or {}
            server.username = username
            server.tls_verify = bool(tls_verify)
            server.pkcs12_path = result.get("pkcs12_path")
            server.client_cert_path = str(get_settings().secrets_dir / server_id / "client.pem")
            server.client_key_path = str(get_settings().secrets_dir / server_id / "client.key")
            server.certificate_subject = meta.get("subject")
            server.certificate_issuer = meta.get("issuer")
            server.certificate_not_before = meta.get("not_before")
            server.certificate_not_after = meta.get("not_after")
            server.certificate_fingerprint = meta.get("fingerprint")
            server.last_error = None
            db.commit()
            msg = "Enrollment successful"
            err = None
        except Exception as exc:  # noqa: BLE001
            server.last_error = str(exc)
            db.commit()
            msg = None
            err = str(exc)
    finally:
        db.close()
    q = f"msg={msg}" if msg else f"err={err}"
    return redirect(f"/tak/{server_id}?{q}")


@pages.post("/tak/{server_id}/import-p12")
async def tak_import_p12(
    server_id: str,
    request: Request,
    p12: UploadFile = File(...),
    password: str = Form(""),
    csrf_token: str = Form(""),
    _user=Depends(require_auth),
):
    verify_csrf(request, csrf_token)
    data = await p12.read()
    Session = get_session_factory()
    db = Session()
    try:
        server = db.get(TakServer, server_id)
        if not server:
            return redirect("/tak")
        try:
            result = import_pkcs12(server_id, data, password or None)
            meta = result.get("meta") or {}
            server.pkcs12_path = str(get_settings().secrets_dir / server_id / "client.p12")
            server.client_cert_path = str(get_settings().secrets_dir / server_id / "client.pem")
            server.client_key_path = str(get_settings().secrets_dir / server_id / "client.key")
            server.certificate_subject = meta.get("subject")
            server.certificate_issuer = meta.get("issuer")
            server.certificate_not_before = meta.get("not_before")
            server.certificate_not_after = meta.get("not_after")
            server.certificate_fingerprint = meta.get("fingerprint")
            db.commit()
            return redirect(f"/tak/{server_id}?msg=Certificate+imported")
        except Exception as exc:  # noqa: BLE001
            return redirect(f"/tak/{server_id}?err={exc}")
    finally:
        db.close()


@pages.post("/tak/{server_id}/channels")
async def tak_channels(
    server_id: str,
    request: Request,
    csrf_token: str = Form(""),
    groups_text: str = Form(""),
    _user=Depends(require_auth),
):
    verify_csrf(request, csrf_token)
    form = await request.form()
    selected = list(form.getlist("groups"))
    if not selected and groups_text.strip():
        selected = [g.strip() for g in groups_text.split(",") if g.strip()]
    Session = get_session_factory()
    db = Session()
    try:
        server = db.get(TakServer, server_id)
        if server:
            server.active_groups = selected
            db.commit()
    finally:
        db.close()
    return redirect(f"/tak/{server_id}?msg=Channels+saved")


@pages.post("/tak/{server_id}/test")
async def tak_test(server_id: str, request: Request, csrf_token: str = Form(""), _user=Depends(require_auth)):
    verify_csrf(request, csrf_token)
    from datetime import datetime, timezone

    from radiotak.gateway.cot import build_cot_xml

    Session = get_session_factory()
    db = Session()
    try:
        server = db.get(TakServer, server_id)
        if not server:
            return redirect("/tak")
        xml = build_cot_xml(
            radio_id="TEST",
            latitude=36.0,
            longitude=-82.0,
            observed_at=datetime.now(timezone.utc),
            callsign=server.callsign or "RadioTAK-TEST",
            system_id="TEST",
            remarks="RadioTAK connection test",
        )
        mgr = tak_registry.get(server_id)
        if not mgr:
            dry = not (server.client_cert_path and PathExists(server.client_cert_path))
            mgr = TakConnectionManager(
                server_id=server_id,
                host=server.host,
                cot_port=server.cot_port,
                callsign=server.callsign or "RadioTAK",
                cert_path=server.client_cert_path,
                key_path=server.client_key_path,
                ca_path=server.server_ca_path,
                tls_verify=server.tls_verify,
                dry_run=dry,
            )
            tak_registry.upsert(mgr)
            await mgr.start()
        mgr.enqueue(xml, "RADIOTAK-TEST-TEST")
        server.status = ConnectionState.CONNECTED.value if mgr.dry_run else server.status
        db.commit()
    finally:
        db.close()
    return redirect("/tak?msg=Test+CoT+queued")


def PathExists(p: Optional[str]) -> bool:
    from pathlib import Path

    return bool(p) and Path(p).exists()


# ----- Units -----


@pages.get("/units", response_class=HTMLResponse)
async def units_page(request: Request, _user=Depends(require_auth)):
    Session = get_session_factory()
    db = Session()
    try:
        all_units = list(db.scalars(select(RadioIdentity).order_by(RadioIdentity.radio_id)))
        approved = [u for u in all_units if u.forward_to_tak]
        observed = [u for u in all_units if not u.forward_to_tak]
    finally:
        db.close()
    return TEMPLATES.TemplateResponse(request, "units.html", base_context(
            request,
            nav="units",
            approved=approved,
            observed=observed,
            message=request.query_params.get("msg"),
        ),
    )


@pages.post("/units/add")
async def units_add(
    request: Request,
    radio_id: str = Form(...),
    system_id: str = Form(""),
    callsign: str = Form(""),
    agency: str = Form(""),
    forward_to_tak: Optional[str] = Form(None),
    csrf_token: str = Form(""),
    _user=Depends(require_auth),
):
    verify_csrf(request, csrf_token)
    Session = get_session_factory()
    db = Session()
    try:
        db.add(
            RadioIdentity(
                radio_id=radio_id.strip(),
                system_id=system_id.strip() or None,
                callsign=callsign.strip() or None,
                agency=agency.strip() or None,
                forward_to_tak=bool(forward_to_tak),
            )
        )
        db.commit()
    finally:
        db.close()
    return redirect("/units?msg=Unit+saved")


@pages.get("/units/{unit_id}", response_class=HTMLResponse)
async def unit_edit_get(unit_id: str, request: Request, _user=Depends(require_auth)):
    Session = get_session_factory()
    db = Session()
    try:
        unit = db.get(RadioIdentity, unit_id)
        if not unit:
            return redirect("/units")
    finally:
        db.close()
    return TEMPLATES.TemplateResponse(request, "unit_edit.html", base_context(request, nav="units", unit=unit))


@pages.post("/units/{unit_id}")
async def unit_edit_post(
    unit_id: str,
    request: Request,
    callsign: str = Form(""),
    display_name: str = Form(""),
    agency: str = Form(""),
    unit: str = Form(""),
    cot_type: str = Form("a-f-G-U-C"),
    stale_seconds: int = Form(120),
    remarks: str = Form(""),
    enabled: Optional[str] = Form(None),
    forward_to_tak: Optional[str] = Form(None),
    csrf_token: str = Form(""),
    _user=Depends(require_auth),
):
    verify_csrf(request, csrf_token)
    Session = get_session_factory()
    db = Session()
    try:
        row = db.get(RadioIdentity, unit_id)
        if row:
            row.callsign = callsign or None
            row.display_name = display_name or None
            row.agency = agency or None
            row.unit = unit or None
            row.cot_type = cot_type or "a-f-G-U-C"
            row.stale_seconds = stale_seconds
            row.remarks = remarks or None
            row.enabled = bool(enabled)
            row.forward_to_tak = bool(forward_to_tak)
            db.commit()
    finally:
        db.close()
    return redirect("/units?msg=Updated")


# ----- Events / Map -----


@pages.get("/events", response_class=HTMLResponse)
async def events_page(request: Request, _user=Depends(require_auth)):
    return TEMPLATES.TemplateResponse(request, "events.html", base_context(request, nav="events", history=list(event_bus.history)[-100:][::-1]),
    )


@pages.get("/map", response_class=HTMLResponse)
async def map_page(request: Request, _user=Depends(require_auth)):
    Session = get_session_factory()
    db = Session()
    try:
        rows = list(
            db.scalars(
                select(RadioIdentity)
                .where(RadioIdentity.last_latitude.is_not(None))
                .order_by(RadioIdentity.last_observed_at.desc())
                .limit(200)
            )
        )
    finally:
        db.close()
    points = [
        {
            "radio_id": r.radio_id,
            "callsign": r.callsign,
            "lat": r.last_latitude,
            "lon": r.last_longitude,
            "observed_at": r.last_observed_at.isoformat() if r.last_observed_at else None,
        }
        for r in rows
    ]
    return TEMPLATES.TemplateResponse(request, "map.html", base_context(request, nav="map", points_json=json.dumps(points)),
    )


# ----- System / Settings / Tailscale -----


@pages.get("/system", response_class=HTMLResponse)
async def system_page(request: Request, _user=Depends(require_auth)):
    latest = None
    try:
        rel = await updater_svc.latest_release()
        latest = rel.get("tag_name")
    except Exception:  # noqa: BLE001
        latest = None
    return TEMPLATES.TemplateResponse(request, "system.html", base_context(
            request,
            nav="system",
            info=get_platform().system_info(),
            version=updater_svc.current_version(),
            branch=load_settings_file().get("github_branch", "main"),
            latest=latest,
            message=request.query_params.get("msg"),
            error=request.query_params.get("err"),
        ),
    )


@pages.post("/system/update")
async def system_update(request: Request, csrf_token: str = Form(""), _user=Depends(require_auth)):
    verify_csrf(request, csrf_token)
    code, out = updater_svc.update_now()
    if code == 0:
        return redirect("/system?msg=" + __import__("urllib.parse").parse.quote(out[:1500]))
    return redirect("/system?err=" + __import__("urllib.parse").parse.quote(out[:1500]))


@pages.post("/system/restart")
async def system_restart(request: Request, csrf_token: str = Form(""), _user=Depends(require_auth)):
    verify_csrf(request, csrf_token)
    code, out = get_platform().service_action("radiotak", "restart")
    return redirect(f"/system?msg={out}")


@pages.get("/system/diagnostics")
async def system_diagnostics(_user=Depends(require_auth)):
    data = diagnostics_svc.build_diagnostics_zip()
    return Response(
        data,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=radiotak-diagnostics.zip"},
    )


@pages.post("/system/purge")
async def system_purge(request: Request, csrf_token: str = Form(""), _user=Depends(require_auth)):
    verify_csrf(request, csrf_token)
    counts = retention_svc.purge_old_records()
    return redirect(f"/system?msg=Purged+{counts}")


@pages.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, _user=Depends(require_auth)):
    return TEMPLATES.TemplateResponse(request, "settings.html", base_context(
            request,
            nav="settings",
            cfg=load_settings_file(),
            message=request.query_params.get("msg"),
        ),
    )


@pages.post("/settings")
async def settings_save(request: Request, _user=Depends(require_auth)):
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    updates = {
        "title": form.get("title") or "RadioTAK",
        "accent": form.get("accent") or "#06b6d4",
        "theme": form.get("theme") or "dark",
        "github_branch": form.get("github_branch") or "main",
        "log_retention_days": int(form.get("log_retention_days") or 14),
        "observation_retention_days": int(form.get("observation_retention_days") or 7),
        "max_log_mb": int(form.get("max_log_mb") or 200),
        "privacy_mode": bool(form.get("privacy_mode")),
        "forwarding": {
            "min_interval_seconds": int(form.get("min_interval_seconds") or 2),
            "stale_seconds": int(form.get("stale_seconds") or 120),
            "min_movement_meters": int(form.get("min_movement_meters") or 5),
            "stationary_heartbeat_seconds": int(form.get("stationary_heartbeat_seconds") or 45),
        },
    }
    update_settings(updates)
    new_password = form.get("new_password") or ""
    current = form.get("current_password") or ""
    if new_password:
        auth = load_auth()
        if not auth or not verify_password(current, auth.password_hash):
            return redirect("/settings?msg=Password+change+failed")
        save_auth(auth.username, new_password)
    return redirect("/settings?msg=Saved")


@pages.get("/tailscale", response_class=HTMLResponse)
async def tailscale_page(request: Request, _user=Depends(require_auth)):
    return TEMPLATES.TemplateResponse(request, "tailscale.html", base_context(
            request,
            nav="tailscale",
            status=tailscale_svc.status(),
            hostname=load_settings_file().get("tailscale_hostname", ""),
            message=request.query_params.get("msg"),
            error=request.query_params.get("err"),
        ),
    )


@pages.post("/tailscale/install")
async def tailscale_install(request: Request, csrf_token: str = Form(""), _user=Depends(require_auth)):
    verify_csrf(request, csrf_token)
    code, out = tailscale_svc.install()
    return redirect(f"/tailscale?msg={out}" if code == 0 else f"/tailscale?err={out}")


@pages.post("/tailscale/up")
async def tailscale_up(
    request: Request,
    auth_key: str = Form(...),
    hostname: str = Form(""),
    ssh: Optional[str] = Form(None),
    csrf_token: str = Form(""),
    _user=Depends(require_auth),
):
    verify_csrf(request, csrf_token)
    if hostname:
        update_settings({"tailscale_hostname": hostname})
    code, out = tailscale_svc.up(auth_key.strip(), hostname or None, ssh=bool(ssh))
    return redirect(f"/tailscale?msg={out}" if code == 0 else f"/tailscale?err={out}")


@pages.post("/tailscale/down")
async def tailscale_down(request: Request, csrf_token: str = Form(""), _user=Depends(require_auth)):
    verify_csrf(request, csrf_token)
    code, out = tailscale_svc.down()
    return redirect(f"/tailscale?msg={out}")


# ----- API -----


@api.get("/health")
async def health():
    return {"status": "ok", "version": updater_svc.current_version()}


@api.get("/status")
async def status(_user=Depends(require_auth)):
    return {
        "version": updater_svc.current_version(),
        "metrics": get_platform().system_info(),
        "modules": {k: {"installed": v.get("installed"), "status": v.get("status")} for k, v in modules_svc.list_modules().items()},
        "tak": [
            {
                "id": m.server_id,
                "state": m.state.value,
                "sent": m.metrics.cot_sent,
                "dropped": m.metrics.cot_dropped,
            }
            for m in tak_registry.all()
        ],
    }


@api.get("/locations/latest")
async def locations_latest(_user=Depends(require_auth)):
    Session = get_session_factory()
    db = Session()
    try:
        rows = list(
            db.scalars(
                select(RadioIdentity)
                .where(RadioIdentity.last_latitude.is_not(None))
                .order_by(RadioIdentity.last_observed_at.desc())
                .limit(200)
            )
        )
        return [
            {
                "radio_id": r.radio_id,
                "callsign": r.callsign,
                "lat": r.last_latitude,
                "lon": r.last_longitude,
                "forward": r.forward_to_tak,
            }
            for r in rows
        ]
    finally:
        db.close()


@api.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    # Cookie auth for websocket
    settings = get_settings()
    token = websocket.cookies.get(settings.session_cookie)
    from radiotak.auth import decode_session_token

    if not decode_session_token(token):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    q = event_bus.subscribe()
    try:
        while True:
            event = await q.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        event_bus.unsubscribe(q)
