"""Structured JSON logging with retention."""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from typing import Any, Optional

from radiotak.config import get_settings
from radiotak.services.settings_store import load_settings_file


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "component": getattr(record, "component", record.name),
            "event": getattr(record, "event", record.getMessage()),
        }
        for key in (
            "protocol",
            "system",
            "radio_id",
            "callsign",
            "tak_server",
            "latency_ms",
            "detail",
        ):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        settings = load_settings_file()
        if settings.get("privacy_mode"):
            for field in ("radio_id",):
                if field in payload and payload[field]:
                    payload[field] = hashlib.sha256(str(payload[field]).encode()).hexdigest()[:12]
            if "latitude" in payload:
                payload.pop("latitude", None)
            if "longitude" in payload:
                payload.pop("longitude", None)
        return json.dumps(payload, default=str)


def setup_logging() -> logging.Logger:
    settings = get_settings()
    settings.ensure_dirs()
    logger = logging.getLogger("radiotak")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = JsonFormatter()
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    logger.addHandler(stream)

    file_handler = TimedRotatingFileHandler(
        settings.logs_dir / "radiotak.jsonl",
        when="midnight",
        backupCount=int(load_settings_file().get("log_retention_days", 14)),
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)
    return logger


def get_logger(name: str = "radiotak") -> logging.Logger:
    return logging.getLogger(name)


def log_event(component: str, event: str, level: int = logging.INFO, **kwargs: Any) -> None:
    logger = get_logger()
    extra = {"component": component, "event": event, **kwargs}
    logger.log(level, event, extra=extra)
