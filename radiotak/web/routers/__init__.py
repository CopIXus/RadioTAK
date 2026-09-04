"""Pages and API routers."""

from __future__ import annotations

import json
import logging
import re
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, Response
from sqlalchemy import func, select

from radiotak.auth import (
    check_rate_limit,
    clear_failed_logins,
    create_session_token,
    decode_session_token,
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
    RadioSystem,
    TakServer,
    get_session_factory,
)
from radiotak.gateway.constants import DEFAULT_STALE_SECONDS, DETECTION_COT_TYPE
from radiotak.gateway.events import event_bus
from radiotak.gateway.identities import hear_status
from radiotak.gateway.marker_style import resolve_style
from radiotak.gateway.tak import ConnectionState, TakConnectionManager, tak_registry
from radiotak.gateway.tak.enrollment import enroll_with_pytak, import_pkcs12
from radiotak.gateway.tak.marti import list_groups, set_active_groups
from radiotak.platform import get_platform
from radiotak.services import diagnostics as diagnostics_svc
from radiotak.services import modules as modules_svc
from radiotak.services import retention as retention_svc
from radiotak.services import tailscale as tailscale_svc
from radiotak.services import tak_runtime
from radiotak.services import updater as updater_svc
from radiotak.services.audit import recent_audit, write_audit
from radiotak.services.branding import (
    favicon_path,
    logo_path,
    remove_logo,
    save_logo,
)
from radiotak.services.hearing import hearing_gauges
from radiotak.services.settings_store import load_settings_file, update_settings
from radiotak.web.deps import TEMPLATES, base_context, redirect, require_auth, verify_csrf

pages = APIRouter()
api = APIRouter(prefix="/api/v1")
log = logging.getLogger("radiotak.web")

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{3,8}$")


def PathExists(p: Optional[str]) -> bool:
    return bool(p) and Path(p).exists()


def _valid_hex_color(value: str) -> bool:
    return bool(_HEX_COLOR_RE.match((value or "").strip()))


def _actor(request: Request) -> str:
    session = getattr(request.state, "session", None) or {}
    return session.get("u") or ""


def _primary_tak_server(db) -> Optional[TakServer]:
    server = db.scalar(
        select(TakServer).where(TakServer.enabled.is_(True)).order_by(TakServer.name).limit(1)
    )
    if server:
        return server
    return db.scalar(select(TakServer).order_by(TakServer.name).limit(1))


def _tak_server_view(server: TakServer) -> SimpleNamespace:
    return SimpleNamespace(
        id=server.id,
        name=server.name,
        enabled=server.enabled,
        host=server.host,
        cot_port=server.cot_port,
        enrollment_port=server.enrollment_port,
        api_port=server.api_port,
        connection_mode=server.connection_mode,
        tls_verify=server.tls_verify,
        username=server.username,
        client_cert_path=server.client_cert_path,
        client_key_path=server.client_key_path,
        pkcs12_path=server.pkcs12_path,
        callsign=server.callsign,
        device_uid=server.device_uid,
        default_callsign=server.default_callsign,
        cot_type_default=server.cot_type_default,
        iconset_path=server.iconset_path,
        marker_color=server.marker_color,
        cot_how=server.cot_how,
        default_ce_feet=server.default_ce_feet,
        presence_lat=server.presence_lat,
        presence_lon=server.presence_lon,
        active_groups=server.active_groups,
        status=server.status,
        last_error=server.last_error,
        certificate_subject=server.certificate_subject,
        certificate_issuer=server.certificate_issuer,
        certificate_not_before=server.certificate_not_before,
        certificate_not_after=server.certificate_not_after,
        certificate_fingerprint=server.certificate_fingerprint,
    )


def _unit_view(unit: RadioIdentity) -> SimpleNamespace:
    status = hear_status(unit)
    return SimpleNamespace(
        id=unit.id,
        radio_id=unit.radio_id,
        system_id=unit.system_id,
        enabled=unit.enabled,
        forward_to_tak=unit.forward_to_tak,
        callsign=unit.callsign,
        display_name=unit.display_name,
        agency=unit.agency,
        unit=unit.unit,
        team=unit.team,
        role=unit.role,
        cot_type=unit.cot_type,
        stale_seconds=unit.stale_seconds,
        remarks=unit.remarks,
        last_latitude=unit.last_latitude,
        last_longitude=unit.last_longitude,
        last_observed_at=unit.last_observed_at,
        observation_count=unit.observation_count,
        **status,
    )


def _cc_markers_hz(db) -> list[int]:
    markers: set[int] = set()
    systems = list(db.scalars(select(RadioSystem).where(RadioSystem.enabled.is_(True))))
    for system in systems:
        cfg = system.config or {}
        for hz in cfg.get("frequencies_hz") or []:
            try:
                markers.add(int(hz))
            except (TypeError, ValueError):
                continue
    return sorted(markers)


