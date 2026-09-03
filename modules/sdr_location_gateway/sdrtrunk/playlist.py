"""Minimal SDRTrunk playlist.xml writer for P25 control channels."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable


def write_p25_playlist(
    path: Path,
    *,
    system_name: str,
    control_channels_mhz: Iterable[float],
    auto_start: bool = True,
) -> Path:
    """Write a minimal playlist the operator can refine in SDRTrunk GUI."""
    root = ET.Element("playlist")
    system = ET.SubElement(root, "system", {"name": system_name, "protocol": "APCO25"})
    for mhz in control_channels_mhz:
        hz = int(round(float(mhz) * 1_000_000))
        ET.SubElement(
            system,
            "channel",
            {
                "name": f"CC {mhz}",
                "frequency": str(hz),
                "type": "control",
                "autostart": "true" if auto_start else "false",
            },
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(root)
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return path
