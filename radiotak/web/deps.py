"""Shared template context helpers and deps."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import HTTPException, Request
from fastapi.templating import Jinja2Templates
from starlette.responses import RedirectResponse

from radiotak.auth import decode_session_token, needs_setup
from radiotak.config import get_settings
from radiotak.services.modules import is_installed
from radiotak.services.settings_store import load_settings_file
from radiotak.services.updater import current_version

_PKG_TEMPLATES = Path(__file__).resolve().parent / "templates"
TEMPLATES = Jinja2Templates(directory=str(_PKG_TEMPLATES))


def base_context(request: Request, nav: str = "", **extra):
    cfg = load_settings_file()
    session = getattr(request.state, "session", None) or {}
    return {
        "request": request,
        "nav": nav,
        "title": cfg.get("title", "RadioTAK"),
        "accent": cfg.get("accent", "#06b6d4"),
        "version": current_version(),
        "branch": cfg.get("github_branch", "main"),
        "csrf_token": session.get("csrf", ""),
        "username": session.get("u", ""),
        "sdr_installed": is_installed("sdr_location_gateway"),
        "hide_sidebar": False,
        **extra,
    }


async def require_auth(request: Request):
    settings = get_settings()
    if needs_setup(settings):
        raise HTTPException(status_code=307, headers={"Location": "/setup"})
    token = request.cookies.get(settings.session_cookie)
    data = decode_session_token(token) if token else None
    if not data:
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    request.state.session = data
    return data


def verify_csrf(request: Request, token: Optional[str]) -> None:
    session = getattr(request.state, "session", {}) or {}
    expected = session.get("csrf")
    if not expected or not token or token != expected:
        raise HTTPException(status_code=403, detail="CSRF validation failed")


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)
