"""SQLAlchemy models and engine."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from radiotak.config import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class ForwardingStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    BLOCKED = "blocked"
    DROPPED = "dropped"
    ERROR = "error"


class TakConnectionStatus(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    CERTIFICATE_ERROR = "certificate_error"
    AUTH_ERROR = "auth_error"
    DNS_ERROR = "dns_error"
    TLS_ERROR = "tls_error"


class LocationObservation(Base):
    __tablename__ = "location_observations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    source: Mapped[str] = mapped_column(String(64), default="decoder")
    decoder: Mapped[str] = mapped_column(String(64), default="sdrtrunk")
    protocol: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    system_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    system_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    site_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    frequency_hz: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    channel: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    talkgroup_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    radio_id: Mapped[str] = mapped_column(String(64), index=True)
    radio_alias: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    altitude_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    speed_mps: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    heading_deg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    accuracy_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    emergency: Mapped[bool] = mapped_column(Boolean, default=False)
    signal_quality: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    raw_event_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    raw_payload_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    forwarding_status: Mapped[str] = mapped_column(
        String(32), default=ForwardingStatus.PENDING.value, index=True
    )
    forwarding_reason: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    tak_server_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    cot_uid: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)


class RadioIdentity(Base):
    __tablename__ = "radio_identities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    radio_id: Mapped[str] = mapped_column(String(64), index=True)
    system_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    forward_to_tak: Mapped[bool] = mapped_column(Boolean, default=False)
    callsign: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    agency: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    cot_type: Mapped[str] = mapped_column(String(64), default="a-n-G")
    team: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    role: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    stale_seconds: Mapped[int] = mapped_column(Integer, default=0)
    remarks: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_observed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    observation_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TakServer(Base):
    __tablename__ = "tak_servers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    host: Mapped[str] = mapped_column(String(255))
    cot_port: Mapped[int] = mapped_column(Integer, default=8089)
    enrollment_port: Mapped[int] = mapped_column(Integer, default=8446)
    api_port: Mapped[int] = mapped_column(Integer, default=8443)
    connection_mode: Mapped[str] = mapped_column(String(32), default="tls")
    tls_verify: Mapped[bool] = mapped_column(Boolean, default=True)
    server_ca_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # Passwords / key material stored via SecretStore references, never plaintext in API
    credential_secret_ref: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    client_cert_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    client_key_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    client_key_password_ref: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    pkcs12_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    pkcs12_password_ref: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    callsign: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    device_uid: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # Marker / CoT appearance (per TAK server)
    default_callsign: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, default="Radio")
    cot_type_default: Mapped[str] = mapped_column(String(64), default="a-n-G")
    iconset_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    marker_color: Mapped[str] = mapped_column(String(16), default="#06b6d4")
    cot_how: Mapped[str] = mapped_column(String(32), default="m-g")
    default_ce_feet: Mapped[float] = mapped_column(Float, default=2000.0)
    presence_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    presence_lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    auto_connect: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_reconnect: Mapped[bool] = mapped_column(Boolean, default=True)
    reconnect_min_seconds: Mapped[int] = mapped_column(Integer, default=2)
    reconnect_max_seconds: Mapped[int] = mapped_column(Integer, default=60)
    active_groups: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=TakConnectionStatus.DISCONNECTED.value)
    last_connected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    certificate_subject: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    certificate_issuer: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    certificate_not_before: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    certificate_not_after: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    certificate_fingerprint: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SdrDevice(Base):
    __tablename__ = "sdr_devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    driver: Mapped[str] = mapped_column(String(64), default="rtl")
    serial_number: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    usb_path: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    sample_rate: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    center_frequency_hz: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    gain_mode: Mapped[str] = mapped_column(String(32), default="auto")
    gain: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ppm_correction: Mapped[float] = mapped_column(Float, default=0.0)
    bias_tee: Mapped[bool] = mapped_column(Boolean, default=False)
    preferred_decoder: Mapped[str] = mapped_column(String(64), default="sdrtrunk")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class RadioSystem(Base):
    __tablename__ = "radio_systems"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    protocol: Mapped[str] = mapped_column(String(32), default="P25")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decoder: Mapped[str] = mapped_column(String(64), default="sdrtrunk")
    sdr_device_ids: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    location_forwarding_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ForwardingEvent(Base):
    __tablename__ = "forwarding_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    observation_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("location_observations.id"), nullable=True
    )
    tak_server_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32))
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    actor: Mapped[str] = mapped_column(String(128), default="system")
    action: Mapped[str] = mapped_column(String(128))
    target: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    detail: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


_engine = None
_SessionLocal = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        settings.ensure_dirs()
        _engine = create_engine(
            settings.database_url,
            connect_args={"check_same_thread": False},
            future=True,
        )

        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record):  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    return _engine


def get_session_factory():
    get_engine()
    return _SessionLocal


def init_db() -> None:
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    _sqlite_add_missing_columns(engine)


def _sqlite_add_missing_columns(engine) -> None:
    """Best-effort ALTER TABLE for new columns on existing SQLite DBs."""
    statements = [
        "ALTER TABLE tak_servers ADD COLUMN default_callsign VARCHAR(128) DEFAULT 'Radio'",
        "ALTER TABLE tak_servers ADD COLUMN cot_type_default VARCHAR(64) DEFAULT 'a-n-G'",
        "ALTER TABLE tak_servers ADD COLUMN iconset_path VARCHAR(512)",
        "ALTER TABLE tak_servers ADD COLUMN marker_color VARCHAR(16) DEFAULT '#06b6d4'",
        "ALTER TABLE tak_servers ADD COLUMN cot_how VARCHAR(32) DEFAULT 'm-g'",
        "ALTER TABLE tak_servers ADD COLUMN default_ce_feet FLOAT DEFAULT 2000",
        "ALTER TABLE audit_log ADD COLUMN target VARCHAR(256)",
    ]
    with engine.begin() as conn:
        for sql in statements:
            try:
                conn.exec_driver_sql(sql)
            except Exception:  # noqa: BLE001
                pass
        presence_added = False
        try:
            conn.exec_driver_sql("ALTER TABLE tak_servers ADD COLUMN presence_lat FLOAT")
            presence_added = True
        except Exception:  # noqa: BLE001
            pass
        try:
            conn.exec_driver_sql("ALTER TABLE tak_servers ADD COLUMN presence_lon FLOAT")
        except Exception:  # noqa: BLE001
            pass
        if presence_added:
            for sql in (
                "UPDATE tak_servers SET cot_type_default = 'a-n-G' WHERE cot_type_default = 'a-f-G-U-C'",
                "UPDATE radio_identities SET cot_type = 'a-n-G' WHERE cot_type = 'a-f-G-U-C'",
                "UPDATE radio_identities SET stale_seconds = 0 WHERE stale_seconds = 120",
            ):
                try:
                    conn.exec_driver_sql(sql)
                except Exception:  # noqa: BLE001
                    pass


def get_db():
    Session = get_session_factory()
    db = Session()
    try:
        yield db
    finally:
        db.close()
