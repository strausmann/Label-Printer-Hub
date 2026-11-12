"""The app the browser tests (Playwright) run against.

``uvicorn tests.e2e_app:app`` serves the real FastAPI app and the built web UI
(``PRINTER_HUB_WEB_DIST_DIR``) on a throw-away SQLite database. Hardware and upstream
apps are replaced: both tape printers use ``MockPrinterBackend`` and Snipe-IT, Grocy and
Spoolman are in-memory fakes, so no network is involved. The one page printer is real IPP
against a scriptable fake on a loopback port; ``E2EApp`` (below) starts it, seeds the sheets
and serves the ``/__e2e/`` control paths that switch its state.

Environment:

- ``E2E_KEY_FILE``: path that receives the plaintext key to sign in with (mode 0600).
  With the default seeding this is an admin API key.
- ``E2E_PORT``: the port uvicorn listens on (default 8765); it forms ``public_url``.
- ``E2E_BOOTSTRAP=1``: start with no API keys and the one-time bootstrap key instead (D7);
  the file then holds the bootstrap key.

The Grocy URL is set through the environment, so the settings UI has a locked field to test.

The module builds the app on import (like ``app.main``), because that is how uvicorn
loads it. Importing it therefore needs the same settings ``app.main`` needs; they are
filled with throw-away values below, never read from the real environment.
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import os
import secrets
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

E2E_ADMIN_KEY_NAME = "e2e admin key"
E2E_FAILED_JOB_TITLE = "Failed cable label"
E2E_FAILED_JOB_ERROR = "Printer reported: cover open"

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

# The one tape printer the hub polls (263-29): its status comes from ``_fake_preflight``.
E2E_POLLED_TAPE_NAME = "Bench PT-P750W"
E2E_POLLED_TAPE_SLUG = "bench-pt"
E2E_POLLED_TAPE_MM = 12
"""The tape width the fake status writer reports for the polled printer."""
E2E_POLLED_TAPE_PRINTER: dict[str, Any] = {
    "name": E2E_POLLED_TAPE_NAME,
    "slug": E2E_POLLED_TAPE_SLUG,
    "model": "PT-P750W",
    "backend": "ptouch",
    "connection": {
        "host": "192.0.2.12",
        "port": 9100,
        "snmp": {"discover": True, "community": "public"},
    },
}


async def _fake_preflight(host: str, **_kwargs: Any) -> Any:
    """The fake SNMP status writer: the polled printer is idle with a 12 mm tape loaded."""
    from app.printer_backends.snmp_helper import PreflightStatus

    return PreflightStatus(
        hr_printer_status="idle", loaded_tape_mm=E2E_POLLED_TAPE_MM, error_flags=[], media_raw=None
    )


async def _fake_model_pjl(host: str, **_kwargs: Any) -> str:
    """No SNMP agent to ask for the model: the printer falls back to the model it was saved with."""
    from app.printer_backends.exceptions import SnmpDiscoveryError

    raise SnmpDiscoveryError("e2e: no SNMP agent")


async def _fake_identity(host: str, **_kwargs: Any) -> Any:
    """No hardware identity: the e2e hub has no SNMP agent to ask."""
    from app.printer_backends.snmp_helper import ObservedIdentity

    return ObservedIdentity()


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
    # Every spec signs in from 127.0.0.1; the production default (10/min) would trip.
    os.environ["PRINTER_HUB_SIGN_IN_LIMIT_PER_MINUTE"] = "100000"
    # The page printer's status is probed over IPP; a 30 s interval would make every state
    # switch in the specs take half a minute. The tape printers use the in-memory backend.
    os.environ["PRINTER_HUB_SSE_PROBE_INTERVAL_S"] = E2E_PROBE_INTERVAL_S
    os.environ.setdefault("PRINTER_HUB_WEB_DIST_DIR", "../frontend/dist")
    # One integration URL comes from the container, so the settings UI has a locked field (D4).
    os.environ["PRINTER_HUB_GROCY_URL"] = "http://grocy.example.invalid"
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
    from app.models.job import Job, JobState
    from app.repositories import api_keys as api_keys_repo
    from app.schemas.printer_admin import PrinterCreatePayload
    from app.services.printer_admin_service import PrinterAdminService
    from app.sheets.locking import install_statement_counter
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(database_url, connect_args={"check_same_thread": False})
    install_statement_counter(engine.sync_engine)  # the sheet write lock needs it (264-01)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            service = PrinterAdminService(session, "e2e")
            created = [
                await service.create_printer(PrinterCreatePayload(**printer))
                for printer in E2E_PRINTERS
            ]
            # One failed job, so the jobs page has something to retry.
            session.add(
                Job(
                    printer_id=created[1].id,
                    state=JobState.FAILED.value,
                    error=E2E_FAILED_JOB_ERROR,
                    payload={
                        "content_type": "qr_two_lines",
                        # Same keys PrintService writes: retry re-renders from them.
                        # 24 mm = what the mock printer reports as loaded: a retry no longer
                        # fails with a tape mismatch, which would pause this printer and
                        # leak into the printer specs.  (The QL driver has no 24 mm spec, so
                        # the retried job still ends up failed; the jobs spec does not
                        # depend on that outcome.)
                        "rendered_tape_mm": 24,
                        "tape_mm": 24,
                        "options": {"copies": 1},
                        "label_data": {
                            "source_app": "snipeit",
                            "title": E2E_FAILED_JOB_TITLE,
                            "primary_id": "A-0001",
                            "qr_payload": "https://example.invalid/snipeit/1",
                            "secondary": [],
                            "items": [],
                        },
                    },
                )
            )
            await session.commit()
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


# --- page printer, seeded sheets and the control path (Plan 4, Task 1) ---------------------------

E2E_PAGE_PRINTER_NAME = "Office page printer"
E2E_PAGE_PRINTER_SLUG = "office-page"
E2E_PAGE_TRAY = "main-tray"
# What the real HP CP1525N reports (spike #231): a default paper size, no per-tray media.
E2E_MEDIA_DEFAULT = "iso_a4_210x297mm"
E2E_CONTROL_PREFIX = "/__e2e/"
# Short probe interval: the hub learns of a state switch within about a second (default: 30 s).
E2E_PROBE_INTERVAL_S = "1"

TAPE_L4736 = "avery-zweckform-l4736rev"  # 4 x 12 = 48 cells
TAPE_L4731 = "avery-zweckform-l4731rev"  # 189 cells, the edge sheet
E2E_CUSTOM_TYPE_KEY = "e2e-custom-unknown-radius"


_TAPE_BACKENDS: list[Any] = []
"""The in-memory backends of the tape printers (``MockPrinterBackend``), in build order."""


class _TapeState(BaseModel):
    """Body of ``POST /__e2e/tape-printer/state``: the tape ends after this many more labels."""

    model_config = ConfigDict(extra="forbid")

    tape_runs_out_in: int = Field(ge=0, le=10_000)


def _tape_out_in(labels: int) -> None:
    for backend in _TAPE_BACKENDS:
        backend.tape_runs_out_after = len(backend.printed_images) + labels


def _new_tape() -> None:
    """A fresh tape in every tape printer: it no longer runs out, and it is not empty."""
    for backend in _TAPE_BACKENDS:
        backend.tape_runs_out_after = None
        backend._tape_empty = False


def _new_fake() -> Any:
    from tests.helpers.fake_ipp_printer import FakeIppPrinter

    return FakeIppPrinter(media_sources=[E2E_PAGE_TRAY], media_default=E2E_MEDIA_DEFAULT)


class _PageState(BaseModel):
    """Body of ``POST /__e2e/page-printer/state``: every field optional, none unknown."""

    model_config = ConfigDict(extra="forbid")

    printer_state: int | None = None
    reasons: list[str] | None = None
    markers: list[dict[str, Any]] | None = None
    accepting_jobs: bool | None = None
    job_script: list[int] | None = None
    margins_hmm: int | None = Field(default=None, ge=0, le=5000)
    cancel_steps: int | None = Field(default=None, ge=0, le=20)
    media_default: str | None = Field(default=None, max_length=64)
    """A media keyword; ``""`` clears it (a real ``None`` means "leave unchanged")."""
    printer_uuid: str | None = Field(default=None, max_length=64)
    """The ``printer-uuid`` the printer reports (the identity the hub stores); ``""`` clears it."""


_RESET_KEEP = frozenset({"received", "_jobs", "_next_job_id"})


def _reset_fake(fake: Any) -> None:
    """Back to a fresh idle printer, in place: the running server keeps the same object."""
    fresh = _new_fake()
    for f in dataclasses.fields(fake):
        if f.name not in _RESET_KEEP:
            setattr(fake, f.name, getattr(fresh, f.name))
    fake.received.clear()


def _fake_state(fake: Any) -> dict[str, Any]:
    return {
        "printer_state": fake.printer_state,
        "reasons": list(fake.reasons),
        "markers": [dict(m) for m in fake.markers],
        "accepting_jobs": fake.accepting_jobs,
        "job_script": list(fake.job_script),
        "margins_hmm": fake.margins_hmm,
        "cancel_steps": fake.cancel_steps,
        "media_default": fake.media_default,
        "printer_uuid": fake.printer_uuid,
        "media_sources": list(fake.media_sources),
    }


class E2EApp:
    """ASGI wrapper around the hub for the browser tests.

    - On ``lifespan.startup`` it first brings up the fake page printer, creates its printer row
      and the seed sheets, and only then lets the hub's own lifespan run (C4): the hub reads its
      enabled page printers once at startup, so the row has to exist before that.
    - It serves ``/__e2e/…`` itself, ahead of the hub's SPA catch-all (C5), so a GET never
      returns ``index.html``. These paths exist in this wrapper only, never in ``app.main``.
    """

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.fake = _new_fake()
        self.uri: str | None = None
        self._stop: Any = None

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "lifespan":
            await self._lifespan(scope, receive, send)
        elif scope["type"] == "http" and scope["path"].startswith(E2E_CONTROL_PREFIX):
            await self._control(scope, receive, send)
        else:
            await self.inner(scope, receive, send)

    async def _lifespan(self, scope: Any, receive: Any, send: Any) -> None:
        async def receive_with_setup() -> Any:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await self._setup()
            return message

        async def send_with_teardown(message: Any) -> None:
            if message["type"] in ("lifespan.shutdown.complete", "lifespan.shutdown.failed"):
                await self._teardown()
            await send(message)

        await self.inner(scope, receive_with_setup, send_with_teardown)

    async def _setup(self) -> None:
        from tests.helpers.fake_ipp_printer import serve_on_loopback

        self.uri, self._stop = await serve_on_loopback(self.fake)
        await _seed_page_printer_and_sheets(self.uri)

    async def _teardown(self) -> None:
        if self._stop is not None:
            stop, self._stop = self._stop, None
            await stop()

    async def _resume_tape_printers(self) -> None:
        """Lift a pause an empty tape caused, so the next spec finds the printers ready."""
        app = getattr(self.inner, "_app", self.inner)
        queue = getattr(app.state, "print_queue", None)
        if queue is None:
            return
        for printer_id in list(getattr(queue, "_printers", {})):
            info = queue.pause_info(printer_id)
            if info is not None and info.source == "printer_error":
                await queue.resume_printer(printer_id)

    async def _control(self, scope: Any, receive: Any, send: Any) -> None:
        request = Request(scope, receive)
        path = request.url.path.rstrip("/")
        method = request.method
        response: Response
        if path == "/__e2e/page-printer" and method == "GET":
            response = JSONResponse({"uri": self.uri, "state": _fake_state(self.fake)})
        elif path == "/__e2e/page-printer/state" and method == "POST":
            try:
                body = _PageState.model_validate(await request.json())
            except (ValueError, ValidationError) as exc:
                response = JSONResponse({"error": str(exc)}, status_code=422)
            else:
                for name, value in body.model_dump(exclude_none=True).items():
                    clearable = name in ("media_default", "printer_uuid")
                    setattr(self.fake, name, value or None if clearable else value)
                response = JSONResponse({"uri": self.uri, "state": _fake_state(self.fake)})
        elif path == "/__e2e/page-printer/reset" and method == "POST":
            _reset_fake(self.fake)
            response = JSONResponse({"uri": self.uri, "state": _fake_state(self.fake)})
        elif path == "/__e2e/tape-printer/state" and method == "POST":
            try:
                tape = _TapeState.model_validate(await request.json())
            except (ValueError, ValidationError) as exc:
                response = JSONResponse({"error": str(exc)}, status_code=422)
            else:
                _tape_out_in(tape.tape_runs_out_in)
                response = JSONResponse({"backends": len(_TAPE_BACKENDS)})
        elif path == "/__e2e/tape-printer/reset" and method == "POST":
            _new_tape()
            await self._resume_tape_printers()
            response = JSONResponse({"backends": len(_TAPE_BACKENDS)})
        else:
            response = JSONResponse({"error": "unknown control path"}, status_code=404)
        await response(scope, receive, send)


async def _seed_page_printer_and_sheets(uri: str) -> None:
    """Create the page printer row and the seed sheets; the order of the sheets is fixed."""
    from app.db.engine import async_session
    from app.schemas.printer_admin import PrinterCreatePayload
    from app.seed.sheet_seed import run_sheet_seed
    from app.services.printer_admin_service import PrinterAdminService
    from app.sheets import sheet_service, type_service
    from app.sheets.geometry import Geometry
    from app.sheets.sheet_service import MarkedCell

    async with async_session() as session:
        # After the two tape printers (created_at order): ``usable[0]`` stays Workshop PT-P750W.
        service = PrinterAdminService(session, "e2e")
        await service.create_printer(
            PrinterCreatePayload.model_validate(
                {
                    "name": E2E_PAGE_PRINTER_NAME,
                    "slug": E2E_PAGE_PRINTER_SLUG,
                    "backend": "ipp",
                    "connection": {"uri": uri, "tls_verify": True},
                    "trays": [
                        {
                            "key": E2E_PAGE_TRAY,
                            "label": "Main tray",
                            "load_hint": "written side down, top edge first",
                            "is_default": True,
                        },
                        {"key": "auto", "label": "Automatic"},
                    ],
                }
            )
        )
        # Last, so every list keeps the first three printers where they were.
        await service.create_printer(PrinterCreatePayload.model_validate(E2E_POLLED_TAPE_PRINTER))

    # Idempotent; the lifespan runs it again afterwards.
    await run_sheet_seed(async_session)

    def marks(numbers: range, purpose: Any) -> list[MarkedCell]:
        return [MarkedCell(n, purpose(n)) for n in numbers]

    async def _mk_sheet(
        session: Any, type_key: str, used: range, purpose: Callable[[int], str]
    ) -> Any:
        """A sheet of *type_key* with the cells *used* marked, written by ``purpose``."""
        return await sheet_service.create_sheet(
            session,
            type_key=type_key,
            version=None,
            used_cells=marks(used, purpose),
            note=None,
            actor="e2e",
        )

    def item(n: int) -> str:
        return f"item {n}"

    async with async_session() as session:
        # 1. L4736-0001: 17 of 48 cells used.
        await _mk_sheet(session, TAPE_L4736, range(1, 18), item)
        # 2. L4736-0002: full.
        await _mk_sheet(session, TAPE_L4736, range(1, 49), item)
        # 3. L4736-0003: discarded.
        discarded = await _mk_sheet(session, TAPE_L4736, range(1, 4), item)
        await sheet_service.discard_sheet(session, discarded.code, actor="e2e")
        # 4. L4731-0001: the 189-cell edge sheet, 120 used, every purpose 120 characters long.
        await _mk_sheet(
            session,
            TAPE_L4731,
            range(1, 121),
            lambda n: f"cell {n:03d} " + "a" * (120 - len(f"cell {n:03d} ")),
        )
        # A custom type whose corner radius is unknown (the "measure it" case).
        await type_service.create_type(
            session,
            type_service.TypeFields(
                key=E2E_CUSTOM_TYPE_KEY,
                prefix="E2ECUSTOM",
                vendor="E2E Labels",
                product_codes=["E2E-3x4"],
                description="Custom type, corner radius unknown",
                allow_qr=None,
            ),
            Geometry(
                page_size="A4",
                page_w=21000,
                page_h=29700,
                label_w=6000,
                label_h=4000,
                cols=3,
                rows=4,
                pitch_x=6500,
                pitch_y=4500,
                margin_top=1500,
                margin_left=1500,
                corner_radius=None,
                shape="rectangle",
            ),
            actor="e2e",
        )


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

    # No printer is reachable: every configured printer gets the in-memory backend. They are
    # kept, so ``/__e2e/tape-printer/state`` can let their tape run out (#277).
    def _mock_backend(_cfg: Any) -> MockPrinterBackend:
        backend = MockPrinterBackend()
        _TAPE_BACKENDS.append(backend)
        return backend

    BackendRouter._build_one = staticmethod(_mock_backend)  # type: ignore[method-assign]
    # The polled tape printer (263-29): the runtime and the status probe ask these, not the network.
    from app.services import printer_runtime
    from app.services.producers import status_probe_producer

    printer_runtime.query_model_pjl = _fake_model_pjl  # type: ignore[assignment]
    status_probe_producer.query_preflight = _fake_preflight  # type: ignore[assignment]
    status_probe_producer.query_identity = _fake_identity  # type: ignore[assignment]
    IntegrationRegistry.clear()  # importing app.main discovered the real plugins
    for name, display in (("snipeit", "Snipe-IT"), ("grocy", "Grocy"), ("spoolman", "Spoolman")):
        IntegrationRegistry.register(_FakeIntegration(name, display))  # type: ignore[arg-type]

    if key_file is not None:
        key = os.environ["PRINTER_HUB_BOOTSTRAP_ADMIN_KEY"] if bootstrap else admin_key
        assert key is not None
        _write_key_file(key_file, key)
    return E2EApp(main_module.create_app())


_APP: ASGIApp | None = None


def __getattr__(name: str) -> ASGIApp:
    """``tests.e2e_app:app`` is built on first access, not at import.

    Building the app writes ``os.environ``, clears the settings cache and patches
    ``app.main`` and the backend router. A unit test that only imports the helpers above
    (``test_e2e_page_state``) must not change the process, so only the server entry point
    (``uvicorn tests.e2e_app:app``), which reads the attribute, pays for it.
    """
    global _APP
    if name != "app":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if _APP is None:
        _APP = build_e2e_app()
    return _APP
