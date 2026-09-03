"""Tailscale helpers."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any


def is_installed() -> bool:
    return shutil.which("tailscale") is not None


def status() -> dict[str, Any]:
    if not is_installed():
        return {"installed": False, "backend": "none"}
    try:
        proc = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        if proc.returncode != 0:
            return {"installed": True, "error": (proc.stderr or proc.stdout or "").strip()}
        data = json.loads(proc.stdout or "{}")
        self_node = data.get("Self") or {}
        return {
            "installed": True,
            "backend": data.get("BackendState"),
            "hostname": self_node.get("HostName"),
            "dns_name": self_node.get("DNSName"),
            "ips": self_node.get("TailscaleIPs") or [],
            "online": self_node.get("Online"),
            "raw_summary": _brief(data),
        }
    except Exception as exc:  # noqa: BLE001
        return {"installed": True, "error": str(exc)}


def _brief(data: dict[str, Any]) -> str:
    self_node = data.get("Self") or {}
    ips = ", ".join(self_node.get("TailscaleIPs") or [])
    return f"{data.get('BackendState', '?')} {self_node.get('HostName', '')} {ips}".strip()


def up(auth_key: str, hostname: str | None = None, ssh: bool = True) -> tuple[int, str]:
    from radiotak.platform import get_platform

    args = ["tailscale", "up", f"--auth-key={auth_key}", "--accept-routes=false"]
    if hostname:
        args.append(f"--hostname={hostname}")
    if ssh:
        args.append("--ssh")
    # Never log the auth key — strip for return
    code, out = get_platform().run_priv(*args)
    redacted = out.replace(auth_key, "***")
    return code, redacted


def down() -> tuple[int, str]:
    from radiotak.platform import get_platform

    return get_platform().run_priv("tailscale", "down")


def install() -> tuple[int, str]:
    from radiotak.platform import get_platform

    return get_platform().run_priv("install-tailscale")
