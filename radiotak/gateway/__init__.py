"""Normalized location event schema (Pydantic)."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        # treat as epoch ms if large
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(timezone.utc)


class LocationEventIn(BaseModel):
    """Inbound decoder event — sdr2tak.location.v1."""

    schema_name: str = Field(default="sdr2tak.location.v1", alias="schema")
    event_id: Optional[str] = None
    decoder: str = "sdrtrunk"
    protocol: Optional[str] = None
    system_name: Optional[str] = None
    system_id: Optional[str] = None
    site_id: Optional[str] = None
    nac: Optional[str] = None
    frequency_hz: Optional[int] = None
    talkgroup: Optional[str] = None
    radio_id: str
    source_alias: Optional[str] = None
    latitude: float
    longitude: float
    altitude_m: Optional[float] = None
    speed_mps: Optional[float] = None
    heading_deg: Optional[float] = None
    accuracy_m: Optional[float] = None
    emergency: bool = False
    rssi_dbm: Optional[float] = None
    observed_at: datetime
    raw_event_type: Optional[str] = None

    model_config = {"populate_by_name": True}

    @field_validator("latitude")
    @classmethod
    def _lat(cls, v: float) -> float:
        if not math.isfinite(v) or v < -90 or v > 90:
            raise ValueError("latitude out of range")
        return v

    @field_validator("longitude")
    @classmethod
    def _lon(cls, v: float) -> float:
        if not math.isfinite(v) or v < -180 or v > 180:
            raise ValueError("longitude out of range")
        return v

    @field_validator("heading_deg")
    @classmethod
    def _heading(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        if not math.isfinite(v) or v < 0 or v >= 360:
            raise ValueError("heading out of range")
        return v

    @field_validator("observed_at", mode="before")
    @classmethod
    def _obs(cls, v: Any) -> datetime:
        return _parse_dt(v)

    @model_validator(mode="after")
    def _no_null_island(self) -> LocationEventIn:
        # Do not silently accept missing coords as 0,0 — reject exact origin with no accuracy
        if abs(self.latitude) < 1e-9 and abs(self.longitude) < 1e-9:
            raise ValueError("coordinates look like null island (0,0)")
        return self


def stable_cot_uid(system_id: Optional[str], radio_id: str) -> str:
    system = (system_id or "UNK").replace(" ", "-")
    return f"RADIOTAK-{system}-{radio_id}"
