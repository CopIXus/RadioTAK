"""Git-based updater."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Optional

import httpx

from radiotak import __version__
from radiotak.config import get_settings
from radiotak.services.settings_store import load_settings_file


def current_version() -> str:
    settings = get_settings()
    version_file = settings.install_dir / "VERSION"
    if version_file.exists():
        return version_file.read_text(encoding="utf-8").strip()
    return __version__


async def latest_release(repo: Optional[str] = None) -> dict[str, Any]:
    settings = get_settings()
    repo = repo or settings.github_repo
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers={"Accept": "application/vnd.github+json"})
        if resp.status_code == 404:
            # no releases yet — compare to main VERSION raw
            raw = f"https://raw.githubusercontent.com/{repo}/main/VERSION"
            r2 = await client.get(raw)
            return {"tag_name": r2.text.strip() if r2.status_code == 200 else None, "html_url": None}
        resp.raise_for_status()
        return resp.json()


def update_now(branch: Optional[str] = None) -> tuple[int, str]:
    settings = get_settings()
    data = load_settings_file()
    branch = branch or data.get("github_branch") or settings.github_branch
    repo = settings.github_repo
    install = settings.install_dir
    lines: list[str] = []

    def run(cmd: list[str], cwd: Path | None = None) -> int:
        proc = subprocess.run(
            cmd, cwd=str(cwd or install), capture_output=True, text=True, check=False
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        lines.append(f"$ {' '.join(cmd)}\n{out}")
        return proc.returncode

    remote = f"https://github.com/{repo}.git"
    git = ["git", "-c", f"safe.directory={install}"]
    if run([*git, "fetch", remote, branch]) != 0:
        return 1, "\n".join(lines)
    if run([*git, "checkout", "--force", "-B", branch, "FETCH_HEAD"]) != 0:
        return 1, "\n".join(lines)

    venv_pip = install / ".venv" / "bin" / "pip"
    if not venv_pip.exists():
        venv_pip = install / ".venv" / "Scripts" / "pip.exe"
    if venv_pip.exists():
        run([str(venv_pip), "install", "-r", "requirements.txt"])
    else:
        run(["pip", "install", "-r", "requirements.txt"])

    # Restart via priv helper when available
    from radiotak.platform import get_platform

    code, out = get_platform().service_action("radiotak", "restart")
    lines.append(out)
    return code, "\n".join(lines)


def update_status_payload() -> dict[str, Any]:
    return {
        "installed": current_version(),
        "branch": load_settings_file().get("github_branch", "main"),
        "repo": get_settings().github_repo,
    }
