"""Normalized location event schema (Pydantic)."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, int | float):
        # treat as epoch ms if large
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=UTC)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(UTC)


class DecodeEventIn(BaseModel):
    """Inbound decoder call event — sdr2tak.decode.v1 (no GPS required)."""

    schema_name: str = Field(default="sdr2tak.decode.v1", alias="schema")
    event_id: str | None = None
    decoder: str = "sdrtrunk"
    protocol: str | None = None
    system_name: str | None = None
    system_id: str | None = None
    site_id: str | None = None
    nac: str | None = None
    wacn: str | None = None
    rfss: str | None = None
    frequency_hz: int | None = None
    channel: str | None = None
    timeslot: int | None = None
    p25_phase: str | None = None
    talkgroup: str | None = None
    radio_id: str
    source_alias: str | None = None
    destination_radio_id: str | None = None
    encrypted: bool = False
    algorithm_id: str | None = None
    algorithm_id_hex: str | None = None
    key_id: str | None = None
    message_indicator: str | None = None
    message_indicator_hex: str | None = None
    duration_ms: int | None = None
    key_loaded: bool = False
    emergency: bool = False
    observed_at: datetime
    raw_event_type: str | None = None
    details: str | None = None

    model_config = {"populate_by_name": True}

    @field_validator("radio_id")
    @classmethod
    def _radio(cls, v: str) -> str:
        text = str(v or "").strip()
        if not text:
            raise ValueError("radio_id is required")
        return text

    @field_validator(
        "talkgroup",
        "algorithm_id",
        "algorithm_id_hex",
        "key_id",
        "message_indicator",
        "message_indicator_hex",
        "system_id",
        "site_id",
        "nac",
        "wacn",
        "rfss",
        "channel",
        "p25_phase",
        "destination_radio_id",
        mode="before",
    )
    @classmethod
    def _stringify(cls, v: Any) -> str | None:
        if v is None or v == "":
            return None
        return str(v).strip()

    @field_validator("observed_at", mode="before")
    @classmethod
    def _obs(cls, v: Any) -> datetime:
        return _parse_dt(v)


class LocationEventIn(BaseModel):
    """Inbound decoder event — sdr2tak.location.v1."""

    schema_name: str = Field(default="sdr2tak.location.v1", alias="schema")
    event_id: str | None = None
    decoder: str = "sdrtrunk"
    protocol: str | None = None
    system_name: str | None = None
    system_id: str | None = None
    site_id: str | None = None
    nac: str | None = None
    wacn: str | None = None
    rfss: str | None = None
    frequency_hz: int | None = None
    channel: str | None = None
    timeslot: int | None = None
    p25_phase: str | None = None
    talkgroup: str | None = None
    radio_id: str
    source_alias: str | None = None
    latitude: float
    longitude: float
    altitude_m: float | None = None
    speed_mps: float | None = None
    heading_deg: float | None = None
    accuracy_m: float | None = None
    emergency: bool = False
    rssi_dbm: float | None = None
    observed_at: datetime
    raw_event_type: str | None = None

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
    def _heading(cls, v: float | None) -> float | None:
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


def stable_cot_uid(system_id: str | None, radio_id: str) -> str:
    system = (system_id or "UNK").replace(" ", "-")
    return f"RADIOTAK-{system}-{radio_id}"
