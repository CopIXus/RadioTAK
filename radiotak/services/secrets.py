"""SecretStore — filesystem-backed secrets under /var/lib/radiotak/secrets."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from radiotak.config import Settings, get_settings


class SecretStore:
    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_dirs()

    def path_for(self, name: str) -> Path:
        safe = name.replace("..", "").replace("/", "_").replace("\\", "_")
        return self.settings.secrets_dir / safe

    def write_text(self, name: str, content: str) -> Path:
        path = self.path_for(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self._chmod(path)
        return path

    def write_bytes(self, name: str, content: bytes) -> Path:
        path = self.path_for(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        self._chmod(path)
        return path

    def read_text(self, name: str) -> Optional[str]:
        path = self.path_for(name)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def read_bytes(self, name: str) -> Optional[bytes]:
        path = self.path_for(name)
        if not path.exists():
            return None
        return path.read_bytes()

    def delete(self, name: str) -> None:
        path = self.path_for(name)
        if path.exists():
            path.unlink()

    def exists(self, name: str) -> bool:
        return self.path_for(name).exists()

    @staticmethod
    def _chmod(path: Path) -> None:
        try:
            if os.name != "nt":
                os.chmod(path, 0o600)
                os.chmod(path.parent, 0o700)
        except OSError:
            pass
