"""Persistent settings for the APRS RF Gateway module."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from radiotak.config import get_settings

DEFAULTS: dict[str, Any] = {
    "mycall": "N0CALL-15",
    "kiss_host": "127.0.0.1",
    "kiss_port": 8001,
    "enable_rf": True,
    "enable_is": False,
    "aprs_is_server": "rotate.aprs2.net",
    "aprs_is_port": 14580,
    "aprs_is_passcode": -1,
    "aprs_is_filter": "r/36.35/-82.21/50",
    "chatroom": "APRS",
    "marti_dest_group": "",
    "auto_approve_units": False,
    "rtl_device": "0",
    "rtl_gain": 40,
    "frequency_hz": 144390000,
    "sdr_backend": "auto",
    # TAK marker colors by transport (override TAK server Marker Appearance for APRS).
    "marker_color_rf": "#22c55e",
    "marker_color_is": "#3b82f6",
}


def module_state_dir() -> Path:
    d = get_settings().modules_state_dir / "aprs_rf_gateway"
    d.mkdir(parents=True, exist_ok=True)
    return d


def settings_path() -> Path:
    return module_state_dir() / "settings.json"


def direwolf_conf_path() -> Path:
    return module_state_dir() / "direwolf.conf"


def load_settings() -> dict[str, Any]:
    path = settings_path()
    data = dict(DEFAULTS)
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data.update(loaded)
        except (json.JSONDecodeError, OSError):
            pass
    return data


def aprs_passcode(callsign: str) -> int:
    """Standard APRS-IS passcode from callsign (SSID stripped)."""
    base = (callsign or "N0CALL").split("-", 1)[0].upper()
    h = 0x73E2
    i = 0
    while i < len(base):
        h ^= ord(base[i]) << 8
        if i + 1 < len(base):
            h ^= ord(base[i + 1])
        i += 2
    return h & 0x7FFF


def save_settings(data: dict[str, Any]) -> dict[str, Any]:
    # Preserve keys not in the form (e.g. sdr_backend) across UI saves.
    merged = load_settings()
    merged.update(data)
    # Normalize types
    merged["kiss_port"] = int(merged.get("kiss_port") or 8001)
    merged["aprs_is_port"] = int(merged.get("aprs_is_port") or 14580)
    merged["rtl_gain"] = int(merged.get("rtl_gain") or 40)
    merged["frequency_hz"] = int(merged.get("frequency_hz") or 144390000)
    merged["enable_rf"] = bool(merged.get("enable_rf"))
    merged["enable_is"] = bool(merged.get("enable_is"))
    merged["auto_approve_units"] = bool(merged.get("auto_approve_units"))
    merged["mycall"] = str(merged.get("mycall") or "N0CALL-15").strip().upper()
    merged["chatroom"] = str(merged.get("chatroom") or "APRS").strip() or "APRS"
    # -1 means derive from MYCALL (receive still needs a valid amateur call)
    raw_pc = merged.get("aprs_is_passcode", -1)
    try:
        pc = int(raw_pc)
    except (TypeError, ValueError):
        pc = -1
    if pc < 0:
        pc = aprs_passcode(merged["mycall"])
    merged["aprs_is_passcode"] = pc
    for key, default in (("marker_color_rf", "#22c55e"), ("marker_color_is", "#3b82f6")):
        color = str(merged.get(key) or default).strip()
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
            color = default
        merged[key] = color.lower()
    path = settings_path()
    path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    _sync_direwolf_mycall(merged["mycall"])
    return merged


def aprs_transport_from_raw_event(raw_event_type: str | None) -> str | None:
    """Return ``rf`` or ``is`` from ``aprs_*_{rf|is}`` raw_event_type suffixes."""
    text = str(raw_event_type or "").strip().lower()
    if text.endswith("_rf"):
        return "rf"
    if text.endswith("_is"):
        return "is"
    return None


def marker_color_for_transport(transport: str | None, cfg: dict[str, Any] | None = None) -> str | None:
    """APRS-specific TAK marker color for RF vs APRS-IS."""
    settings = cfg or load_settings()
    if transport == "rf":
        return str(settings.get("marker_color_rf") or "").strip() or None
    if transport == "is":
        return str(settings.get("marker_color_is") or "").strip() or None
    return None


def _sync_direwolf_mycall(mycall: str) -> None:
    conf = direwolf_conf_path()
    if not conf.exists():
        return
    try:
        text = conf.read_text(encoding="utf-8")
        text2 = re.sub(r"(?m)^MYCALL\s+\S+", f"MYCALL {mycall}", text)
        if text2 != text:
            conf.write_text(text2, encoding="utf-8")
    except OSError:
        pass
