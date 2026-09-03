"""Application configuration and data paths."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_data_dir() -> Path:
    override = os.environ.get("RADIOTAK_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        return Path.cwd() / ".data"
    return Path("/var/lib/radiotak")


def _default_install_dir() -> Path:
    override = os.environ.get("RADIOTAK_INSTALL_DIR")
    if override:
        return Path(override).expanduser().resolve()
    # Prefer /opt/radiotak on Pi; fall back to repo root for development.
    opt = Path("/opt/radiotak")
    if opt.is_dir() and (opt / "VERSION").exists():
        return opt
    return Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RADIOTAK_", extra="ignore")

    app_name: str = "RadioTAK"
    host: str = "0.0.0.0"
    port: int = 5001
    data_dir: Path = _default_data_dir()
    install_dir: Path = _default_install_dir()
    github_repo: str = "CopIXus/RadioTAK"
    github_branch: str = "main"
    session_cookie: str = "radiotak_session"
    session_max_age: int = 60 * 60 * 12
    login_max_attempts: int = 8
    login_window_seconds: int = 300
    bind_https: bool = True
    secret_key: str = ""  # generated into settings.json if empty
    log_retention_days: int = 14
    observation_retention_days: int = 7
    event_retention_days: int = 1
    audit_retention_days: int = 30
    max_log_mb: int = 200
    privacy_mode: bool = False
    theme: str = "dark"
    accent: str = "#06b6d4"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "radiotak.db"

    @property
    def auth_path(self) -> Path:
        return self.data_dir / "auth.json"

    @property
    def settings_path(self) -> Path:
        return self.data_dir / "settings.json"

    @property
    def secrets_dir(self) -> Path:
        return self.data_dir / "secrets"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def modules_state_dir(self) -> Path:
        return self.data_dir / "modules"

    @property
    def cert_dir(self) -> Path:
        return self.data_dir / "tls"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path.as_posix()}"

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.secrets_dir,
            self.logs_dir,
            self.modules_state_dir,
            self.cert_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        try:
            if os.name != "nt":
                os.chmod(self.secrets_dir, 0o700)
        except OSError:
            pass


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
