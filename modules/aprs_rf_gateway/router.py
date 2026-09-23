"""APRS RF Gateway module routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

from radiotak.platform import get_platform
from radiotak.services.audit import write_audit
from radiotak.web.deps import TEMPLATES, base_context, redirect, require_auth, verify_csrf

from . import service as aprs_service
from .settings import load_settings, save_settings

router = APIRouter(prefix="/modules/aprs", tags=["aprs"])

SERVICE_UNIT = "direwolf-aprs"


def _page(request: Request, **extra):
    cfg = load_settings()
    plat = get_platform()
    return TEMPLATES.TemplateResponse(
        request,
        "aprs_module.html",
        base_context(
            request,
            nav="aprs",
            settings=cfg,
            direwolf_running=plat.service_active(SERVICE_UNIT),
            gateway=aprs_service.stats_snapshot(),
            **extra,
        ),
    )


@router.get("", response_class=HTMLResponse)
async def aprs_home(request: Request, _user=Depends(require_auth)):
    return _page(request)


@router.get("/status.json")
async def aprs_status(_user=Depends(require_auth)):
    plat = get_platform()
    return JSONResponse(
        {
            "direwolf_running": plat.service_active(SERVICE_UNIT),
            "gateway": aprs_service.stats_snapshot(),
            "settings": load_settings(),
        }
    )


@router.post("/settings")
async def aprs_save_settings(
    request: Request,
    mycall: str = Form("N0CALL-15"),
    kiss_host: str = Form("127.0.0.1"),
    kiss_port: int = Form(8001),
    enable_rf: str | None = Form(None),
    enable_is: str | None = Form(None),
    aprs_is_server: str = Form("rotate.aprs2.net"),
    aprs_is_port: int = Form(14580),
    aprs_is_passcode: int = Form(-1),
    aprs_is_filter: str = Form("r/36.35/-82.21/50"),
    chatroom: str = Form("APRS"),
    marti_dest_group: str = Form(""),
    rtl_device: str = Form("0"),
    rtl_gain: int = Form(40),
    frequency_hz: int = Form(144390000),
    _user=Depends(require_auth),
    _csrf=Depends(verify_csrf),
):
    save_settings(
        {
            "mycall": mycall,
            "kiss_host": kiss_host,
            "kiss_port": kiss_port,
            "enable_rf": enable_rf is not None,
            "enable_is": enable_is is not None,
            "aprs_is_server": aprs_is_server,
            "aprs_is_port": aprs_is_port,
            "aprs_is_passcode": aprs_is_passcode,
            "aprs_is_filter": aprs_is_filter,
            "chatroom": chatroom,
            "marti_dest_group": marti_dest_group,
            "rtl_device": rtl_device,
            "rtl_gain": rtl_gain,
            "frequency_hz": frequency_hz,
        }
    )
    write_audit("aprs.settings", detail={"mycall": mycall.strip().upper()})
    return redirect("/modules/aprs?message=Settings+saved")


@router.post("/service/{action}")
async def aprs_service_action(
    action: str,
    request: Request,
    _user=Depends(require_auth),
    _csrf=Depends(verify_csrf),
):
    if action not in ("start", "stop", "restart"):
        return redirect("/modules/aprs?error=bad+action")
    code, out = get_platform().service_action(SERVICE_UNIT, action)
    write_audit(f"aprs.service.{action}", detail={"exit": code, "out": (out or "")[:200]})
    if code != 0 and get_platform().__class__.__name__ != "DevPlatform":
        return redirect(f"/modules/aprs?error=Direwolf+{action}+failed")
    return redirect(f"/modules/aprs?message=Direwolf+{action}")
