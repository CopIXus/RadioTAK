"""Hearing / decoder activity gauges (no FFT required)."""

from __future__ import annotations

import time
from collections import deque
from typing import Any

from radiotak.platform import get_platform


class HearingGauges:
    def __init__(self, window_s: float = 60.0) -> None:
        self.window_s = window_s
        self._events: deque[float] = deque()
        self.last_event_at: float | None = None

    def note(self) -> None:
        now = time.time()
        self.last_event_at = now
        self._events.append(now)
        self._trim(now)

    def _trim(self, now: float | None = None) -> None:
        now = now or time.time()
        cutoff = now - self.window_s
        while self._events and self._events[0] < cutoff:
            self._events.popleft()

    def messages_per_min(self) -> float:
        self._trim()
        return round(len(self._events) * (60.0 / self.window_s), 1)

    def last_event_age_s(self) -> float | None:
        if self.last_event_at is None:
            return None
        return round(time.time() - self.last_event_at, 1)

    def snapshot(self) -> dict[str, Any]:
        decoder_on = False
        try:
            decoder_on = bool(get_platform().service_active("sdrtrunk"))
        except Exception:  # noqa: BLE001
            decoder_on = False
        age = self.last_event_age_s()
        mpm = self.messages_per_min()
        # Lock proxy: decoder running and heard something recently
        if decoder_on and age is not None and age < 30:
            lock = "locked"
            lock_class = "ok"
        elif decoder_on and age is not None and age < 120:
            lock = "intermittent"
            lock_class = "warn"
        elif decoder_on:
            lock = "listening"
            lock_class = "warn"
        else:
            lock = "idle"
            lock_class = ""
        return {
            "messages_per_min": mpm,
            "last_event_age_s": age,
            "decoder_running": decoder_on,
            "cc_lock": lock,
            "cc_lock_class": lock_class,
            "gauge_mpm_class": "ok" if mpm > 0 else ("warn" if decoder_on else ""),
            "gauge_age_class": (
                "ok"
                if age is not None and age < 30
                else ("warn" if age is not None and age < 120 else ("bad" if decoder_on else ""))
            ),
        }


hearing_gauges = HearingGauges()
