"""SDR Location Gateway module routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from radiotak.config import get_settings
from radiotak.db import SdrDevice, get_session_factory
from radiotak.platform import get_platform
from radiotak.web.deps import base_context, redirect, require_auth, verify_csrf

router = APIRouter(prefix="/modules/sdr", tags=["sdr"])

_tpl_dirs = [
    str(get_settings().install_dir / "modules" / "sdr_location_gateway" / "templates"),
    str(get_settings().install_dir / "radiotak" / "web" / "templates"),
]
TEMPLATES = Jinja2Templates(directory=_tpl_dirs[0])


@router.get("", response_class=HTMLResponse)
async def sdr_page(request: Request, _user=Depends(require_auth)):
    devices = get_platform().list_sdr_devices()
    Session = get_session_factory()
    db = Session()
    try:
        saved = list(db.scalars(__import__("sqlalchemy").select(SdrDevice)))
    finally:
        db.close()
    # Render via string template fallback if file missing — use install_dir template
    from pathlib import Path

    tpl = Path(_tpl_dirs[0]) / "sdr.html"
    if not tpl.exists():
        from fastapi.responses import HTMLResponse as HR

        body = "<h1>SDR</h1><p>Devices: " + str(devices) + "</p>"
        return HR(body)
    from radiotak.web.deps import TEMPLATES as CORE

    return CORE.TemplateResponse(
        request,
        "sdr_module.html",
        base_context(
            request,
            nav="sdr",
            devices=devices,
            saved=saved,
            message=request.query_params.get("msg"),
        ),
    )


@router.post("/discover")
async def sdr_discover(request: Request, csrf_token: str = Form(""), _user=Depends(require_auth)):
    verify_csrf(request, csrf_token)
    devices = get_platform().list_sdr_devices()
    Session = get_session_factory()
    db = Session()
    try:
        for d in devices:
            exists = False
            for row in db.scalars(__import__("sqlalchemy").select(SdrDevice)):
                if row.usb_path == d.get("usb_path") or (
                    d.get("serial_number") and row.serial_number == d.get("serial_number")
                ):
                    exists = True
                    break
            if not exists:
                db.add(
                    SdrDevice(
                        name=d.get("name") or "SDR",
                        driver=d.get("driver") or "rtl",
                        serial_number=d.get("serial_number"),
                        usb_path=d.get("usb_path"),
                    )
                )
        db.commit()
    finally:
        db.close()
    return redirect("/modules/sdr?msg=Discovery+complete")


@router.post("/service/{action}")
async def sdr_service(
    action: str, request: Request, csrf_token: str = Form(""), _user=Depends(require_auth)
):
    verify_csrf(request, csrf_token)
    if action not in ("start", "stop", "restart"):
        return redirect("/modules/sdr?msg=bad+action")
    code, out = get_platform().service_action("sdrtrunk", action)
    return redirect(f"/modules/sdr?msg={out or action}")
