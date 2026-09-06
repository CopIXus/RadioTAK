"""Device timezone for operator-facing clocks.

Timestamps stay UTC in storage, CoT, and exports. Console clocks use the
appliance zone: the OS IANA timezone when it is a real local zone, otherwise
the zone saved in Settings / first-run setup.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

log = logging.getLogger("radiotak.timezone")

GENERIC_ZONES = frozenset(
    {
        "utc",
        "gmt",
        "uct",
        "zulu",
        "universal",
        "greenwich",
        "etc/utc",
        "etc/gmt",
        "etc/gmt0",
        "etc/gmt+0",
        "etc/gmt-0",
        "etc/uct",
        "etc/zulu",
        "etc/universal",
        "etc/greenwich",
    }
)

PREFERRED_ZONES = [
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Phoenix",
    "America/Los_Angeles",
    "America/Anchorage",
    "America/Adak",
    "Pacific/Honolulu",
    "America/Puerto_Rico",
    "America/St_Thomas",
    "Pacific/Guam",
    "Pacific/Pago_Pago",
    "UTC",
]

# tzutil /g names → IANA. Used on Windows/dev hosts.
WINDOWS_TZ = {
    "UTC": "UTC",
    "GMT Standard Time": "Europe/London",
    "Greenwich Standard Time": "Atlantic/Reykjavik",
    "Eastern Standard Time": "America/New_York",
    "Eastern Standard Time (Mexico)": "America/Cancun",
    "US Eastern Standard Time": "America/Indianapolis",
    "Central Standard Time": "America/Chicago",
    "Central Standard Time (Mexico)": "America/Mexico_City",
    "Canada Central Standard Time": "America/Regina",
    "US Mountain Standard Time": "America/Phoenix",
    "Mountain Standard Time": "America/Denver",
    "Mountain Standard Time (Mexico)": "America/Chihuahua",
    "Pacific Standard Time": "America/Los_Angeles",
    "Pacific Standard Time (Mexico)": "America/Tijuana",
    "Alaskan Standard Time": "America/Anchorage",
    "Aleutian Standard Time": "America/Adak",
    "Hawaiian Standard Time": "Pacific/Honolulu",
    "Atlantic Standard Time": "America/Halifax",
    "SA Western Standard Time": "America/La_Paz",
    "Pacific SA Standard Time": "America/Santiago",
    "Newfoundland Standard Time": "America/St_Johns",
    "SA Pacific Standard Time": "America/Bogota",
    "Central America Standard Time": "America/Guatemala",
    "Azores Standard Time": "Atlantic/Azores",
    "Cape Verde Standard Time": "Atlantic/Cape_Verde",
    "W. Europe Standard Time": "Europe/Berlin",
    "Romance Standard Time": "Europe/Paris",
    "Central Europe Standard Time": "Europe/Budapest",
    "Central European Standard Time": "Europe/Warsaw",
    "GTB Standard Time": "Europe/Bucharest",
    "E. Europe Standard Time": "Europe/Chisinau",
    "FLE Standard Time": "Europe/Kiev",
    "Russian Standard Time": "Europe/Moscow",
    "Arabian Standard Time": "Asia/Dubai",
    "India Standard Time": "Asia/Kolkata",
    "China Standard Time": "Asia/Shanghai",
    "Tokyo Standard Time": "Asia/Tokyo",
    "AUS Eastern Standard Time": "Australia/Sydney",
    "E. Australia Standard Time": "Australia/Brisbane",
    "AUS Central Standard Time": "Australia/Darwin",
    "Cen. Australia Standard Time": "Australia/Adelaide",
    "W. Australia Standard Time": "Australia/Perth",
    "New Zealand Standard Time": "Pacific/Auckland",
    "UTC-11": "Pacific/Pago_Pago",
    "Samoa Standard Time": "Pacific/Pago_Pago",
    "West Pacific Standard Time": "Pacific/Guam",
}

_ZONE_NAME_RE = None


def _zone_name_re():
    global _ZONE_NAME_RE
    if _ZONE_NAME_RE is None:
        import re

        _ZONE_NAME_RE = re.compile(r"^[A-Za-z0-9/_+\-]+$")
    return _ZONE_NAME_RE


def normalize_zone(name: str | None) -> str | None:
    text = (name or "").strip()
    if not text or text.lower() in ("n/a", "unknown", "none"):
        return None
    mapped = WINDOWS_TZ.get(text)
    if mapped:
        text = mapped
    if not _zone_name_re().match(text):
        return None
    if text.upper() == "UTC":
        return "UTC"
    try:
        ZoneInfo(text)
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        return None
    return text


def is_generic_zone(name: str | None) -> bool:
    text = (name or "").strip()
    if not text:
        return True
    return text.replace(" ", "").lower() in GENERIC_ZONES


def is_local_zone(name: str | None) -> bool:
    zone = normalize_zone(name)
    return bool(zone) and not is_generic_zone(zone)


def is_valid_zone(name: str | None) -> bool:
    return normalize_zone(name) is not None


def zone_info(name: str) -> ZoneInfo:
    zone = normalize_zone(name) or "UTC"
    try:
        return ZoneInfo(zone)
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        return ZoneInfo("UTC")


def parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    if isinstance(value, int | float):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=UTC)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def to_iso(value: Any) -> str:
    dt = parse_datetime(value)
    if dt is None:
        return ""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_os_timezone() -> str | None:
    from radiotak.platform import get_platform

    return normalize_zone(get_platform().os_timezone())


def configured_timezone() -> str | None:
    from radiotak.services.settings_store import load_settings_file

    try:
        data = load_settings_file()
    except Exception:  # noqa: BLE001
        return None
    return normalize_zone(str(data.get("display_timezone") or ""))


def display_timezone() -> str:
    os_tz = read_os_timezone()
    cfg = configured_timezone()
    if is_local_zone(os_tz) and not cfg:
        return os_tz or "UTC"
    if cfg:
        return cfg
    if os_tz:
        return os_tz
    return "UTC"


def needs_timezone_selection() -> bool:
    return not is_local_zone(read_os_timezone()) and not configured_timezone()


def timezone_choices() -> list[tuple[str, str]]:
    known = set(PREFERRED_ZONES)
    try:
        known.update(
            z
            for z in available_timezones()
            if "/" in z and not z.startswith("Etc/") and not z.lower().startswith(("right/", "posix/"))
        )
    except Exception:  # noqa: BLE001
        pass
    known.add("UTC")
    preferred = [z for z in PREFERRED_ZONES if z in known or is_valid_zone(z)]
    rest = sorted(z for z in known if z not in preferred)
    out: list[tuple[str, str]] = []
    for zone in preferred + rest:
        if is_valid_zone(zone):
            out.append((zone, zone.replace("_", " ")))
    if not out:
        out = [("UTC", "UTC")]
    return out


def format_display(value: Any, *, seconds: bool = True) -> str:
    dt = parse_datetime(value)
    if dt is None:
        return str(value).strip() if isinstance(value, str) and str(value).strip() else ""
    local = dt.astimezone(zone_info(display_timezone()))
    fmt = "%Y-%m-%d %H:%M:%S" if seconds else "%Y-%m-%d %H:%M"
    return local.strftime(fmt)


def timezone_context(*, include_choices: bool = False) -> dict[str, Any]:
    os_tz = read_os_timezone() or ""
    cfg = configured_timezone() or ""
    display = display_timezone()
    ctx: dict[str, Any] = {
        "os": os_tz,
        "configured": cfg,
        "display": display,
        "needs_selection": needs_timezone_selection(),
        "source": "settings" if cfg else ("os" if is_local_zone(os_tz) else "fallback"),
        "now": format_display(datetime.now(UTC)),
    }
    if include_choices:
        ctx["choices"] = timezone_choices()
        ctx["preferred"] = [z for z in PREFERRED_ZONES if is_valid_zone(z)]
    return ctx


def apply_timezone(name: str) -> tuple[bool, str]:
    zone = normalize_zone(name)
    if not zone:
        return False, "Invalid time zone"
    from radiotak.platform import get_platform
    from radiotak.services.settings_store import update_settings

    update_settings({"display_timezone": zone})
    code, out = get_platform().set_os_timezone(zone)
    if code != 0:
        log.info("OS timezone not changed (%s); console clocks still use %s", out or code, zone)
        return True, f"Saved {zone} for console clocks (device clock unchanged)"
    return True, f"Time zone set to {zone}"
