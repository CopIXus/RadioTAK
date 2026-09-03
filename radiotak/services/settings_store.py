"""Persistent settings.json helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from radiotak.config import Settings, get_settings, reload_settings

DEFAULTS: dict[str, Any] = {
    "theme": "dark",
    "accent": "#06b6d4",
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
}


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
        if key == "forwarding" and isinstance(value, dict):
            data.setdefault("forwarding", {}).update(value)
        else:
            data[key] = value
    save_settings_file(data, settings)
    return data
