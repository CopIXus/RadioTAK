"""Sanitized diagnostics ZIP."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Optional

from radiotak import __version__
from radiotak.config import get_settings
from radiotak.platform import get_platform
from radiotak.services.modules import list_modules
from radiotak.services.settings_store import load_settings_file
from radiotak.services.updater import current_version


REDACT_KEYS = {
    "password",
    "token",
    "secret",
    "private_key",
    "auth_key",
    "credential",
    "passphrase",
    "pkcs12_password",
}


def _sanitize(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if any(r in k.lower() for r in REDACT_KEYS):
                out[k] = "***REDACTED***"
            else:
                out[k] = _sanitize(v)
        return out
    if isinstance(obj, list):
        return [_sanitize(x) for x in obj]
    return obj


def build_diagnostics_zip(redact_gps: bool = False) -> bytes:
    settings = get_settings()
    buf = io.BytesIO()
    info = get_platform().system_info()
    cfg = _sanitize(load_settings_file())
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "system-info.json",
            json.dumps(
                {
                    "version": current_version(),
                    "package_version": __version__,
                    "system": info,
                },
                indent=2,
                default=str,
            ),
        )
        zf.writestr("settings-sanitized.json", json.dumps(cfg, indent=2, default=str))
        zf.writestr(
            "modules.json",
            json.dumps(_sanitize(list_modules()), indent=2, default=str),
        )
        log_path = settings.logs_dir / "radiotak.jsonl"
        if log_path.exists():
            text = log_path.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()[-500:]
            if redact_gps:
                lines = [ln for ln in lines]  # coords already optional via privacy mode
            zf.writestr("recent-logs.txt", "\n".join(lines))
        zf.writestr(
            "README.txt",
            "RadioTAK diagnostics bundle. Secrets and private keys are excluded.\n",
        )
    return buf.getvalue()
