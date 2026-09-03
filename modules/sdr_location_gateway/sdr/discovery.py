"""USB SDR discovery helpers."""

from __future__ import annotations

from typing import Any

from radiotak.platform import get_platform


def discover() -> list[dict[str, Any]]:
    return get_platform().list_sdr_devices()