def _dashboard_stats(db) -> dict[str, int]:
    observed = db.scalar(select(func.count()).select_from(RadioIdentity)) or 0
    approved = (
        db.scalar(
            select(func.count()).select_from(RadioIdentity).where(RadioIdentity.forward_to_tak.is_(True))
        )
        or 0
    )
    total_hears = db.scalar(select(func.coalesce(func.sum(RadioIdentity.observation_count), 0))) or 0
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
    dropped = (
        db.scalar(
            select(func.count())
            .select_from(LocationObservation)
            .where(LocationObservation.forwarding_status == ForwardingStatus.DROPPED.value)
        )
        or 0
    )
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    heard_1h = (
        db.scalar(
            select(func.count())
            .select_from(LocationObservation)
            .where(LocationObservation.received_at > since)
        )
        or 0
    )
    return {
        "observed": observed,
        "approved": approved,
        "total_hears": int(total_hears),
        "forwarded": forwarded,
        "blocked": blocked,
        "dropped": dropped,
        "heard_1h": heard_1h,
    }


def _location_points(
    db,
    primary_server: Optional[TakServer],
    *,
    approved_only: bool = False,
    limit: int = 200,
) -> list[dict[str, Any]]:
    q = select(RadioIdentity).where(RadioIdentity.last_latitude.is_not(None))
    if approved_only:
        q = q.where(RadioIdentity.forward_to_tak.is_(True))
    rows = list(db.scalars(q.order_by(RadioIdentity.last_observed_at.desc()).limit(limit)))
    points: list[dict[str, Any]] = []
    for unit in rows:
        style = resolve_style(server=primary_server, identity=unit, radio_id=unit.radio_id)
        points.append(
            {
                "radio_id": unit.radio_id,
                "callsign": style["callsign"],
                "lat": unit.last_latitude,
                "lon": unit.last_longitude,
                "marker_color": style["marker_color"],
                "icon": style["iconset_path"],
                "cot_type": style["cot_type"],
                "observed_at": unit.last_observed_at.isoformat() if unit.last_observed_at else None,
                "forward": unit.forward_to_tak,
            }
        )
    return points


def _build_checklist(
    *,
    has_tak_server: bool,
    has_enrolled_cert: bool,
    has_approved_unit: bool,
    sdr_installed: bool,
    has_radio_system: bool,
    decoder_running: bool,
) -> list[dict[str, Any]]:
    return [
        {"done": has_tak_server, "label": "Add a TAK server", "href": "/tak"},
        {"done": has_enrolled_cert, "label": "Enroll TAK certificate", "href": "/tak"},
        {"done": has_approved_unit, "label": "Approve at least one radio unit", "href": "/units"},
        {"done": sdr_installed, "label": "Install SDR Location Gateway", "href": "/marketplace"},
        {"done": has_radio_system, "label": "Configure a radio system", "href": "/modules/sdr"},
        {"done": decoder_running, "label": "Start the decoder", "href": "/modules/sdr"},
    ]


def _cert_paths(server_id: str, server: TakServer) -> tuple[Optional[str], Optional[str]]:
    settings = get_settings()
    cert = server.client_cert_path or str(settings.secrets_dir / server_id / "client.pem")
    key = server.client_key_path or str(settings.secrets_dir / server_id / "client.key")
    return cert, key


