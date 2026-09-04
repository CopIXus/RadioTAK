"""Branding logo storage under data_dir/branding/."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from radiotak.config import get_settings
from radiotak.services.settings_store import load_settings_file, update_settings

ALLOWED_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/svg+xml": ".svg",
}
MAX_BYTES = 512 * 1024
_SCRIPT_RE = re.compile(r"<script[\s\S]*?</script>|on\w+\s*=", re.IGNORECASE)


def branding_dir() -> Path:
    d = get_settings().data_dir / "branding"
    d.mkdir(parents=True, exist_ok=True)
    return d


def logo_path() -> Optional[Path]:
    cfg = load_settings_file()
    name = (cfg.get("customization") or {}).get("logo_filename") or ""
    if not name:
        return None
    path = branding_dir() / name
    return path if path.exists() else None


def product_logo_path() -> Path:
    return Path(__file__).resolve().parent.parent / "web" / "static" / "img" / "logo.png"


def favicon_path() -> Optional[Path]:
    product = product_logo_path()
    if product.exists():
        return product
    p = logo_path()
    if p and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".svg"}:
        return p
    return None


def save_logo(data: bytes, mime: str) -> Path:
    mime = (mime or "").lower().strip()
    if mime not in ALLOWED_MIME:
        raise ValueError(f"Unsupported type: {mime}. Use PNG, SVG, or JPEG.")
    if len(data) > MAX_BYTES:
        raise ValueError("File too large (max 512 KB)")
    if mime == "image/svg+xml":
        text = data.decode("utf-8", errors="ignore")
        if _SCRIPT_RE.search(text):
            raise ValueError("SVG contains disallowed script content")
        data = text.encode("utf-8")
    # clear old logos
    for old in branding_dir().glob("logo.*"):
        try:
            old.unlink()
        except OSError:
            pass
    dest = branding_dir() / f"logo{ALLOWED_MIME[mime]}"
    dest.write_bytes(data)
    update_settings({"customization": {"logo_filename": dest.name}})
    return dest


def remove_logo() -> None:
    for old in branding_dir().glob("logo.*"):
        try:
            old.unlink()
        except OSError:
            pass
    update_settings({"customization": {"logo_filename": ""}})
