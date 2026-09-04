"""Marketplace module registry."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

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


SDR_MODULE_ID = "sdr_location_gateway"
_upgrade_lock = threading.Lock()
_upgrade_state: dict[str, Any] = {"running": False, "last_code": None, "last_reason": None}


def decoder_build_info() -> dict[str, Any]:
    """Installed SDRTrunk build facts (safe to call when the module is absent)."""
    try:
        from modules.sdr_location_gateway.sdrtrunk.build import sdrtrunk_build_info

        return sdrtrunk_build_info()
    except Exception as exc:  # noqa: BLE001
        return {
            "installed": False,
            "has_exporters": False,
            "upgrade_available": False,
            "error": str(exc),
        }


def decoder_upgrade_state() -> dict[str, Any]:
    with _upgrade_lock:
        return dict(_upgrade_state)


def decoder_upgrade_needed() -> bool:
    if not is_installed(SDR_MODULE_ID):
        return False
    info = decoder_build_info()
    return bool(info.get("installed")) and bool(info.get("upgrade_available"))


def upgrade_decoder_async(reason: str = "manual") -> bool:
    """Re-run the SDR module installer in a daemon thread.

    install.sh is idempotent: it only downloads when the installed fork tag differs
    from the tag it ships, and it restarts sdrtrunk if the decoder was running.
    Returns False if an upgrade is already in flight.
    """
    from radiotak.platform import get_platform

    if get_platform().__class__.__name__ == "DevPlatform":
        return False
    with _upgrade_lock:
        if _upgrade_state["running"]:
            return False
        _upgrade_state["running"] = True
        _upgrade_state["last_reason"] = reason

    def _work() -> None:
        code = 1
        try:
            code, _ = install_module(SDR_MODULE_ID)
        except Exception as exc:  # noqa: BLE001
            append_install_log(SDR_MODULE_ID, f"decoder upgrade failed: {exc}")
        finally:
            with _upgrade_lock:
                _upgrade_state["running"] = False
                _upgrade_state["last_code"] = code

    threading.Thread(target=_work, name="sdrtrunk-upgrade", daemon=True).start()
    return True


def upgrade_decoder_on_startup(delay_seconds: float = 20.0) -> None:
    """Self-heal: after a RadioTAK update, pull the matching SDRTrunk fork build.

    Without this, ``git pull`` / the System → Update button only refreshes RadioTAK
    while the decoder stays on whatever zip was unpacked at first install (for a
    long time that was stock 0.6.1, which has no :29501/:29500 exporters).
    """
    import logging
    import time

    log = logging.getLogger("radiotak.modules")

    def _check() -> None:
        time.sleep(delay_seconds)
        try:
            if decoder_upgrade_needed():
                info = decoder_build_info()
                log.warning(
                    "SDRTrunk build %s lacks exporters or is behind %s — upgrading decoder",
                    info.get("version"),
                    info.get("expected_tag"),
                )
                upgrade_decoder_async(reason="startup")
        except Exception as exc:  # noqa: BLE001
            log.warning("decoder upgrade check failed: %s", exc)

    threading.Thread(target=_check, name="sdrtrunk-upgrade-check", daemon=True).start()


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
