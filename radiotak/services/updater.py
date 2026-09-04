"""Git-based updater and date-stamped versioning."""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from radiotak import __version__
from radiotak.config import get_settings
from radiotak.services.settings_store import load_settings_file

_STAMP_RE = re.compile(r"^\d{2}\.\d{4}\.\d{4}$")
_update_cache: dict[str, Any] = {"ts": 0.0, "payload": None}
_UPDATE_CACHE_SECONDS = 120.0


def _git(install: Path, *args: str) -> tuple[int, str]:
    cmd = ["git", "-c", f"safe.directory={install}", *args]
    proc = subprocess.run(cmd, cwd=str(install), capture_output=True, text=True, check=False)
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode, out


def version_stamp_now() -> str:
    """Wall-clock YY.MMDD.HHMM in the local timezone."""
    from datetime import datetime

    return datetime.now().strftime("%y.%m%d.%H%M")


def version_stamp_from_git(install: Optional[Path] = None) -> Optional[str]:
    """Return YY.MMDD.HHMM from HEAD committer date, or None."""
    settings = get_settings()
    root = install or settings.install_dir
    code, out = _git(root, "log", "-1", "--format=%cd", "--date=format:%y.%m%d.%H%M")
    if code != 0:
        return None
    stamp = out.splitlines()[0].strip() if out else ""
    return stamp if _STAMP_RE.match(stamp) else None


def write_version_stamp(install: Optional[Path] = None, *, use_now: bool = False) -> str:
    """Write VERSION from HEAD commit time (or wall clock when use_now=True)."""
    settings = get_settings()
    root = install or settings.install_dir
    stamp = version_stamp_now() if use_now else version_stamp_from_git(root)
    path = root / "VERSION"
    if not stamp:
        stamp = path.read_text(encoding="utf-8").strip() if path.exists() else __version__
        if not _STAMP_RE.match(stamp):
            stamp = version_stamp_now()
    path.write_text(stamp + "\n", encoding="utf-8")
    return stamp


def current_version() -> str:
    settings = get_settings()
    version_file = settings.install_dir / "VERSION"
    if version_file.exists():
        raw = version_file.read_text(encoding="utf-8").strip()
        if raw and raw != "0.0.0":
            # Migrate legacy semver files to git stamp when possible.
            if not _STAMP_RE.match(raw):
                stamped = version_stamp_from_git(settings.install_dir)
                if stamped:
                    try:
                        version_file.write_text(stamped + "\n", encoding="utf-8")
                    except OSError:
                        pass
                    return stamped
            return raw
    stamped = version_stamp_from_git(settings.install_dir)
    if stamped:
        return stamped
    return __version__


def local_commit_sha() -> Optional[str]:
    settings = get_settings()
    code, out = _git(settings.install_dir, "rev-parse", "HEAD")
    if code != 0:
        return None
    sha = out.splitlines()[0].strip() if out else ""
    return sha or None


async def latest_release(repo: Optional[str] = None) -> dict[str, Any]:
    settings = get_settings()
    repo = repo or settings.github_repo
    branch = load_settings_file().get("github_branch") or settings.github_branch
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers={"Accept": "application/vnd.github+json"})
        if resp.status_code == 404:
            raw = f"https://raw.githubusercontent.com/{repo}/{branch}/VERSION"
            r2 = await client.get(raw)
            tag = r2.text.strip() if r2.status_code == 200 else None
            return {
                "tag_name": tag,
                "html_url": f"https://github.com/{repo}/tree/{branch}",
                "target_commitish": branch,
            }
        resp.raise_for_status()
        return resp.json()


async def remote_head(repo: Optional[str] = None, branch: Optional[str] = None) -> dict[str, Any]:
    """Resolve remote branch tip SHA and VERSION stamp."""
    settings = get_settings()
    repo = repo or settings.github_repo
    branch = branch or load_settings_file().get("github_branch") or settings.github_branch
    headers = {"Accept": "application/vnd.github+json"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        commit_url = f"https://api.github.com/repos/{repo}/commits/{branch}"
        cre = await client.get(commit_url, headers=headers)
        sha = None
        stamp = None
        html_url = f"https://github.com/{repo}/tree/{branch}"
        if cre.status_code == 200:
            data = cre.json()
            sha = data.get("sha")
            html_url = data.get("html_url") or html_url
            # Prefer committer date → YY.MMDD.HHMM in UTC-less local wall clock of commit.
            date_s = (data.get("commit") or {}).get("committer", {}).get("date")
            if date_s:
                # 2026-09-04T12:27:00Z → convert via git-style local isn't available; use VERSION file.
                pass
        ver_url = f"https://raw.githubusercontent.com/{repo}/{branch}/VERSION"
        vre = await client.get(ver_url)
        if vre.status_code == 200:
            stamp = vre.text.strip() or None
        if not stamp and sha:
            # Fallback: abbreviated date from API commit if VERSION missing.
            date_s = (cre.json().get("commit") or {}).get("committer", {}).get("date") if cre.status_code == 200 else None
            if date_s and len(date_s) >= 16:
                # YYYY-MM-DDTHH:MM → YY.MMDD.HHMM (UTC)
                stamp = f"{date_s[2:4]}.{date_s[5:7]}{date_s[8:10]}.{date_s[11:13]}{date_s[14:16]}"
        return {"sha": sha, "version": stamp, "html_url": html_url, "branch": branch, "repo": repo}


async def check_for_update(force: bool = False) -> dict[str, Any]:
    now = time.monotonic()
    if (
        not force
        and _update_cache["payload"] is not None
        and (now - float(_update_cache["ts"])) < _UPDATE_CACHE_SECONDS
    ):
        return dict(_update_cache["payload"])

    installed = current_version()
    local_sha = local_commit_sha()
    payload: dict[str, Any] = {
        "installed": installed,
        "latest": installed,
        "update_available": False,
        "local_sha": local_sha,
        "remote_sha": None,
        "html_url": None,
        "branch": load_settings_file().get("github_branch", get_settings().github_branch),
        "repo": get_settings().github_repo,
    }
    try:
        remote = await remote_head()
        payload["remote_sha"] = remote.get("sha")
        payload["html_url"] = remote.get("html_url")
        latest = remote.get("version") or installed
        payload["latest"] = latest
        remote_sha = remote.get("sha")
        if remote_sha and local_sha and remote_sha.lower() != local_sha.lower():
            payload["update_available"] = True
        elif latest and installed and latest != installed:
            # VERSION differs even if SHA compare unavailable
            payload["update_available"] = True
    except Exception:  # noqa: BLE001
        pass

    _update_cache["ts"] = now
    _update_cache["payload"] = dict(payload)
    return payload


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

    try:
        stamp = write_version_stamp(install)
        lines.append(f"VERSION stamped: {stamp}\n")
    except OSError as exc:
        lines.append(f"VERSION stamp failed: {exc}\n")

    venv_pip = install / ".venv" / "bin" / "pip"
    if not venv_pip.exists():
        venv_pip = install / ".venv" / "Scripts" / "pip.exe"
    if venv_pip.exists():
        run([str(venv_pip), "install", "-r", "requirements.txt"])
    else:
        run(["pip", "install", "-r", "requirements.txt"])

    from radiotak.platform import get_platform

    code, out = get_platform().service_action("radiotak", "restart")
    lines.append(out)
    _update_cache["ts"] = 0.0
    _update_cache["payload"] = None
    return code, "\n".join(lines)


def update_status_payload() -> dict[str, Any]:
    return {
        "installed": current_version(),
        "branch": load_settings_file().get("github_branch", "main"),
        "repo": get_settings().github_repo,
    }