def _media_type_for_path(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".png":
        return "image/png"
    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if ext == ".svg":
        return "image/svg+xml"
    return "application/octet-stream"


# ----- Auth / setup -----


@pages.get("/setup", response_class=HTMLResponse)
async def setup_get(request: Request):
    if not needs_setup():
        return redirect("/login")
    return TEMPLATES.TemplateResponse(
        request,
        "setup.html",
        base_context(request, hide_sidebar=True),
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
        return TEMPLATES.TemplateResponse(
            request,
            "setup.html",
            base_context(request, hide_sidebar=True, error=error),
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
    token = create_session_token("_login_")
    data = decode_session_token(token)
    csrf = (data or {}).get("csrf", "")
    ctx = base_context(request, hide_sidebar=True, csrf_token=csrf)
    resp = TEMPLATES.TemplateResponse(request, "login.html", ctx)
    resp.set_cookie("radiotak_login_csrf", csrf, httponly=True, samesite="lax", max_age=600)
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
    cookie_csrf = request.cookies.get("radiotak_login_csrf", "")
    if not cookie_csrf or cookie_csrf != csrf_token:
        return TEMPLATES.TemplateResponse(
            request,
            "login.html",
            base_context(request, hide_sidebar=True, error="Invalid login token"),
            status_code=401,
        )
    ip = request.client.host if request.client else "unknown"
    settings = get_settings()
    if not check_rate_limit(ip):
        return TEMPLATES.TemplateResponse(
            request,
            "login.html",
            base_context(request, hide_sidebar=True, error="Too many attempts. Try again later."),
            status_code=429,
        )
    auth = load_auth()
    if not auth or auth.username != username or not verify_password(password, auth.password_hash):
        record_failed_login(ip)
        return TEMPLATES.TemplateResponse(
            request,
            "login.html",
            base_context(request, hide_sidebar=True, error="Invalid username or password"),
            status_code=401,
        )
    clear_failed_logins(ip)
    write_audit("login", actor=username)
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
        stats = _dashboard_stats(db)
        primary = _primary_tak_server(db)
        latest = _location_points(db, primary, approved_only=True, limit=50)
        servers = list(db.scalars(select(TakServer)))
        cc_markers = _cc_markers_hz(db)
        has_radio_system = bool(db.scalar(select(func.count()).select_from(RadioSystem)))
        has_enrolled_cert = any(PathExists(s.client_cert_path) for s in servers)
    finally:
        db.close()

    cfg = load_settings_file()
    novnc = cfg.get("novnc") or {}
    sdr_on = modules_svc.is_installed("sdr_location_gateway")
    decoder_on = bool(sdr_on and get_platform().service_active("sdrtrunk"))
    connected = any(s.status == "connected" for s in servers)
    tak_status = "CONNECTED" if connected else ("CONFIGURED" if servers else "NOT CONFIGURED")
    checklist = _build_checklist(
        has_tak_server=bool(servers),
        has_enrolled_cert=has_enrolled_cert,
        has_approved_unit=stats["approved"] > 0,
        sdr_installed=sdr_on,
        has_radio_system=has_radio_system,
        decoder_running=decoder_on,
    )
    ctx = base_context(
        request,
        nav="dashboard",
        metrics=get_platform().system_info(),
        stats=stats,
        counts=stats,
        gauges=hearing_gauges.snapshot(),
        checklist=checklist,
        latest_json=json.dumps(latest),
        cc_markers_hz=json.dumps(cc_markers),
        novnc_enabled=bool(novnc.get("enabled")),
        novnc_url=novnc.get("url") or "/novnc/",
        sdr_installed=sdr_on,
        sdr_summary="Open SDR to set frequencies and start the decoder"
        if sdr_on
        else "Install SDR Location Gateway from Marketplace",
        sdr_status="READY" if sdr_on else "NOT INSTALLED",
        sdr_status_class="status-running" if sdr_on else "status-idle",
        decoder_summary="Listening via SDRTrunk"
        if decoder_on
        else ("Configure frequencies on the SDR page" if sdr_on else "Install the SDR module first"),
        decoder_status="RUNNING" if decoder_on else "IDLE",
        decoder_status_class="status-running" if decoder_on else "status-idle",
        tak_summary=f"{len(servers)} server(s)",
        tak_status=tak_status,
        tak_status_class="status-running" if connected else "status-idle",
    )
    return TEMPLATES.TemplateResponse(request, "dashboard.html", ctx)


# ----- Branding / customization -----


@pages.get("/customization", response_class=HTMLResponse)
async def customization_get(request: Request, _user=Depends(require_auth)):
    cfg = load_settings_file()
    return TEMPLATES.TemplateResponse(
        request,
        "customization.html",
        base_context(
            request,
            nav="customization",
            cfg=cfg,
            message=request.query_params.get("msg"),
            error=request.query_params.get("err"),
        ),
    )


@pages.post("/customization")
async def customization_post(request: Request, _user=Depends(require_auth)):
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    accent = (form.get("accent") or "").strip()
    banner_color = (form.get("banner_color") or "").strip()
    if accent and not _valid_hex_color(accent):
        return redirect("/customization?err=" + quote("Invalid accent color"))
    if banner_color and not _valid_hex_color(banner_color):
        return redirect("/customization?err=" + quote("Invalid banner color"))
    banner_text = (form.get("banner_text") or "")[:120]
    banner_enabled = bool(form.get("banner_enabled"))
    title_val = (form.get("title") or "").strip()
    custom_title = bool(title_val and title_val.casefold() != "radiotak")
    updates: dict[str, Any] = {
        "customization": {
            "banner_enabled": banner_enabled,
            # Opt-out when the user unchecks while branding text would otherwise show.
            "banner_opt_out": (bool(banner_text.strip()) or custom_title) and not banner_enabled,
            "banner_text": banner_text,
            "banner_font": form.get("banner_font") or "JetBrains Mono",
            "banner_size": form.get("banner_size") or "medium",
            "banner_color": banner_color or "#f1f5f9",
        },
    }
    if form.get("title"):
        updates["title"] = form.get("title")
    if accent:
        updates["accent"] = accent
    if form.get("theme"):
        updates["theme"] = form.get("theme")
    update_settings(updates)
    write_audit("customization_save", actor=_actor(request))
    return redirect("/customization?msg=Saved")


@pages.post("/customization/logo")
async def customization_logo_upload(
    request: Request,
    logo: UploadFile = File(...),
    csrf_token: str = Form(""),
    _user=Depends(require_auth),
):
    verify_csrf(request, csrf_token)
    data = await logo.read()
    try:
        save_logo(data, logo.content_type or "")
    except ValueError as exc:
        return redirect("/customization?err=" + quote(str(exc)))
    write_audit("logo_upload", actor=_actor(request))
    return redirect("/customization?msg=Logo+uploaded")


async def _customization_logo_delete(request: Request, csrf_token: str = Form("")):
    verify_csrf(request, csrf_token)
    remove_logo()
    write_audit("logo_delete", actor=_actor(request))
    return redirect("/customization?msg=Logo+removed")


@pages.post("/customization/logo/delete")
async def customization_logo_delete(
    request: Request, csrf_token: str = Form(""), _user=Depends(require_auth)
):
    return await _customization_logo_delete(request, csrf_token)


@pages.post("/customization/logo/remove")
async def customization_logo_remove(
    request: Request, csrf_token: str = Form(""), _user=Depends(require_auth)
):
    return await _customization_logo_delete(request, csrf_token)


@pages.get("/branding/logo")
async def branding_logo():
    path = logo_path()
    if not path:
        return Response(status_code=404)
    return FileResponse(path, media_type=_media_type_for_path(path))


@pages.get("/branding/favicon")
async def branding_favicon():
    path = favicon_path()
    if not path:
        return Response(status_code=404)
    return FileResponse(path, media_type=_media_type_for_path(path))


# ----- Help -----


@pages.get("/help", response_class=HTMLResponse)
async def help_page(request: Request, _user=Depends(require_auth)):
    return TEMPLATES.TemplateResponse(request, "help.html", base_context(request, nav="help"))


# ----- Marketplace -----


@pages.get("/marketplace", response_class=HTMLResponse)
async def marketplace(request: Request, _user=Depends(require_auth)):
    return TEMPLATES.TemplateResponse(
        request,
        "marketplace.html",
        base_context(request, nav="marketplace", modules=modules_svc.list_modules()),
    )


@pages.post("/marketplace/{module_id}/install")
async def marketplace_install(
    module_id: str, request: Request, csrf_token: str = Form(""), _user=Depends(require_auth)
):
    verify_csrf(request, csrf_token)
    modules_svc.install_module(module_id)
    write_audit("module_install", actor=_actor(request), target=module_id)
    return redirect("/marketplace")


@pages.post("/marketplace/{module_id}/uninstall")
async def marketplace_uninstall(
    module_id: str, request: Request, csrf_token: str = Form(""), _user=Depends(require_auth)
):
    verify_csrf(request, csrf_token)
    modules_svc.uninstall_module(module_id)
    write_audit("module_uninstall", actor=_actor(request), target=module_id)
    return redirect("/marketplace")


# ----- TAK -----


@pages.get("/tak", response_class=HTMLResponse)
async def tak_list(request: Request, _user=Depends(require_auth)):
    Session = get_session_factory()
    db = Session()
    try:
        rows = list(db.scalars(select(TakServer).order_by(TakServer.name)))
        servers = []
        for s in rows:
            v = _tak_server_view(s)
            mgr = tak_registry.get(s.id)
            if mgr:
                v.status = mgr.state.value
                if mgr.state == ConnectionState.CONNECTED:
                    if v.last_error and "activebits" in v.last_error:
                        v.last_error = None
                elif mgr.last_error:
                    v.last_error = mgr.last_error
            servers.append(v)
    finally:
        db.close()
    return TEMPLATES.TemplateResponse(
        request,
        "tak.html",
        base_context(
            request,
            nav="tak",
            servers=servers,
            message=request.query_params.get("msg"),
            error=request.query_params.get("err"),
        ),
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
    mgr = TakConnectionManager(
        server_id=sid,
        host=host.strip(),
        cot_port=cot_port,
        callsign=callsign,
        dry_run=True,
    )
    tak_registry.upsert(mgr)
    await mgr.start()
    write_audit("tak_add", actor=_actor(request), target=sid)
    return redirect(f"/tak/{sid}")


@pages.get("/tak/{server_id}", response_class=HTMLResponse)
async def tak_detail(server_id: str, request: Request, _user=Depends(require_auth)):
    Session = get_session_factory()
    db = Session()
    try:
        row = db.get(TakServer, server_id)
        if not row:
            return redirect("/tak")
        server = _tak_server_view(row)
        cert, key = _cert_paths(server_id, row)
        groups: list[Any] = []
        if PathExists(cert) and PathExists(key):
            try:
                groups = await list_groups(
                    row.host,
                    api_port=row.api_port,
                    cert=(str(cert), str(key)),
                    verify=False,
                )
            except Exception:  # noqa: BLE001
                groups = []
    finally:
        db.close()
    return TEMPLATES.TemplateResponse(
        request,
        "tak_detail.html",
        base_context(
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
    msg = None
    err = None
    try:
        server = db.get(TakServer, server_id)
        if not server:
            return redirect("/tak")
        try:
            if not server.device_uid:
                server.device_uid = f"RadioTAK-{server_id[:8]}"
            result = await enroll_with_pytak(
                server.host,
                username,
                password,
                server_id,
                enrollment_port=server.enrollment_port or 8446,
                tls_verify=bool(tls_verify),
                client_uid=server.device_uid,
            )
            meta = result.get("meta") or {}
            server.username = username
            server.tls_verify = bool(tls_verify)
            server.pkcs12_path = result.get("pkcs12_path")
            server.pkcs12_password_ref = result.get("passphrase_ref")
            server.client_cert_path = result.get("cert_path") or str(
                get_settings().secrets_dir / server_id / "client.pem"
            )
            server.client_key_path = result.get("key_path") or str(
                get_settings().secrets_dir / server_id / "client.key"
            )
            if result.get("ca_path"):
                server.server_ca_path = result["ca_path"]
            server.certificate_subject = meta.get("subject")
            server.certificate_issuer = meta.get("issuer")
            server.certificate_not_before = meta.get("not_before")
            server.certificate_not_after = meta.get("not_after")
            server.certificate_fingerprint = meta.get("fingerprint")
            server.last_error = None
            db.commit()
            await tak_runtime.restart(server_id)
            write_audit("tak_enroll", actor=_actor(request), target=server_id)
            msg = "Enrollment successful"
        except Exception as exc:  # noqa: BLE001
            server.last_error = str(exc)
            db.commit()
            err = str(exc)
    finally:
        db.close()
    q = f"msg={quote(msg)}" if msg else f"err={quote(err or 'Enrollment failed')}"
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
            if result.get("ca_path"):
                server.server_ca_path = result["ca_path"]
            if password:
                server.pkcs12_password_ref = f"{server_id}/p12_password"
            server.certificate_subject = meta.get("subject")
            server.certificate_issuer = meta.get("issuer")
            server.certificate_not_before = meta.get("not_before")
            server.certificate_not_after = meta.get("not_after")
            server.certificate_fingerprint = meta.get("fingerprint")
            server.last_error = None
            db.commit()
            await tak_runtime.restart(server_id)
            write_audit("tak_import_p12", actor=_actor(request), target=server_id)
            return redirect(f"/tak/{server_id}?msg=Certificate+imported")
        except Exception as exc:  # noqa: BLE001
            server.last_error = str(exc)
            db.commit()
            return redirect(f"/tak/{server_id}?err={quote(str(exc))}")
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
        if not server:
            return redirect("/tak")
        server.active_groups = selected
        cert, key = _cert_paths(server_id, server)
        server.last_error = None
        mgr = tak_registry.get(server_id)
        connected = bool(mgr and mgr.state == ConnectionState.CONNECTED)
        if selected and PathExists(cert) and PathExists(key) and connected:
            try:
                await set_active_groups(
                    server.host,
                    selected,
                    api_port=server.api_port,
                    client_uid=server.device_uid or server.callsign or "RadioTAK",
                    cert=(str(cert), str(key)),
                    verify=False,
                )
            except Exception as exc:  # noqa: BLE001
                # Saved locally; Marti often 400s until the CoT stream is up.
                log.warning("Marti group push deferred: %s", exc)
        if mgr:
            mgr.active_groups = list(selected)
        db.commit()
    finally:
        db.close()
    return redirect(f"/tak/{server_id}?msg=Channels+saved")


@pages.post("/tak/{server_id}/marker")
async def tak_marker(
    server_id: str,
    request: Request,
    default_callsign: str = Form("Radio"),
    cot_type_default: str = Form(DETECTION_COT_TYPE),
    iconset_path: str = Form(""),
    marker_color: str = Form("#06b6d4"),
    cot_how: str = Form("m-g"),
    default_ce_feet: float = Form(2000),
    presence_lat: str = Form(""),
    presence_lon: str = Form(""),
    csrf_token: str = Form(""),
    _user=Depends(require_auth),
):
    verify_csrf(request, csrf_token)
    if not _valid_hex_color(marker_color):
        return redirect(f"/tak/{server_id}?err={quote('Invalid marker color')}")
    Session = get_session_factory()
    db = Session()
    try:
        server = db.get(TakServer, server_id)
        if not server:
            return redirect("/tak")
        server.default_callsign = default_callsign.strip() or "Radio"
        server.cot_type_default = cot_type_default.strip() or DETECTION_COT_TYPE
        server.iconset_path = iconset_path.strip() or None
        server.marker_color = marker_color.strip()
        server.cot_how = cot_how.strip() or "m-g"
        server.default_ce_feet = float(default_ce_feet)
        try:
            server.presence_lat = float(presence_lat) if presence_lat.strip() else None
            server.presence_lon = float(presence_lon) if presence_lon.strip() else None
        except ValueError:
            return redirect(f"/tak/{server_id}?err={quote('Invalid gateway latitude/longitude')}")
        db.commit()
        mgr = tak_registry.get(server_id)
        if mgr:
            mgr.presence_lat = float(server.presence_lat or 0.0)
            mgr.presence_lon = float(server.presence_lon or 0.0)
        write_audit("tak_marker", actor=_actor(request), target=server_id)
    finally:
        db.close()
    return redirect(f"/tak/{server_id}?msg=Marker+appearance+saved")


@pages.post("/tak/{server_id}/delete")
async def tak_delete(
    server_id: str, request: Request, csrf_token: str = Form(""), _user=Depends(require_auth)
):
    verify_csrf(request, csrf_token)
    Session = get_session_factory()
    db = Session()
    name = server_id
    try:
        server = db.get(TakServer, server_id)
        if not server:
            return redirect("/tak")
        name = server.name
        db.delete(server)
        db.commit()
    finally:
        db.close()
    mgr = tak_registry.get(server_id)
    if mgr:
        await mgr.stop()
    secrets_dir = get_settings().secrets_dir / server_id
    if secrets_dir.exists():
        shutil.rmtree(secrets_dir, ignore_errors=True)
    write_audit("tak_delete", actor=_actor(request), target=f"{server_id}:{name}")
    return redirect("/tak?msg=Server+deleted")


@pages.post("/tak/{server_id}/test")
async def tak_test(server_id: str, request: Request, csrf_token: str = Form(""), _user=Depends(require_auth)):
    verify_csrf(request, csrf_token)
    from radiotak.gateway.cot import build_cot_xml

    Session = get_session_factory()
    db = Session()
    try:
        server = db.get(TakServer, server_id)
        if not server:
            return redirect("/tak")
        style = resolve_style(server=server, radio_id="TEST")
        xml = build_cot_xml(
            radio_id="TEST",
            latitude=36.0,
            longitude=-82.0,
            observed_at=datetime.now(timezone.utc),
            callsign=style["callsign"] or "RadioTAK-TEST",
            system_id="TEST",
            remarks="RadioTAK connection test",
            cot_type=style["cot_type"],
            how=style["how"],
            iconset_path=style["iconset_path"] or None,
            marker_color=style["marker_color"],
            default_ce_m=style["default_ce_meters"],
        )
        mgr = tak_registry.get(server_id)
        if not mgr:
            dry = not PathExists(server.client_cert_path)
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


# ----- Units -----


@pages.get("/units", response_class=HTMLResponse)
async def units_page(request: Request, _user=Depends(require_auth)):
    Session = get_session_factory()
    db = Session()
    try:
        all_units = list(db.scalars(select(RadioIdentity).order_by(RadioIdentity.radio_id)))
        approved = [_unit_view(u) for u in all_units if u.forward_to_tak]
        observed = [_unit_view(u) for u in all_units if not u.forward_to_tak]
    finally:
        db.close()
    return TEMPLATES.TemplateResponse(
        request,
        "units.html",
        base_context(
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
        row = db.get(RadioIdentity, unit_id)
        if not row:
            return redirect("/units")
        unit = _unit_view(row)
    finally:
        db.close()
    fwd = load_settings_file().get("forwarding") or {}
    default_stale = int(fwd.get("stale_seconds") or DEFAULT_STALE_SECONDS)
    return TEMPLATES.TemplateResponse(
        request,
        "unit_edit.html",
        base_context(request, nav="units", unit=unit, default_stale=default_stale),
    )


@pages.post("/units/{unit_id}")
async def unit_edit_post(
    unit_id: str,
    request: Request,
    callsign: str = Form(""),
    display_name: str = Form(""),
    agency: str = Form(""),
    unit: str = Form(""),
    team: str = Form(""),
    role: str = Form(""),
    cot_type: str = Form(DETECTION_COT_TYPE),
    stale_seconds: int = Form(0),
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
            row.team = team.strip() or None
            row.role = role.strip() or None
            row.cot_type = cot_type or DETECTION_COT_TYPE
            row.stale_seconds = max(0, int(stale_seconds))
            row.remarks = remarks or None
            row.enabled = bool(enabled)
            row.forward_to_tak = bool(forward_to_tak)
            db.commit()
            write_audit("unit_edit", actor=_actor(request), target=unit_id)
    finally:
        db.close()
    return redirect("/units?msg=Updated")


@pages.post("/units/{unit_id}/approve")
async def unit_approve(
    unit_id: str, request: Request, csrf_token: str = Form(""), _user=Depends(require_auth)
):
    verify_csrf(request, csrf_token)
    Session = get_session_factory()
    db = Session()
    try:
        row = db.get(RadioIdentity, unit_id)
        if row:
            row.forward_to_tak = True
            db.commit()
            write_audit("unit_approve", actor=_actor(request), target=unit_id)
    finally:
        db.close()
    return redirect("/units?msg=Unit+approved")


@pages.post("/units/{unit_id}/delete")
async def unit_delete(
    unit_id: str, request: Request, csrf_token: str = Form(""), _user=Depends(require_auth)
):
    verify_csrf(request, csrf_token)
    Session = get_session_factory()
    db = Session()
    try:
        row = db.get(RadioIdentity, unit_id)
        if row:
            db.delete(row)
            db.commit()
            write_audit("unit_delete", actor=_actor(request), target=unit_id)
    finally:
        db.close()
    return redirect("/units?msg=Unit+deleted")


# ----- Events / Map -----


@pages.get("/events", response_class=HTMLResponse)
async def events_page(request: Request, _user=Depends(require_auth)):
    return TEMPLATES.TemplateResponse(
        request,
        "events.html",
        base_context(request, nav="events", history=list(event_bus.history)[-100:][::-1]),
    )


@pages.get("/map", response_class=HTMLResponse)
async def map_page(request: Request, _user=Depends(require_auth)):
    Session = get_session_factory()
    db = Session()
    try:
        primary = _primary_tak_server(db)
        points = _location_points(db, primary, limit=200)
    finally:
        db.close()
    return TEMPLATES.TemplateResponse(
        request,
        "map.html",
        base_context(request, nav="map", points_json=json.dumps(points)),
    )


# ----- System / Settings / Tailscale -----


@pages.get("/system", response_class=HTMLResponse)
async def system_page(request: Request, _user=Depends(require_auth)):
    update_info = await updater_svc.check_for_update()
    return TEMPLATES.TemplateResponse(
        request,
        "system.html",
        base_context(
            request,
            nav="system",
            info=get_platform().system_info(),
            version=update_info.get("installed") or updater_svc.current_version(),
            branch=load_settings_file().get("github_branch", "main"),
            latest=update_info.get("latest"),
            update_available=bool(update_info.get("update_available")),
            audit_rows=recent_audit(50),
            message=request.query_params.get("msg"),
            error=request.query_params.get("err"),
            updating=request.query_params.get("updating"),
        ),
    )


@pages.post("/system/update")
async def system_update(request: Request, csrf_token: str = Form(""), _user=Depends(require_auth)):
    verify_csrf(request, csrf_token)
    write_audit("system_update", actor=_actor(request), detail={"via": "form"})
    updater_svc.start_update_job()
    return redirect("/system?updating=1")


@pages.post("/system/restart")
async def system_restart(request: Request, csrf_token: str = Form(""), _user=Depends(require_auth)):
    verify_csrf(request, csrf_token)
    code, out = get_platform().service_action("radiotak", "restart")
    write_audit("system_restart", actor=_actor(request), detail={"code": code})
    return redirect(f"/system?msg={quote(out)}")


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
    write_audit("system_purge", actor=_actor(request), detail={"counts": counts})
    return redirect(f"/system?msg=Purged+{counts}")


@pages.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, _user=Depends(require_auth)):
    return TEMPLATES.TemplateResponse(
        request,
        "settings.html",
        base_context(
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
    updates: dict[str, Any] = {
        "github_branch": form.get("github_branch") or "main",
        "log_retention_days": int(form.get("log_retention_days") or 14),
        "observation_retention_days": int(form.get("observation_retention_days") or 7),
        "event_retention_days": int(form.get("event_retention_days") or 1),
        "audit_retention_days": int(form.get("audit_retention_days") or 30),
        "max_log_mb": int(form.get("max_log_mb") or 200),
        "privacy_mode": bool(form.get("privacy_mode")),
        "map_history_minutes": int(form.get("map_history_minutes") or 60),
        "forwarding": {
            "unknown_radios": form.get("unknown_radios") or "deny",
            "duplicate_suppression": bool(form.get("duplicate_suppression")),
            "min_interval_seconds": int(form.get("min_interval_seconds") or 2),
            "stale_seconds": int(form.get("stale_seconds") or DEFAULT_STALE_SECONDS),
            "min_movement_meters": int(form.get("min_movement_meters") or 5),
            "stationary_heartbeat_seconds": int(form.get("stationary_heartbeat_seconds") or 45),
            "default_ce_meters": int(form.get("default_ce_meters") or 20),
        },
    }
    title = form.get("title")
    accent = form.get("accent")
    theme = form.get("theme")
    if title:
        updates["title"] = title
    if accent:
        if not _valid_hex_color(accent):
            return redirect("/settings?err=" + quote("Invalid accent color"))
        updates["accent"] = accent
    if theme:
        updates["theme"] = theme
    update_settings(updates)
    new_password = form.get("new_password") or ""
    current = form.get("current_password") or ""
    if new_password:
        auth = load_auth()
        if not auth or not verify_password(current, auth.password_hash):
            return redirect("/settings?err=Password+change+failed")
        save_auth(auth.username, new_password)
        write_audit("password_change", actor=_actor(request))
    write_audit("settings_save", actor=_actor(request))
    return redirect("/settings?msg=Saved")


@pages.get("/tailscale", response_class=HTMLResponse)
async def tailscale_page(request: Request, _user=Depends(require_auth)):
    return TEMPLATES.TemplateResponse(
        request,
        "tailscale.html",
        base_context(
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
    write_audit("tailscale_install", actor=_actor(request), detail={"code": code})
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
    write_audit("tailscale_up", actor=_actor(request), detail={"code": code, "hostname": hostname})
    return redirect(f"/tailscale?msg={out}" if code == 0 else f"/tailscale?err={out}")


@pages.post("/tailscale/down")
async def tailscale_down(request: Request, csrf_token: str = Form(""), _user=Depends(require_auth)):
    verify_csrf(request, csrf_token)
    code, out = tailscale_svc.down()
    write_audit("tailscale_down", actor=_actor(request), detail={"code": code})
    return redirect(f"/tailscale?msg={out}")


# ----- API -----


@api.get("/health")
async def health():
    state = updater_svc.load_update_state()
    return {
        "status": "ok",
        "version": updater_svc.current_version(),
        "update": {"state": state.get("state") or "idle"},
    }


@api.get("/system/update")
async def api_update_status(_user=Depends(require_auth)):
    return updater_svc.update_status_payload()


@api.post("/system/update")
async def api_system_update(request: Request, _user=Depends(require_auth)):
    token = request.headers.get("X-CSRF-Token") or ""
    if not token:
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        token = (body or {}).get("csrf_token") or ""
    verify_csrf(request, token)
    write_audit("system_update", actor=_actor(request), detail={"via": "api"})
    state = updater_svc.start_update_job()
    payload = updater_svc.update_status_payload()["update"]
    return {"ok": True, "update": payload, "started": state.get("state")}


@pages.get("/update-sw.js")
async def update_service_worker():
    path = Path(__file__).resolve().parent.parent / "static" / "js" / "update-sw.js"
    return FileResponse(
        str(path),
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


@api.get("/version")
async def version_status(_user=Depends(require_auth)):
    return await updater_svc.check_for_update()


@api.get("/status")
async def status(_user=Depends(require_auth)):
    from modules.sdr_location_gateway.sdrtrunk.spectrum import spectrum_hub

    Session = get_session_factory()
    db = Session()
    try:
        stats = _dashboard_stats(db)
    finally:
        db.close()
    last_age = None
    if spectrum_hub.last_frame_at is not None:
        last_age = round(time.time() - spectrum_hub.last_frame_at, 1)
    return {
        "version": updater_svc.current_version(),
        "metrics": get_platform().system_info(),
        "modules": {
            k: {"installed": v.get("installed"), "status": v.get("status")}
            for k, v in modules_svc.list_modules().items()
        },
        "tak": [
            {
                "id": m.server_id,
                "state": m.state.value,
                "sent": m.metrics.cot_sent,
                "dropped": m.metrics.cot_dropped,
            }
            for m in tak_registry.all()
        ],
        "gauges": hearing_gauges.snapshot(),
        "stats": stats,
        "spectrum": {
            "frames_received": spectrum_hub.frames_received,
            "last_frame_age": last_age,
        },
    }


@api.get("/locations/latest")
async def locations_latest(_user=Depends(require_auth)):
    Session = get_session_factory()
    db = Session()
    try:
        primary = _primary_tak_server(db)
        return _location_points(db, primary, limit=200)
    finally:
        db.close()


@api.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    settings = get_settings()
    token = websocket.cookies.get(settings.session_cookie)
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


@api.websocket("/ws/spectrum")
async def ws_spectrum(websocket: WebSocket):
    from modules.sdr_location_gateway.sdrtrunk.spectrum import spectrum_hub

    settings = get_settings()
    token = websocket.cookies.get(settings.session_cookie)
    if not decode_session_token(token):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    q = spectrum_hub.subscribe()
    if spectrum_hub.latest:
        await websocket.send_json(spectrum_hub.latest)
    try:
        while True:
            frame = await q.get()
            await websocket.send_json(frame)
    except WebSocketDisconnect:
        pass
    finally:
        spectrum_hub.unsubscribe(q)
