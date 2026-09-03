"""RadioTAK FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
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
from radiotak.services.logging_setup import setup_logging
from radiotak.services.modules import load_module_routers
from radiotak.web.routers import api, pages


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    setup_logging()
    init_db()

    def _on_pipeline(event: dict) -> None:
        event_bus.publish(event)

    pipeline.add_listener(_on_pipeline)

    # Periodic retention (daily-ish via 6h loop)
    async def retention_loop():
        from radiotak.services.retention import purge_old_records

        while True:
            await asyncio.sleep(6 * 3600)
            try:
                purge_old_records()
            except Exception:  # noqa: BLE001
                pass

    task = asyncio.create_task(retention_loop())
    yield
    task.cancel()


def create_app() -> FastAPI:
    settings = get_settings()
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
    ssl_cert = settings.cert_dir / "cert.pem"
    ssl_key = settings.cert_dir / "key.pem"
    kwargs = {
        "host": settings.host,
        "port": settings.port,
        "log_level": "info",
    }
    if settings.bind_https and ssl_cert.exists() and ssl_key.exists():
        kwargs["ssl_certfile"] = str(ssl_cert)
        kwargs["ssl_keyfile"] = str(ssl_key)
    elif settings.bind_https:
        # generate ephemeral self-signed for dev if missing
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
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    run()
