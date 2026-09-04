"""Persistent settings.json helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from radiotak.config import Settings, get_settings, reload_settings

DEFAULTS: dict[str, Any] = {
    "theme": "dark",
    "accent": "#3b82f6",
    "cyan": "#06b6d4",
    "title": "RadioTAK",
    "github_branch": "main",
    "bind_host": "0.0.0.0",
    "bind_port": 5001,
    "log_retention_days": 14,
    "observation_retention_days": 7,
    "event_retention_days": 1,
    "audit_retention_days": 30,
    "max_log_mb": 200,
    "privacy_mode": False,
    "forwarding": {
        "unknown_radios": "deny",
        "duplicate_suppression": True,
        "min_interval_seconds": 2,
        "stationary_heartbeat_seconds": 45,
        "stale_seconds": 120,
        "min_movement_meters": 5,
        "default_ce_meters": 20,
    },
    "map_history_minutes": 60,
    "tailscale_hostname": "",
    "customization": {
        "banner_enabled": True,
        "banner_opt_out": False,
        "banner_text": "",
        "banner_font": "JetBrains Mono",
        "banner_size": "medium",
        "banner_color": "#f1f5f9",
        "logo_filename": "",
    },
    "spectrum": {
        "host": "127.0.0.1",
        "port": 29501,
        "enabled": True,
    },
    "novnc": {
        "enabled": False,
        "url": "/novnc/",
    },
}

_BANNER_FONT_CSS = {
    "JetBrains Mono": "'JetBrains Mono', monospace",
    "Orbitron": "'Orbitron', sans-serif",
    "DM Sans": "'DM Sans', sans-serif",
    "System UI": "system-ui, -apple-system, sans-serif",
}

_BANNER_SIZE_PX = {"small": "14px", "medium": "20px", "large": "28px"}


def load_settings_file(settings: Optional[Settings] = None) -> dict[str, Any]:
    settings = settings or get_settings()
    path = settings.settings_path
    if not path.exists():
        data = dict(DEFAULTS)
        save_settings_file(data, settings)
        return data
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = {}
    merged = dict(DEFAULTS)
    merged.update(data)
    if "forwarding" in data and isinstance(data["forwarding"], dict):
        fwd = dict(DEFAULTS["forwarding"])
        fwd.update(data["forwarding"])
        merged["forwarding"] = fwd
    if "customization" in data and isinstance(data["customization"], dict):
        cust = dict(DEFAULTS["customization"])
        cust.update(data["customization"])
        merged["customization"] = cust
    if "spectrum" in data and isinstance(data["spectrum"], dict):
        spec = dict(DEFAULTS["spectrum"])
        spec.update(data["spectrum"])
        merged["spectrum"] = spec
    if "novnc" in data and isinstance(data["novnc"], dict):
        nv = dict(DEFAULTS["novnc"])
        nv.update(data["novnc"])
        merged["novnc"] = nv
    return merged


def save_settings_file(data: dict[str, Any], settings: Optional[Settings] = None) -> None:
    settings = settings or get_settings()
    settings.ensure_dirs()
    path: Path = settings.settings_path
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    reload_settings()


def update_settings(updates: dict[str, Any], settings: Optional[Settings] = None) -> dict[str, Any]:
    data = load_settings_file(settings)
    for key, value in updates.items():
        if key in ("forwarding", "customization", "spectrum", "novnc") and isinstance(value, dict):
            data.setdefault(key, {}).update(value)
        else:
            data[key] = value
    save_settings_file(data, settings)
    return data


def banner_font_css(name: str) -> str:
    return _BANNER_FONT_CSS.get(name, _BANNER_FONT_CSS["JetBrains Mono"])


def banner_size_px(size: str) -> str:
    return _BANNER_SIZE_PX.get(size, "20px")
