"""RadioTAK FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from radiotak.config import get_settings
from radiotak.db import init_db
from radiotak.gateway.events import event_bus
from radiotak.gateway.pipeline import pipeline
from radiotak.services.hearing import hearing_gauges
from radiotak.services.logging_setup import setup_logging
from radiotak.services.modules import load_module_routers, upgrade_decoder_on_startup
from radiotak.services.settings_store import load_settings_file
from radiotak.web.routers import api, pages

log = logging.getLogger("radiotak.main")


async def _ndjson_listen() -> None:
    try:
        from modules.sdr_location_gateway.sdrtrunk.adapter import listen_ndjson_tcp

        await listen_ndjson_tcp()
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("NDJSON listen failed: %s", exc)


async def _spectrum_listen() -> None:
    try:
        from modules.sdr_location_gateway.sdrtrunk.spectrum import listen_spectrum_tcp

        await listen_spectrum_tcp()
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("spectrum listen failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    setup_logging()
    init_db()
    try:
        from radiotak.services.updater import reconcile_update_state_on_startup

        reconcile_update_state_on_startup()
    except Exception as exc:  # noqa: BLE001
        log.warning("update-state reconcile failed: %s", exc)

    def _on_pipeline(event: dict) -> None:
        event_bus.publish(event)
        if event.get("type") in ("queued", "blocked", "encrypted", "heard"):
            hearing_gauges.note()

    pipeline.add_listener(_on_pipeline)

    async def retention_loop():
        from radiotak.services.retention import purge_old_records

        while True:
            await asyncio.sleep(6 * 3600)
            try:
                purge_old_records()
            except Exception as exc:  # noqa: BLE001
                log.warning("retention purge failed: %s", exc)

    task = asyncio.create_task(retention_loop())
    ndjson_task = asyncio.create_task(_ndjson_listen())
    spectrum_task = asyncio.create_task(_spectrum_listen())

    # Keep the SDRTrunk fork build in step with this RadioTAK checkout.
    try:
        upgrade_decoder_on_startup()
    except Exception as exc:  # noqa: BLE001
        log.warning("decoder upgrade scheduling failed: %s", exc)

    try:
        from radiotak.services import tak_runtime

        await tak_runtime.start_all()
    except Exception as exc:  # noqa: BLE001
        log.warning("TAK auto-connect failed: %s", exc)

    yield

    try:
        from radiotak.services import tak_runtime

        await tak_runtime.stop_all()
    except Exception as exc:  # noqa: BLE001
        log.warning("TAK shutdown failed: %s", exc)

    for t in (ndjson_task, spectrum_task, task):
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001
            pass


def create_app() -> FastAPI:
    app = FastAPI(title="RadioTAK", lifespan=lifespan, docs_url=None, redoc_url=None)

    static_dir = Path(__file__).parent / "web" / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(pages)
    app.include_router(api)

    for router in load_module_routers():
        app.include_router(router)

    @app.exception_handler(StarletteHTTPException)
    async def http_exc_handler(request: Request, exc: StarletteHTTPException):
        if exc.status_code in (303, 307) and exc.headers and "Location" in exc.headers:
            return RedirectResponse(exc.headers["Location"], status_code=exc.status_code)
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        from fastapi.responses import JSONResponse, PlainTextResponse

        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        return PlainTextResponse(str(exc.detail), status_code=exc.status_code)

    return app


app = create_app()


def run() -> None:
    import uvicorn

    settings = get_settings()
    settings.ensure_dirs()
    cfg = load_settings_file()
    host = cfg.get("bind_host") or settings.host
    port = int(cfg.get("bind_port") or settings.port)
    ssl_cert = settings.cert_dir / "cert.pem"
    ssl_key = settings.cert_dir / "key.pem"
    kwargs = {
        "host": host,
        "port": port,
        "log_level": "info",
    }
    if settings.bind_https and ssl_cert.exists() and ssl_key.exists():
        kwargs["ssl_certfile"] = str(ssl_cert)
        kwargs["ssl_keyfile"] = str(ssl_key)
    elif settings.bind_https:
        _ensure_dev_cert(ssl_cert, ssl_key)
        if ssl_cert.exists():
            kwargs["ssl_certfile"] = str(ssl_cert)
            kwargs["ssl_keyfile"] = str(ssl_key)
    uvicorn.run("radiotak.main:app", **kwargs, reload=False)


def _ensure_dev_cert(cert_path: Path, key_path: Path) -> None:
    if cert_path.exists() and key_path.exists():
        return
    try:
        from datetime import datetime, timedelta, timezone

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "RadioTAK")])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(timezone.utc))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
            .sign(key, hashes.SHA256())
        )
        cert_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    except Exception as exc:  # noqa: BLE001
        log.warning("dev cert generation failed: %s", exc)


if __name__ == "__main__":
    run()
