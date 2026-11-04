"""The app the browser tests (Playwright) run against.

``uvicorn tests.e2e_app:app`` serves the real FastAPI app and the built web UI
(``PRINTER_HUB_WEB_DIST_DIR``) on a throw-away SQLite database. Hardware and upstream
apps are replaced: both printers use ``MockPrinterBackend`` and Snipe-IT, Grocy and
Spoolman are in-memory fakes, so no network is involved.

Environment:

- ``E2E_KEY_FILE``: path that receives the plaintext key to sign in with (mode 0600).
  With the default seeding this is an admin API key.
- ``E2E_PORT``: the port uvicorn listens on (default 8765); it forms ``public_url``.
- ``E2E_BOOTSTRAP=1``: start with no API keys and the one-time bootstrap key instead (D7);
  the file then holds the bootstrap key.

The module builds the app on import (like ``app.main``), because that is how uvicorn
loads it. Importing it therefore needs the same settings ``app.main`` needs; they are
filled with throw-away values below, never read from the real environment.
"""

from __future__ import annotations

import asyncio
import base64
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any

from starlette.types import ASGIApp

E2E_ADMIN_KEY_NAME = "e2e admin key"

# Printers created through the admin service (the model ids are real driver ids).
E2E_PRINTERS: tuple[dict[str, Any], ...] = (
    {
        "name": "Workshop PT-P750W",
        "slug": "workshop-pt",
        "model": "PT-P750W",
        "backend": "ptouch",
        "connection": {"host": "192.0.2.10", "port": 9100},
    },
    {
        "name": "Office QL-820NWB",
        "slug": "office-ql",
        "model": "QL-820NWB",
        "backend": "brother_ql",
        "connection": {"host": "192.0.2.11", "port": 9100},
    },
)


class _FakeIntegration:
    """In-memory stand-in for an integration plugin (satisfies ``IntegrationPlugin``)."""

    def __init__(self, name: str, display_name: str) -> None:
        self.name = name
        self.display_name = display_name

    async def lookup(self, identifier: str) -> Any:
        from app.schemas.label_data import LabelData

        return LabelData(
            source_app=self.name,
            title=f"{self.display_name} item",
            primary_id=identifier,
            qr_payload=f"https://example.invalid/{self.name}/{identifier}",
        )

    def bind(self, store: Any) -> None:
        return None

    async def reconfigure(self) -> None:
        return None

    def is_configured(self) -> bool:
        return True


def _prepare_environment(workdir: Path) -> tuple[bool, Path | None]:
    """Fill the settings ``app.main`` reads at import time. Returns (bootstrap, key_file)."""
    bootstrap = os.environ.get("E2E_BOOTSTRAP") == "1"
    key_file_raw = os.environ.get("E2E_KEY_FILE")
    os.environ["PRINTER_HUB_SECRET_KEY"] = base64.urlsafe_b64encode(
        secrets.token_bytes(32)
    ).decode()
    os.environ["PRINTER_HUB_PUBLIC_URL"] = f"http://localhost:{os.environ.get('E2E_PORT', '8765')}"
    os.environ["PRINTER_HUB_DATABASE_URL"] = f"sqlite+aiosqlite:///{workdir / 'e2e.db'}"
    os.environ.setdefault("PRINTER_HUB_WEB_DIST_DIR", "../frontend/dist")
    if bootstrap:
        # A throw-away bootstrap key: at least 32 characters.
        os.environ["PRINTER_HUB_BOOTSTRAP_ADMIN_KEY"] = "e2e-bootstrap-" + secrets.token_urlsafe(24)
    else:
        os.environ.pop("PRINTER_HUB_BOOTSTRAP_ADMIN_KEY", None)
    return bootstrap, Path(key_file_raw) if key_file_raw else None


def _migrate(database_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    ini = Path(__file__).resolve().parents[1] / "alembic.ini"
    cfg = Config(str(ini))
    cfg.attributes["configure_logger"] = False
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")


async def _seed(database_url: str, *, with_admin_key: bool) -> str | None:
    """Create the two mock printers (and the admin key); returns the admin key plaintext."""
    from app.auth.key_generator import generate_api_key
    from app.models.api_key import ApiKey
    from app.repositories import api_keys as api_keys_repo
    from app.schemas.printer_admin import PrinterCreatePayload
    from app.services.printer_admin_service import PrinterAdminService
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(database_url, connect_args={"check_same_thread": False})
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            service = PrinterAdminService(session, "e2e")
            for printer in E2E_PRINTERS:
                await service.create_printer(PrinterCreatePayload(**printer))
        if not with_admin_key:
            return None
        plaintext, prefix, hashed = generate_api_key()
        async with factory() as session:
            await api_keys_repo.create(
                session,
                ApiKey(
                    name=E2E_ADMIN_KEY_NAME,
                    key_hash=hashed,
                    key_prefix=prefix,
                    scopes=["admin"],
                    allowed_printer_ids=[],
                    rate_limit_per_minute=10000,
                    enabled=True,
                ),
            )
        return plaintext
    finally:
        await engine.dispose()


def _write_key_file(path: Path, key: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(key)


def build_e2e_app() -> ASGIApp:
    """Build the app against a fresh temp database; see the module docstring."""
    workdir = Path(tempfile.mkdtemp(prefix="lph-e2e-"))
    bootstrap, key_file = _prepare_environment(workdir)

    # Imported only now: ``app.main`` and ``app.db.engine`` read the settings at import time.
    from app.config import get_settings

    get_settings.cache_clear()
    database_url = os.environ["PRINTER_HUB_DATABASE_URL"]
    _migrate(database_url)
    admin_key = asyncio.run(_seed(database_url, with_admin_key=not bootstrap))

    import app.main as main_module
    from app.integrations.registry import IntegrationRegistry
    from app.printer_backends.mock_backend import MockPrinterBackend
    from app.services.backend_router import BackendRouter

    # The database is migrated above; the lifespan's own run would use alembic.ini's path.
    async def _already_migrated() -> None:
        return None

    main_module.run_migrations = _already_migrated  # type: ignore[assignment]
    # No printer is reachable: every configured printer gets the in-memory backend.
    BackendRouter._build_one = staticmethod(lambda _cfg: MockPrinterBackend())  # type: ignore[method-assign]
    IntegrationRegistry.clear()  # importing app.main discovered the real plugins
    for name, display in (("snipeit", "Snipe-IT"), ("grocy", "Grocy"), ("spoolman", "Spoolman")):
        IntegrationRegistry.register(_FakeIntegration(name, display))  # type: ignore[arg-type]

    if key_file is not None:
        key = os.environ["PRINTER_HUB_BOOTSTRAP_ADMIN_KEY"] if bootstrap else admin_key
        assert key is not None
        _write_key_file(key_file, key)
    return main_module.create_app()


app = build_e2e_app()
