"""Shared template context helpers and deps."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import HTTPException, Request
from fastapi.templating import Jinja2Templates
from starlette.responses import RedirectResponse

from radiotak.auth import decode_session_token, needs_setup
from radiotak.config import get_settings
from radiotak.services.branding import logo_path
from radiotak.services.modules import is_installed
from radiotak.services.settings_store import (
    banner_font_css,
    banner_size_px,
    load_settings_file,
)
from radiotak.services.updater import current_version
from radiotak.web.help_text import help_as_json

_PKG_TEMPLATES = Path(__file__).resolve().parent / "templates"
TEMPLATES = Jinja2Templates(directory=str(_PKG_TEMPLATES))


def _custom_console_title(title: str) -> str:
    """Agency name when the console title is not the product name."""
    text = (title or "").strip()
    if text and text.casefold() != "radiotak":
        return text
    return ""


def _banner_display_text(cust: dict, title: str = "") -> str:
    """Top-bar copy: dedicated banner text, else a customized console title."""
    text = (cust.get("banner_text") or "").strip()
    if text:
        return text[:120]
    return _custom_console_title(title)[:120]


def _banner_should_show(cust: dict, title: str = "") -> bool:
    """Show the top banner when branding text is set, unless the user opted out."""
    text = _banner_display_text(cust, title)
    if not text:
        return False
    # Explicit opt-out (unchecked + saved) hides the banner while keeping text.
    if cust.get("banner_opt_out"):
        return False
    # Show whenever text is configured. Legacy installs often saved text with
    # banner_enabled left false because the opt-in checkbox was easy to miss.
    return True


def base_context(request: Request, nav: str = "", **extra):
    cfg = load_settings_file()
    cust = cfg.get("customization") or {}
    session = getattr(request.state, "session", None) or {}
    has_logo = logo_path() is not None
    title = cfg.get("title", "RadioTAK")
    banner_display = _banner_display_text(cust, title)
    return {
        "request": request,
        "nav": nav,
        "title": title,
        "accent": cfg.get("accent", "#3b82f6"),
        "cyan": cfg.get("cyan", "#06b6d4"),
        "theme": cfg.get("theme", "dark"),
        "version": current_version(),
        "branch": cfg.get("github_branch", "main"),
        "csrf_token": session.get("csrf", ""),
        "username": session.get("u", ""),
        "sdr_installed": is_installed("sdr_location_gateway"),
        "hide_sidebar": False,
        "help_json": help_as_json(),
        # Banner shows whenever branding text is configured; checkbox can still hide it.
        "banner_text": (cust.get("banner_text") or "")[:120],
        "banner_display": banner_display,
        "banner_enabled": _banner_should_show(cust, title),
        "banner_color": cust.get("banner_color") or "#f1f5f9",
        "banner_font_css": banner_font_css(cust.get("banner_font") or "JetBrains Mono"),
        "banner_size_px": banner_size_px(cust.get("banner_size") or "medium"),
        "banner_sub": cfg.get("tailscale_hostname") or "",
        "logo_url": "/branding/logo" if has_logo else "",
        "product_logo_url": "/static/img/logo.png",
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
