"""Git-based updater and date-stamped versioning."""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from radiotak import __version__
from radiotak.config import get_settings
from radiotak.services.settings_store import load_settings_file

_STAMP_RE = re.compile(r"^\d{2}\.\d{4}\.\d{4}$")
_update_cache: dict[str, Any] = {"ts": 0.0, "payload": None}
_UPDATE_CACHE_SECONDS = 120.0
_LOG_CAP_CHARS = 80_000
_job_lock = threading.Lock()
_job_thread: threading.Thread | None = None

EmitFn = Callable[[str], None]


def parse_version_stamp(value: str | None) -> tuple[int, int, int] | None:
    """Parse YY.MMDD.HHMM into a comparable tuple, or None if not a stamp."""
    raw = (value or "").strip()
    if not _STAMP_RE.match(raw):
        return None
    yy, mmdd, hhmm = raw.split(".")
    return int(yy), int(mmdd), int(hhmm)


def version_is_newer(candidate: str | None, baseline: str | None) -> bool:
    """True when candidate is a strictly newer YY.MMDD.HHMM stamp than baseline."""
    ca = parse_version_stamp(candidate)
    ba = parse_version_stamp(baseline)
    if ca is None or ba is None:
        return False
    return ca > ba


def stamp_from_iso(date_s: str | None) -> str | None:
    """Convert an ISO-8601 timestamp (git %cI or GitHub API) to YY.MMDD.HHMM UTC."""
    raw = (date_s or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    stamp = dt.astimezone(UTC).strftime("%y.%m%d.%H%M")
    return stamp if _STAMP_RE.match(stamp) else None


def compute_update_available(
    *,
    installed: str | None,
    latest: str | None,
    local_sha: str | None,
    remote_sha: str | None,
    remote_ahead_by: int | None = None,
) -> bool:
    """GitHub has a newer build only when it is actually ahead of this install."""
    if local_sha and remote_sha and local_sha.lower() == remote_sha.lower():
        return False
    if remote_ahead_by is not None:
        return remote_ahead_by > 0
    return version_is_newer(latest, installed)


def _git(install: Path, *args: str) -> tuple[int, str]:
    cmd = ["git", "-c", f"safe.directory={install}", *args]
    proc = subprocess.run(cmd, cwd=str(install), capture_output=True, text=True, check=False)
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode, out


def version_stamp_now() -> str:
    """Wall-clock YY.MMDD.HHMM in UTC."""
    return datetime.now(UTC).strftime("%y.%m%d.%H%M")


def version_stamp_from_git(install: Path | None = None) -> str | None:
    """Return YY.MMDD.HHMM (UTC) from HEAD committer date, or None."""
    settings = get_settings()
    root = install or settings.install_dir
    code, out = _git(root, "log", "-1", "--format=%cI")
    if code != 0:
        return None
    iso = out.splitlines()[0].strip() if out else ""
    return stamp_from_iso(iso)


def write_version_stamp(install: Path | None = None, *, use_now: bool = False) -> str:
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


def local_commit_sha() -> str | None:
    settings = get_settings()
    code, out = _git(settings.install_dir, "rev-parse", "HEAD")
    if code != 0:
        return None
    sha = out.splitlines()[0].strip() if out else ""
    return sha or None


async def latest_release(repo: str | None = None) -> dict[str, Any]:
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


async def remote_head(repo: str | None = None, branch: str | None = None) -> dict[str, Any]:
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
            date_s = (data.get("commit") or {}).get("committer", {}).get("date")
            stamp = stamp_from_iso(date_s)
        if not stamp:
            ver_url = f"https://raw.githubusercontent.com/{repo}/{branch}/VERSION"
            vre = await client.get(ver_url)
            if vre.status_code == 200:
                stamp = vre.text.strip() or None
        return {"sha": sha, "version": stamp, "html_url": html_url, "branch": branch, "repo": repo}


async def remote_ahead_by(repo: str, local_sha: str, remote_sha: str) -> int | None:
    """How many commits GitHub is ahead of local. None if compare is unavailable."""
    url = f"https://api.github.com/repos/{repo}/compare/{local_sha}...{remote_sha}"
    headers = {"Accept": "application/vnd.github+json"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            return None
        ahead = resp.json().get("ahead_by")
        return int(ahead) if ahead is not None else None
    except (httpx.HTTPError, TypeError, ValueError):
        return None


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
        remote_sha = remote.get("sha")
        if local_sha and remote_sha and local_sha.lower() == remote_sha.lower():
            latest = installed
        payload["latest"] = latest
        ahead = None
        if remote_sha and local_sha and remote_sha.lower() != local_sha.lower():
            ahead = await remote_ahead_by(payload["repo"], local_sha, remote_sha)
        payload["update_available"] = compute_update_available(
            installed=installed,
            latest=latest,
            local_sha=local_sha,
            remote_sha=remote_sha,
            remote_ahead_by=ahead,
        )
    except Exception:  # noqa: BLE001
        pass

    _update_cache["ts"] = now
    _update_cache["payload"] = dict(payload)
    return payload


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _state_path() -> Path:
    return get_settings().data_dir / "update-state.json"


def _idle_state() -> dict[str, Any]:
    return {
        "state": "idle",
        "log": "",
        "started_at": None,
        "finished_at": None,
        "from_version": None,
        "to_version": None,
        "code": None,
        "error": None,
    }


def load_update_state() -> dict[str, Any]:
    path = _state_path()
    data = _idle_state()
    if not path.exists():
        return data
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            data.update(raw)
    except (OSError, json.JSONDecodeError):
        pass
    return data


def save_update_state(data: dict[str, Any]) -> None:
    path = _state_path()
    payload = _idle_state()
    payload.update(data)
    log = payload.get("log") or ""
    if len(log) > _LOG_CAP_CHARS:
        payload["log"] = log[-_LOG_CAP_CHARS:]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def reconcile_update_state_on_startup() -> None:
    """Mark a restarting update as finished once the new process is up."""
    data = load_update_state()
    state = data.get("state")
    if state == "restarting":
        data["state"] = "done"
        data["code"] = 0
        data["to_version"] = current_version()
        data["finished_at"] = _now_iso()
        data["log"] = (data.get("log") or "") + (
            f"\nConsole is back. Version {data['to_version']}.\n"
        )
        save_update_state(data)
    elif state == "running":
        data["state"] = "failed"
        data["code"] = 1
        data["error"] = "Update interrupted before restart completed."
        data["finished_at"] = _now_iso()
        data["log"] = (data.get("log") or "") + (
            "\nUpdate interrupted (service restarted or crashed).\n"
        )
        save_update_state(data)


def _append_log(line: str) -> None:
    data = load_update_state()
    log = data.get("log") or ""
    if log and not log.endswith("\n"):
        log += "\n"
    log += line if line.endswith("\n") else line + "\n"
    data["log"] = log
    save_update_state(data)


def _stream_cmd(
    cmd: list[str],
    cwd: Path,
    emit: EmitFn,
    env: dict[str, str] | None = None,
    timeout: int = 600,
) -> int:
    emit(f"$ {' '.join(cmd)}")
    merged = os.environ.copy()
    if env:
        merged.update(env)
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=merged,
        )
    except OSError as exc:
        emit(str(exc))
        return 1
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            emit(line.rstrip("\n"))
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        emit("command timed out")
        return 1
    except Exception as exc:  # noqa: BLE001
        emit(str(exc))
        return 1


def _git_fetch_local(install: Path, repo: str, branch: str, emit: EmitFn) -> int:
    remote = f"https://github.com/{repo}.git"
    git = ["git", "-c", f"safe.directory={install}"]
    env = {"GIT_TERMINAL_PROMPT": "0"}
    if _stream_cmd([*git, "fetch", "--progress", remote, branch], install, emit, env=env) != 0:
        return 1
    return _stream_cmd(
        [*git, "checkout", "--force", "-B", branch, "FETCH_HEAD"],
        install,
        emit,
        env=env,
    )


def _git_fetch(install: Path, repo: str, branch: str, emit: EmitFn) -> int:
    """Pull via radiotak-priv when possible so root-owned .git/objects get repaired."""
    from radiotak.platform import get_platform

    plat = get_platform()
    if plat.__class__.__name__ == "LinuxPlatform":
        captured: list[str] = []

        def priv_emit(line: str) -> None:
            captured.append(line)
            emit(line)

        emit("Repairing repository permissions, then fetching from GitHub…")
        code = plat.run_priv_stream("git-update", branch, repo, on_line=priv_emit)
        blob = "\n".join(captured)
        if code == 0:
            return 0
        if "unknown command" in blob:
            emit(
                "Privilege helper is older than this build — "
                "repairing ownership, then fetching locally."
            )
            plat.run_priv_stream("fix-git", on_line=emit)
        else:
            emit("Privileged git-update failed — trying a local fetch after ownership repair.")
            plat.run_priv_stream("fix-git", on_line=emit)
    return _git_fetch_local(install, repo, branch, emit)


def update_now(branch: str | None = None, on_line: EmitFn | None = None) -> tuple[int, str]:
    settings = get_settings()
    data = load_settings_file()
    branch = branch or data.get("github_branch") or settings.github_branch
    repo = settings.github_repo
    install = settings.install_dir
    lines: list[str] = []

    def emit(msg: str) -> None:
        text = msg.rstrip("\n")
        lines.append(text)
        if on_line:
            on_line(text)

    if _git_fetch(install, repo, branch, emit) != 0:
        emit(
            "Git fetch failed. If you see 'insufficient permission' for .git/objects, "
            "SSH in and run: sudo radiotak update"
        )
        return 1, "\n".join(lines) + "\n"

    try:
        stamp = write_version_stamp(install)
        emit(f"VERSION stamped: {stamp}")
    except OSError as exc:
        emit(f"VERSION stamp failed: {exc}")

    venv_pip = install / ".venv" / "bin" / "pip"
    if not venv_pip.exists():
        venv_pip = install / ".venv" / "Scripts" / "pip.exe"
    pip_cmd = [str(venv_pip)] if venv_pip.exists() else ["pip"]
    emit("Installing Python dependencies…")
    _stream_cmd([*pip_cmd, "install", "-r", "requirements.txt"], install, emit)
    if (install / "pyproject.toml").exists() or (install / "setup.py").exists():
        _stream_cmd([*pip_cmd, "install", "-e", str(install)], install, emit)

    from radiotak.platform import get_platform

    try:
        from radiotak.services import modules as modules_svc

        if modules_svc.is_installed(modules_svc.SDR_MODULE_ID):
            if modules_svc.decoder_upgrade_needed():
                emit("Upgrading SDRTrunk decoder (this may take several minutes)…")
                code, out = modules_svc.install_module(modules_svc.SDR_MODULE_ID)
                for line in (out or "").splitlines()[-12:]:
                    emit(line)
                emit(f"SDRTrunk decoder upgrade: exit {code}")
            else:
                emit("SDRTrunk decoder build already current")
    except Exception as exc:  # noqa: BLE001
        emit(f"decoder upgrade skipped: {exc}")

    emit("Restarting RadioTAK — the console will go offline for a short time.")
    _update_cache["ts"] = 0.0
    _update_cache["payload"] = None
    code, out = get_platform().service_action("radiotak", "restart")
    if out:
        emit(out)
    return code, "\n".join(lines) + "\n"


def _run_update_job() -> None:
    from_version = current_version()
    try:
        save_update_state(
            {
                "state": "running",
                "log": f"Starting update from {from_version}…\n",
                "started_at": _now_iso(),
                "finished_at": None,
                "from_version": from_version,
                "to_version": None,
                "code": None,
                "error": None,
            }
        )

        def on_line(msg: str) -> None:
            _append_log(msg)

        code, _out = update_now(on_line=on_line)
        data = load_update_state()
        if code == 0:
            from radiotak.platform import get_platform

            data = load_update_state()
            if get_platform().__class__.__name__ == "DevPlatform":
                data["state"] = "done"
                data["code"] = 0
                data["to_version"] = current_version()
                data["finished_at"] = _now_iso()
                data["log"] = (data.get("log") or "") + (
                    "\n[dev] restart skipped — update finished.\n"
                )
            else:
                data["state"] = "restarting"
                data["log"] = (data.get("log") or "") + "Waiting for console to come back…\n"
            save_update_state(data)
        else:
            data["state"] = "failed"
            data["code"] = code
            data["error"] = "Update command failed. See log."
            data["finished_at"] = _now_iso()
            save_update_state(data)
    except Exception as exc:  # noqa: BLE001
        data = load_update_state()
        data["state"] = "failed"
        data["code"] = 1
        data["error"] = str(exc)
        data["finished_at"] = _now_iso()
        data["log"] = (data.get("log") or "") + f"\n{exc}\n"
        save_update_state(data)


def start_update_job() -> dict[str, Any]:
    """Kick off a background update. Returns current state."""
    global _job_thread
    with _job_lock:
        if _job_thread and _job_thread.is_alive():
            return load_update_state()
        data = load_update_state()
        if data.get("state") in ("running", "restarting"):
            return data
        save_update_state(
            {
                "state": "running",
                "log": "Starting update…\n",
                "started_at": _now_iso(),
                "finished_at": None,
                "from_version": current_version(),
                "to_version": None,
                "code": None,
                "error": None,
            }
        )
        _job_thread = threading.Thread(target=_run_update_job, name="radiotak-update", daemon=True)
        _job_thread.start()
        return load_update_state()


def update_job_busy() -> bool:
    data = load_update_state()
    return data.get("state") in ("running", "restarting")


def update_status_payload() -> dict[str, Any]:
    state = load_update_state()
    return {
        "installed": current_version(),
        "branch": load_settings_file().get("github_branch", "main"),
        "repo": get_settings().github_repo,
        "update": {
            "state": state.get("state") or "idle",
            "log": state.get("log") or "",
            "started_at": state.get("started_at"),
            "finished_at": state.get("finished_at"),
            "from_version": state.get("from_version"),
            "to_version": state.get("to_version") or current_version(),
            "code": state.get("code"),
            "error": state.get("error"),
        },
    }
