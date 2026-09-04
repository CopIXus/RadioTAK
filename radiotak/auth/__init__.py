"""Authentication: Argon2id passwords, signed sessions, CSRF, rate limiting."""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from radiotak.config import Settings, get_settings

_ph = PasswordHasher()
_attempts: dict[str, list[float]] = {}


@dataclass
class AuthRecord:
    username: str
    password_hash: str
    created_at: str


def _auth_path(settings: Settings | None = None) -> Path:
    return (settings or get_settings()).auth_path


def load_auth(settings: Settings | None = None) -> AuthRecord | None:
    path = _auth_path(settings)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return AuthRecord(
        username=data["username"],
        password_hash=data["password_hash"],
        created_at=data.get("created_at", ""),
    )


def save_auth(username: str, password: str, settings: Settings | None = None) -> AuthRecord:
    settings = settings or get_settings()
    settings.ensure_dirs()
    record = AuthRecord(
        username=username.strip(),
        password_hash=_ph.hash(password),
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    path = settings.auth_path
    path.write_text(
        json.dumps(
            {
                "username": record.username,
                "password_hash": record.password_hash,
                "created_at": record.created_at,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return record


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def needs_setup(settings: Settings | None = None) -> bool:
    return load_auth(settings) is None


def serializer(settings: Settings | None = None) -> URLSafeTimedSerializer:
    settings = settings or get_settings()
    secret = settings.secret_key or _ensure_secret_key(settings)
    return URLSafeTimedSerializer(secret, salt="radiotak-session")


def _ensure_secret_key(settings: Settings) -> str:
    from radiotak.services.settings_store import load_settings_file, save_settings_file

    data = load_settings_file(settings)
    if not data.get("secret_key"):
        data["secret_key"] = secrets.token_urlsafe(48)
        save_settings_file(data, settings)
    return data["secret_key"]


def create_session_token(username: str, settings: Settings | None = None) -> str:
    return serializer(settings).dumps({"u": username, "csrf": secrets.token_urlsafe(24)})


def decode_session_token(token: str, settings: Settings | None = None) -> dict | None:
    settings = settings or get_settings()
    try:
        return serializer(settings).loads(token, max_age=settings.session_max_age)
    except (BadSignature, SignatureExpired):
        return None


def check_rate_limit(ip: str, settings: Settings | None = None) -> bool:
    """Return True if login is allowed."""
    settings = settings or get_settings()
    now = time.time()
    window = settings.login_window_seconds
    bucket = [t for t in _attempts.get(ip, []) if now - t < window]
    _attempts[ip] = bucket
    return len(bucket) < settings.login_max_attempts


def record_failed_login(ip: str) -> None:
    _attempts.setdefault(ip, []).append(time.time())


def clear_failed_logins(ip: str) -> None:
    _attempts.pop(ip, None)
