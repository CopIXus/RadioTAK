"""SDRTrunk playlist_v2.xml writer — frequencies entered in the RadioTAK UI."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Sequence

# SDRTrunk 0.6.x Jackson playlist version (0.6.1 writes version="4")
PLAYLIST_VERSION = "4"

_DECODE = {
    "P25": ("decodeConfigP25Phase1", {"modulation": "C4FM", "traffic_channel_pool_size": "3", "ignore_data_calls": "false"}),
    "P25_LSM": ("decodeConfigP25Phase1", {"modulation": "CQPSK", "traffic_channel_pool_size": "3", "ignore_data_calls": "false"}),
    "DMR": ("decodeConfigDMR", {"ignore_data_calls": "false"}),
    "NFM": ("decodeConfigNBFM", {}),
}


def playlist_dir(settings=None) -> Path:
    if settings is None:
        from radiotak.config import get_settings

        settings = get_settings()
    # SDRTrunk HOME=/var/lib/radiotak → application root SDRTrunk/playlist
    return settings.data_dir / "SDRTrunk" / "playlist"


def default_playlist_path(settings=None) -> Path:
    return playlist_dir(settings) / "default.xml"


def properties_path(settings=None) -> Path:
    if settings is None:
        from radiotak.config import get_settings

        settings = get_settings()
    return settings.data_dir / "SDRTrunk" / "SDRTrunk.properties"


EXPORT_PROPERTY_DEFAULTS = {
    "spectrum_export_enabled": "true",
    "spectrum_export_host": "127.0.0.1",
    "spectrum_export_port": "29501",
    "geo_event_export_enabled": "true",
    "geo_event_export_host": "127.0.0.1",
    "geo_event_export_port": "29500",
}


def ensure_export_properties(settings=None) -> Path:
    """Ensure CopIXus exporter keys exist in SDRTrunk.properties (do not clobber other keys)."""
    path = properties_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    missing = [f"{k}={v}" for k, v in EXPORT_PROPERTY_DEFAULTS.items() if f"{k}=" not in text]
    if to_add := missing:
        prefix = "" if not text or text.endswith("\n") else "\n"
        path.write_text(text + prefix + "\n".join(to_add) + "\n", encoding="utf-8")
    elif not path.exists():
        path.write_text("\n".join(f"{k}={v}" for k, v in EXPORT_PROPERTY_DEFAULTS.items()) + "\n", encoding="utf-8")
    return path


def tuner_settings_path(settings=None) -> Path:
    if settings is None:
        from radiotak.config import get_settings

        settings = get_settings()
    return settings.data_dir / ".sdrtrunk" / "tuner_settings.json"


def _preferred_tuner_from_devices(devices) -> str | None:
    if not devices:
        return None
    for dev in devices:
        if not getattr(dev, "enabled", True):
            continue
        serial = getattr(dev, "serial_number", None)
        if serial and str(serial).strip():
            return str(serial).strip()
        name = getattr(dev, "name", None)
        if name and str(name).strip():
            return str(name).strip()
    return None


def parse_frequencies(text: str) -> list[int]:
    """Parse operator input into Hertz.

    Values below 10_000 are treated as MHz (851.0125 → 851012500).
    Larger values are treated as Hz. Separators: comma, semicolon, whitespace.
    """
    if not text or not text.strip():
        return []
    chunks = re.split(r"[\s,;]+", text.strip())
    out: list[int] = []
    seen: set[int] = set()
    for raw in chunks:
        token = raw.lower().replace("mhz", "").replace("hz", "").replace("khz", "").strip()
        if not token:
            continue
        try:
            value = float(token)
        except ValueError as exc:
            raise ValueError(f"Invalid frequency: {raw!r}") from exc
        if value <= 0:
            raise ValueError(f"Frequency must be positive: {raw!r}")
        lowered = raw.lower()
        if "khz" in lowered:
            hz = int(round(value * 1_000))
        elif "hz" in lowered and "mhz" not in lowered and "khz" not in lowered:
            hz = int(round(value))
        elif value < 10_000:
            hz = int(round(value * 1_000_000))
        else:
            hz = int(round(value))
        if hz not in seen:
            seen.add(hz)
            out.append(hz)
    return out


def hz_to_mhz_str(hz: int) -> str:
    mhz = hz / 1_000_000
    text = f"{mhz:.6f}".rstrip("0").rstrip(".")
    return text


def frequencies_to_text(hz_list: Iterable[int]) -> str:
    return "\n".join(hz_to_mhz_str(int(h)) for h in hz_list)


def _decode_elem(protocol: str) -> ET.Element:
    key = (protocol or "P25").upper()
    if key == "P25-LSM":
        key = "P25_LSM"
    type_name, attrs = _DECODE.get(key, _DECODE["P25"])
    return ET.Element("decode_configuration", {"type": type_name, **attrs})


def _source_elem(frequencies_hz: Sequence[int], preferred_tuner: str | None = None) -> ET.Element:
    freqs = [int(f) for f in frequencies_hz]
    if len(freqs) > 1:
        attrib = {"type": "sourceConfigTunerMultipleFrequency", "source_type": "TUNER_MULTIPLE_FREQUENCIES"}
        if preferred_tuner:
            attrib["preferred_tuner"] = preferred_tuner
        el = ET.Element("source_configuration", attrib)
        for hz in freqs:
            fe = ET.SubElement(el, "frequency")
            fe.text = str(hz)
        return el
    attrib = {"type": "sourceConfigTuner", "source_type": "TUNER"}
    if preferred_tuner:
        attrib["preferred_tuner"] = preferred_tuner
    el = ET.Element("source_configuration", attrib)
    fe = ET.SubElement(el, "frequency")
    fe.text = str(freqs[0] if freqs else 0)
    return el


def write_playlist(
    path: Path,
    systems: Sequence[dict[str, Any]],
) -> Path:
    """Write an SDRTrunk playlist_v2 file from RadioTAK radio-system dicts.

    Each system dict: name, protocol, site, frequencies_hz, auto_start, preferred_tuner.
    """
    root = ET.Element("playlist", {"version": PLAYLIST_VERSION})
    order = 1
    for sys in systems:
        freqs = [int(f) for f in (sys.get("frequencies_hz") or [])]
        if not freqs:
            continue
        name = str(sys.get("name") or "Radio")
        site = str(sys.get("site") or "1")
        protocol = str(sys.get("protocol") or "P25")
        auto = bool(sys.get("auto_start", True))
        channel = ET.SubElement(
            root,
            "channel",
            {
                "name": name,
                "system": name,
                "site": site,
                "enabled": "true" if auto else "false",
                "order": str(order),
            },
        )
        channel.append(_decode_elem(protocol))
        channel.append(_source_elem(freqs, sys.get("preferred_tuner")))
        ET.SubElement(channel, "event_log_configuration")
        ET.SubElement(channel, "record_configuration")
        ET.SubElement(channel, "aux_decode_configuration")
        al = ET.SubElement(channel, "alias_list_name")
        al.text = name
        order += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return path


def write_p25_playlist(
    path: Path,
    *,
    system_name: str,
    control_channels_mhz: Iterable[float],
    auto_start: bool = True,
) -> Path:
    """Back-compat wrapper used by older callers."""
    freqs = [int(round(float(m) * 1_000_000)) for m in control_channels_mhz]
    return write_playlist(
        path,
        [{"name": system_name, "protocol": "P25", "site": "1", "frequencies_hz": freqs, "auto_start": auto_start}],
    )


def is_listening(row) -> bool:
    """True when the system is included and auto-started in the decoder playlist."""
    if not getattr(row, "enabled", True):
        return False
    cfg = getattr(row, "config", None) or {}
    return bool(cfg.get("auto_start", True))


def set_row_listening(row, on: bool) -> None:
    """Flip both enabled and auto_start so Listen is a single operator control."""
    on = bool(on)
    row.enabled = on
    cfg = dict(getattr(row, "config", None) or {})
    cfg["auto_start"] = on
    row.config = cfg


def assign_listen_states(listening: list[bool], tuner_count: int) -> list[str]:
    """Map each row to off / active / starved given how many dongles are present.

    Listening systems consume tuners in list order (same as the SDR table / playlist).
    Extra listening systems beyond tuner_count are starved until another SDR is plugged in.
    """
    slots = max(0, int(tuner_count))
    used = 0
    states: list[str] = []
    for on in listening:
        if not on:
            states.append("off")
            continue
        if used < slots:
            states.append("active")
            used += 1
        else:
            states.append("starved")
    return states


def apply_tuner_slots(systems: list[dict[str, Any]], tuner_count: int) -> list[dict[str, Any]]:
    """Only the first tuner_count auto-start systems keep auto_start for the playlist."""
    slots = max(0, int(tuner_count))
    used = 0
    for sys in systems:
        if not sys.get("auto_start"):
            continue
        if used < slots:
            used += 1
        else:
            sys["auto_start"] = False
    return systems


def systems_from_db_rows(rows, devices=None) -> list[dict[str, Any]]:
    preferred = _preferred_tuner_from_devices(devices)
    out: list[dict[str, Any]] = []
    for row in rows:
        if not getattr(row, "enabled", True):
            continue
        cfg = row.config or {}
        freqs = cfg.get("frequencies_hz") or []
        if not freqs:
            continue
        out.append(
            {
                "name": row.name,
                "protocol": row.protocol or cfg.get("protocol") or "P25",
                "site": cfg.get("site") or "1",
                "frequencies_hz": [int(f) for f in freqs],
                "auto_start": bool(cfg.get("auto_start", True)),
                "preferred_tuner": preferred or cfg.get("preferred_tuner"),
            }
        )
    return out


def write_tuner_preferences(devices, settings=None) -> Path | None:
    """Write RadioTAK SDR device UI settings for fork / ops reference.

    SDRTrunk may need matching tuner prefs configured in its GUI or fork patch;
    this JSON file is RadioTAK's export of operator settings under
    ``{data_dir}/.sdrtrunk/tuner_settings.json``.
    """
    if settings is None:
        from radiotak.config import get_settings

        settings = get_settings()
    if not devices:
        return None
    payload = {
        "schema": "radiotak.tuner_settings.v1",
        "note": (
            "SDRTrunk may need matching tuner preferences; "
            "this is RadioTAK's export of UI settings for the fork/ops."
        ),
        "devices": [
            {
                "name": dev.name,
                "serial": dev.serial_number,
                "enabled": bool(getattr(dev, "enabled", True)),
                "gain_mode": getattr(dev, "gain_mode", "auto") or "auto",
                "gain": getattr(dev, "gain", None),
                "ppm_correction": float(getattr(dev, "ppm_correction", 0.0) or 0.0),
                "bias_tee": bool(getattr(dev, "bias_tee", False)),
            }
            for dev in devices
        ],
    }
    path = tuner_settings_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def rebuild_default_playlist(rows, settings=None, devices=None, tuner_count: int | None = None) -> Path:
    if settings is None:
        from radiotak.config import get_settings

        settings = get_settings()
    write_tuner_preferences(devices or [], settings=settings)
    ensure_export_properties(settings=settings)
    systems = systems_from_db_rows(rows, devices=devices)
    if tuner_count is not None:
        apply_tuner_slots(systems, tuner_count)
    return write_playlist(
        default_playlist_path(settings),
        systems,
    )
