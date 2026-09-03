"""Marketplace module registry."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Optional

from radiotak.config import get_settings


def modules_root() -> Path:
    return get_settings().install_dir / "modules"


def state_dir() -> Path:
    d = get_settings().modules_state_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_modules() -> dict[str, dict[str, Any]]:
    root = modules_root()
    result: dict[str, dict[str, Any]] = {}
    if not root.is_dir():
        return result
    for path in sorted(root.iterdir()):
        meta = path / "module.json"
        if not meta.exists():
            continue
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        mid = data.get("id") or path.name
        data["id"] = mid
        data["path"] = str(path)
        data["installed"] = (state_dir() / mid / "installed").exists()
        err_path = state_dir() / mid / "last-error.txt"
        if not data["installed"] and err_path.exists():
            data["last_error"] = err_path.read_text(encoding="utf-8", errors="replace")[-4000:]
        result[mid] = data
    return result


def is_installed(module_id: str) -> bool:
    return (state_dir() / module_id / "installed").exists()


def mark_installed(module_id: str) -> None:
    d = state_dir() / module_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "installed").write_text("1", encoding="utf-8")


def mark_uninstalled(module_id: str) -> None:
    marker = state_dir() / module_id / "installed"
    if marker.exists():
        marker.unlink()


_install_logs: dict[str, list[str]] = {}
_lock = threading.Lock()


def get_install_log(module_id: str) -> list[str]:
    with _lock:
        return list(_install_logs.get(module_id, []))


def append_install_log(module_id: str, line: str) -> None:
    with _lock:
        _install_logs.setdefault(module_id, []).append(line)


def clear_install_log(module_id: str) -> None:
    with _lock:
        _install_logs[module_id] = []


def install_module(module_id: str) -> tuple[int, str]:
    from radiotak.platform import get_platform

    clear_install_log(module_id)
    append_install_log(module_id, f"Installing {module_id}…")
    code, out = get_platform().run_priv("module-install", module_id)
    for line in out.splitlines():
        append_install_log(module_id, line)
    if code == 0 or get_platform().__class__.__name__ == "DevPlatform":
        # DevPlatform always succeeds — mark installed for UI testing
        mark_installed(module_id)
        err_path = state_dir() / module_id / "last-error.txt"
        if err_path.exists():
            err_path.unlink()
        append_install_log(module_id, "Installed.")
        return 0, out
    append_install_log(module_id, f"Failed (exit {code})")
    err_dir = state_dir() / module_id
    err_dir.mkdir(parents=True, exist_ok=True)
    (err_dir / "last-error.txt").write_text(out or f"exit {code}", encoding="utf-8")
    return code, out


def uninstall_module(module_id: str) -> tuple[int, str]:
    from radiotak.platform import get_platform

    clear_install_log(module_id)
    code, out = get_platform().run_priv("module-uninstall", module_id)
    for line in out.splitlines():
        append_install_log(module_id, line)
    mark_uninstalled(module_id)
    append_install_log(module_id, "Uninstalled.")
    return code, out


def load_module_routers():
    """Import routers from installed modules that provide router.py."""
    routers = []
    for mid, meta in list_modules().items():
        if not meta.get("installed") and meta.get("status") != "bundled":
            # Always load bundled routers in dev if present
            if meta.get("status") == "coming_soon":
                continue
        router_path = Path(meta["path"]) / "router.py"
        if not router_path.exists():
            continue
        # Only mount if installed OR status is available/bundled for development
        if not is_installed(mid) and meta.get("status") not in ("bundled", "available"):
            if meta.get("status") == "coming_soon":
                continue
            # Still mount SDR module pages in stub mode for UX
            if mid != "sdr_location_gateway":
                continue
        import importlib.util

        spec = importlib.util.spec_from_file_location(f"modules.{mid}.router", router_path)
        if not spec or not spec.loader:
            continue
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            if hasattr(mod, "router"):
                routers.append(mod.router)
        except Exception:  # noqa: BLE001
            continue
    return routers
