"""Report which SDRTrunk build is installed and whether it carries the CopIXus exporters.

The waterfall (:29501), GPS/Live Events (:29500), and talkgroup audio (:29502) feeds
only exist in the ``CopIXus/sdrtrunk`` fork. A stock DSheirer build decodes audio
fine but never connects to RadioTAK, so the canvas stays black, no units appear,
and the Listen button has nothing to play. This module lets the UI, the updater,
and the startup self-heal all agree on the same facts.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any

_TAG_RE = re.compile(r'^TAG="(v[^"]+)"', re.MULTILINE)
_JAR_RE = re.compile(r"^sdr-trunk-(.+)\.jar$")


def install_script_path() -> Path:
    return Path(__file__).resolve().parent.parent / "install.sh"


def expected_fork_tag() -> str | None:
    """Tag the module installer will install (single source of truth: install.sh)."""
    try:
        m = _TAG_RE.search(install_script_path().read_text(encoding="utf-8"))
    except OSError:
        return None
    return m.group(1) if m else None


def sdrtrunk_app_dir(settings=None) -> Path:
    if settings is None:
        from radiotak.config import get_settings

        settings = get_settings()
    return settings.data_dir / "sdrtrunk" / "app"


def _jar_has_exporters(jar: Path) -> bool:
    try:
        with zipfile.ZipFile(jar) as z:
            names = z.namelist()
            return "io/github/dsheirer/export/DftFrameExporter.class" in names
    except (OSError, zipfile.BadZipFile):
        return False


def _jar_has_audio_exporter(jar: Path) -> bool:
    try:
        with zipfile.ZipFile(jar) as z:
            return "io/github/dsheirer/export/AudioFrameExporter.class" in z.namelist()
    except (OSError, zipfile.BadZipFile):
        return False


def sdrtrunk_build_info(settings=None) -> dict[str, Any]:
    """Describe the installed decoder.

    Keys: installed, version, fork_tag, has_exporters, has_audio_exporter,
    expected_tag, upgrade_available, app_dir.
    ``has_exporters`` / ``has_audio_exporter`` are decided from the jar contents,
    not the marker file, so a hand-installed fork build is still recognised.
    """
    app = sdrtrunk_app_dir(settings)
    expected = expected_fork_tag()
    info: dict[str, Any] = {
        "installed": False,
        "version": None,
        "fork_tag": None,
        "has_exporters": False,
        "has_audio_exporter": False,
        "expected_tag": expected,
        "upgrade_available": False,
        "app_dir": str(app),
    }
    lib = app / "lib"
    if not lib.is_dir():
        return info
    info["installed"] = True
    marker = app / ".radiotak-fork"
    if marker.is_file():
        try:
            info["fork_tag"] = marker.read_text(encoding="utf-8").strip() or None
        except OSError:
            pass
    for jar in sorted(lib.glob("sdr-trunk-*.jar")):
        m = _JAR_RE.match(jar.name)
        if m:
            info["version"] = m.group(1)
        if _jar_has_exporters(jar):
            info["has_exporters"] = True
        if _jar_has_audio_exporter(jar):
            info["has_audio_exporter"] = True
    if expected:
        info["upgrade_available"] = (
            info["fork_tag"] != expected
            or not info["has_exporters"]
            or not info["has_audio_exporter"]
        )
    elif not info["has_exporters"] or not info["has_audio_exporter"]:
        info["upgrade_available"] = True
    return info


def build_label(info: dict[str, Any]) -> str:
    if not info.get("installed"):
        return "SDRTrunk not installed"
    ver = info.get("version") or "unknown"
    if info.get("has_exporters") and info.get("has_audio_exporter"):
        return f"SDRTrunk {ver} (CopIXus exporters)"
    if info.get("has_exporters"):
        return f"SDRTrunk {ver} (spectrum/GPS only — upgrade for Listen audio)"
    return f"SDRTrunk {ver} stock — no waterfall / GPS / audio export"
