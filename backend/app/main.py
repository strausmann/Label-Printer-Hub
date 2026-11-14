# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""FastAPI application entry point.

This module exposes the ASGI app that uvicorn runs in the container. It owns:

- The OpenAPI metadata (title, version, description, /openapi.json, /docs)
- The /healthz endpoint for container orchestrators
- The lifespan that wires plugin discovery, backend selection, driver resolution
  (SNMP-first / setting fallback), queue start, and PrintService into app.state
- Registration of all API routers (printers, jobs, layouts, …)

Routers live under :mod:`app.api` and are mounted here. Keeping the app
instance in one place makes it trivial for tests to import.

See:
    docs/decisions/0002-python-fastapi-backend.md — choice of FastAPI
    docs/decisions/0011-openapi-as-api-contract.md — /openapi.json contract
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Annotated, Any

# ---------------------------------------------------------------------------
# F3 — Early settings validation with a friendly error message.
#
# app.config.get_settings() is called at module load by engine.py (imported
# below) and by integration plugins (imported via app.integrations).  If an
# env var fails Pydantic validation (e.g. LABELYARD_WEBHOOK_API_KEY is
# shorter than 32 chars) we catch the ValidationError here — BEFORE any
# integration imports that would produce multiple interleaved tracebacks —
# and print a human-readable summary, then exit with EX_CONFIG (78).
#
# The raw traceback is preserved when LOG_LEVEL=DEBUG so developers still see
# it during local iteration.
# ---------------------------------------------------------------------------
from pydantic import ValidationError

from app.config import get_settings as _get_settings

try:
    _get_settings()
except ValidationError as _cfg_exc:
    # Honour the app-prefixed var (LABELYARD_LOG_LEVEL, consistent with all other Settings
    # fields), its deprecated predecessor (PRINTER_HUB_LOG_LEVEL) and the short alias
    # (LOG_LEVEL) that uvicorn and other tools conventionally set.
    _debug = any(
        os.environ.get(_name, "").upper() == "DEBUG"
        for _name in ("LABELYARD_LOG_LEVEL", "PRINTER_HUB_LOG_LEVEL", "LOG_LEVEL")
    )
    if _debug:
        # Raise for a traceback, but never re-raise the ValidationError itself: its text
        # carries every offending input value, and those can be secrets.
        _detail = "\n".join(
            f"  {'.'.join(str(_p) for _p in _e['loc'])} [{_e['type']}]: {_e['msg']}"
            for _e in _cfg_exc.errors(include_input=False, include_url=False, include_context=False)
        )
        raise RuntimeError(f"Configuration error (input values omitted):\n{_detail}") from None
    from app.config_legacy import report_from_process as _report_from_process
    from app.config_legacy import setting_variable_label as _variable_label

    _report = _report_from_process()
    _lines = ["❌  Configuration error — fix the following before starting:\n"]
    for _err in _cfg_exc.errors():
        _field = ".".join(str(_p) for _p in _err["loc"])
        _msg = _err["msg"]
        # An unknown key is already reported under its full variable name.
        _label = (
            _field.upper()
            if _err["type"] == "extra_forbidden"
            else _variable_label(_field, _report)
        )
        _lines.append(f"   • {_label}: {_msg}\n")
    _lines.append("\n")
    _lines.append("Hint: see backend/.env.example for all supported variables.\n")
    sys.stderr.writelines(_lines)
    sys.exit(78)  # sysexits.h EX_CONFIG

from fastapi import Depends, FastAPI, Request, Response
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

import app.integrations as _integrations_init  # triggers integration plugin discovery
from app import __version__
from app.api.error_handlers import (
    SHEET_ERROR_SCHEMA,
    SHEET_ERROR_SCHEMA_NAME,
    answers_with_envelope,
    is_sheet_path,
    register_error_handlers,
)
from app.api.routes import auth_session as auth_session_routes
from app.api.routes import batch as batch_routes
from app.api.routes import batches as batches_routes
from app.api.routes import events_v1 as events_v1_routes
from app.api.routes import info as info_routes
from app.api.routes import jobs as jobs_routes
from app.api.routes import lookup as lookup_routes
from app.api.routes import printer_roll as printer_roll_routes
from app.api.routes import printers as printers_routes
from app.api.routes import qr as qr_routes
from app.api.routes import sheet_print as sheet_print_routes
from app.api.routes import test_print as test_print_routes
from app.api.routes import webhooks as webhooks_routes
from app.api.routes.admin_api_keys import router as admin_api_keys_router
from app.api.routes.admin_printers_api import router as admin_printers_api_router
from app.api.routes.calibration import router as calibration_router
from app.api.routes.capabilities import router as capabilities_router
from app.api.routes.print import render_router
from app.api.routes.print import router as print_router
from app.api.routes.settings_api import router as settings_api_router
from app.api.routes.sheet_types import router as sheet_types_router
from app.api.routes.sheets import router as sheets_router
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_read
from app.auth.sessions import purge_expired as purge_expired_sessions
from app.auth.sessions import warn_if_insecure as warn_if_insecure_cookies
from app.build_info import PROJECT_LICENSE, public_repo_url
from app.calibration.page import render_calibration_page
from app.config import get_settings
from app.config_legacy import listen_port_warning, report_from_process, warn_legacy_env
from app.db.engine import async_session, engine
from app.db.lifespan import (
    ensure_printer_state,
    run_migrations,
    verify_alembic_at_head,
)
from app.db.session import get_session
from app.integrations.registry import IntegrationRegistry
from app.observability.log_buffer import install_log_buffer
from app.page_render.pdf import register_pdf_font
from app.page_render.test_page import render_test_page
from app.printer_models.registry import ModelRegistry
from app.repositories import printers as printers_repo
from app.schemas.readiness import ReadinessResponse
from app.services.cleanup_task import CleanupTask
from app.services.event_bus import EventBus
from app.services.job_store_sqlite import SQLiteJobStore
from app.services.layout_engine import LayoutEngine
from app.services.page_jobs import (
    register_outcome_handler,
    register_page_renderer,
    register_recovery_check,
    unregister_outcome_handler,
    unregister_recovery_check,
)
from app.services.print_queue import PrintQueue, load_manual_pauses
from app.services.printer_runtime import PrinterRuntime
from app.services.printer_runtime import shutdown_wait_s as shutdown_wait_s  # re-export
from app.services.producers.print_queue_producer import PrintQueueProducer
from app.services.producers.printer_pause_producer import PrinterPauseProducer
from app.services.readiness import build_readiness_response
from app.settings_store import SettingsStore
from app.sheets.outcome import SheetCellsOutcome, sweep_orphan_reservations
from app.sheets.sheet_page import render_sheet_page
from app.sheets.sweep import SheetReservationSweep
from app.web.api_docs import mount_api_docs
from app.web.spa import add_security_headers, mount_spa
from app.web.version_header import add_version_header

# Per ADR 0011 we pin the OpenAPI version explicitly rather than relying on
# FastAPI's default, so a FastAPI upgrade can't drift the API contract version.
OPENAPI_VERSION = "3.1.0"

# Build-info ENV vars are set by the Dockerfile at build time. Fall back to
# sensible defaults so local non-container runs and unit tests still work.
HUB_VERSION: str = os.environ.get("HUB_VERSION") or __version__
HUB_REVISION: str = os.environ.get("HUB_REVISION", "unknown")
HUB_BUILD_DATE: str = os.environ.get("HUB_BUILD_DATE", "1970-01-01T00:00:00Z")
HUB_REPO_URL: str = os.environ.get("HUB_REPO_URL", "https://github.com/strausmann/labelyard")

_log = logging.getLogger(__name__)


class Healthz(BaseModel):
    """Response body of /healthz.

    Intentionally minimal — no dependencies, no configuration, no PII.
    Container orchestrators check the HTTP status and read the JSON for
    a quick version sanity-check; ops use the build-info fields to confirm
    which image is running without digging through ``docker inspect``.

    Frozen so callers can't accidentally mutate the response model in-place
    (the same immutability discipline we apply to dataclasses — see
    ``docs/learnings/code-review-patterns.md``).
    """

    model_config = ConfigDict(frozen=True)

    status: str
    version: str
    revision: str
    build_date: str
    repository: str
    sse_active_subscribers: int = 0
    """Current live SSE subscriber count. Zero when no clients are connected
    or when the EventBus has not been initialised (pre-lifespan)."""


def _pinned_openapi_schema(app: FastAPI) -> Any:
    """Build the OpenAPI schema with an explicitly pinned version.

    Per ADR 0011 we lock the OpenAPI document version to a known value so a
    future FastAPI upgrade can't silently change it. We do this by overriding
    ``app.openapi`` with a function that calls FastAPI's own ``get_openapi``
    with our chosen ``openapi_version`` — that is the framework-supported
    extension point and stays stable across FastAPI releases. The result is
    cached on ``app.openapi_schema`` so the schema is only built once.
    """
    if app.openapi_schema:
        return app.openapi_schema
    app.openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=OPENAPI_VERSION,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
        servers=app.servers,
        license_info=app.license_info,
    )
    _declare_sheet_error_envelope(app.openapi_schema)
    return app.openapi_schema


def _declare_sheet_error_envelope(schema: dict[str, Any]) -> None:
    """Describe the error bodies the sheet APIs really return (see ``_validation_handler``).

    FastAPI documents ``HTTPValidationError`` for every route; the sheet routes answer with the
    nested error envelope instead, so generated clients must not be told otherwise.
    """
    schema.setdefault("components", {}).setdefault("schemas", {})[SHEET_ERROR_SCHEMA_NAME] = (
        SHEET_ERROR_SCHEMA
    )
    ref = {
        "application/json": {"schema": {"$ref": f"#/components/schemas/{SHEET_ERROR_SCHEMA_NAME}"}}
    }
    for path, item in schema.get("paths", {}).items():
        if not answers_with_envelope(path):
            continue
        sheet = is_sheet_path(path)
        for operation in item.values():
            for status_code, response in operation.get("responses", {}).items():
                # Every documented 4xx and 5xx of a sheet route carries the same error envelope
                # (a 502 for an integration or a stopped print is one too). A webhook route
                # answers only its validation error (422) that way; its other errors keep
                # their own shapes.
                if status_code == "422" or (sheet and status_code.startswith(("4", "5"))):
                    response["content"] = ref


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Wire all application-level singletons into app.state.

    Startup sequence
    ----------------
    1. Load seed templates (idempotent, skipped when directory is absent).
    2. Discover model + backend plugins via entry_points (idempotent).
    3. Load the enabled printers in creation order.
    4. Build the queue (not running), then ``PrinterRuntime.attach(fatal=True)`` each printer:
       backend, model driver, ``PrintService``, IPP clients and states, producers (not
       started). An unresolvable tape model aborts startup; a bad IPP URI is degraded.
    5. Register the sheet outcome handler, start the queue (manual pauses first), sweep
       orphan sheet reservations, start the cleanup task.
    6. ``PrinterRuntime.start()``: the status producers, each probing once at start.
    7. The periodic sheet reservation sweep (``SheetReservationSweep``, 266-04).

    Shutdown sequence
    -----------------
    The reservation sweep stops first. ``PrinterRuntime.stop()`` stops the producers, then
    ``queue.stop()`` once (it drains in-flight jobs up to the longest attached queue timeout,
    then cancels the rest), then closes the page clients.
    """
    settings = get_settings()
    warn_legacy_env(report_from_process(), _log)
    if (port_warning := listen_port_warning(os.environ)) is not None:
        _log.warning(port_warning)
    warn_if_insecure_cookies(settings)
    # 266-14: the PDF font is registered before any planner or renderer thread can need it.
    # A missing font is reported where it is used (the sheet print answers with it).
    try:
        register_pdf_font()
    except Exception:
        _log.exception("The PDF font could not be registered at startup")

    # --- DB startup: migrations first, then in-memory state, then DB writes ---
    await run_migrations()
    await verify_alembic_at_head(settings)

    # Sheet type archive: seed the shipped types. A failure is logged and never blocks startup.
    try:
        from app.seed.sheet_seed import run_sheet_seed

        await run_sheet_seed(async_session)
    except Exception:
        _log.exception("Sheet type seeding failed; continuing without it")

    # 2. Plugin registries (idempotent — skips already-registered names).
    # Re-run if the registry was cleared (e.g. by test fixtures that call
    # IntegrationRegistry._plugins.clear()).
    #
    # Audit #67: beide Calls machen sync I/O (entry_points-Discovery + Module-
    # Imports lesen .dist-info vom Disk). Im FastAPI-async-Lifespan blockt das
    # den event-loop — bei kalten Containern dauert das spürbar.
    # Wir schieben beide Discovery-Schritte in einen Thread.
    if not IntegrationRegistry.names():
        await asyncio.to_thread(_integrations_init._discover_plugins)

    await asyncio.to_thread(ModelRegistry.ensure_discovered)

    # 3. DB-bound init — plugin registry is populated.
    # Phase 5 (#124): printers come from the DB. On a first start (empty printers table)
    # nothing is wired and the hub starts without printers (the operator adds them through
    # the admin API).
    async with async_session() as s:
        # Enabled printers in creation order: the order the back-compat fields use.
        _db_printers = await printers_repo.list_all(s)
        await ensure_printer_state(s)
        await s.commit()
        # D4/D5: runtime settings (env-locked values, encrypted secrets).
        settings_store = SettingsStore()
        await settings_store.load(s)
        app.state.settings_store = settings_store
    # D4: integrations read URL/key/timeout from the store and follow changes live.
    for _plugin in IntegrationRegistry.all().values():
        _bind = getattr(_plugin, "bind", None)
        if callable(_bind):
            _bind(settings_store)
    # -------------------------------------------------------------------------

    # Phase 2: JobStore + CleanupTask
    # 'async_session' ist die async_sessionmaker aus app.db.engine (R2-M5)
    job_store = SQLiteJobStore(async_session)

    # --- SSE EventBus ---
    event_bus = EventBus(queue_size=settings.sse_queue_size)
    app.state.event_bus = event_bus
    # ----- end SSE ------

    # Shared LayoutEngine — stateless, safe to reuse across requests.
    # Used by PrintQueue recovery and PrintService rendering.
    shared_engine = LayoutEngine()
    app.state.engine = shared_engine
    app.state.job_store = job_store

    pq_producer = PrintQueueProducer(bus=event_bus)
    pause_producer = PrinterPauseProducer(bus=event_bus)
    queue = PrintQueue(
        printers=[],
        on_state_change=pq_producer.handle_transition,
        store=job_store,
        engine=shared_engine,
        on_pause_change=pause_producer.handle_change,
        on_run_change=pq_producer.handle_run_change,
    )
    app.state.print_queue = queue

    # Browser sessions: purge those expired for more than a day on every cleanup run.
    cleanup_task = CleanupTask(
        store=job_store,
        retention_days=lambda: int(settings_store.get("jobs.retention_days")),
        session_purge=lambda: purge_expired_sessions(async_session),
        queue=queue,  # finished jobs also leave the queue's memory
    )
    # Started after the orphan sweep below: its first eviction must not delete a job row the
    # sweep still has to read (T5-1).
    app.state.cleanup_task = cleanup_task

    # #224: every printer is wired by the runtime, at startup and on an admin change. The
    # queue is not running yet, so an attach only registers the printer and builds its
    # backend, service and producer; nothing probes before ``runtime.start()`` below.
    # An unresolvable tape model still aborts startup (fatal); a bad IPP URI is degraded.
    runtime = PrinterRuntime(app, settings, session_factory=async_session)
    app.state.printer_runtime = runtime
    for _db_printer in _db_printers:
        await runtime.attach(_db_printer, fatal=True)

    # D15: restart recovery calls the handler's ``on_unknown`` from inside ``start()``, so the
    # handler is registered first (a registry without it would hand the call to a no-op).
    sheet_outcome = SheetCellsOutcome(async_session, event_bus)
    register_outcome_handler("sheet_page", sheet_outcome)
    sheet_recovery = sheet_outcome.may_recover  # one bound method: unregister compares by identity
    register_recovery_check("sheet_page", sheet_recovery)
    # Persisted manual pauses must be in place before any worker task exists.
    async with async_session() as _pause_session:
        _initially_paused = await load_manual_pauses(_pause_session)
    await queue.start(initially_paused=_initially_paused)
    try:  # cells of jobs that ended, or vanished, while the hub was down
        await sweep_orphan_reservations(async_session, bus=event_bus)
    except Exception:
        _log.exception("Sheet orphan sweep failed; the next start tries again")
    await cleanup_task.start()
    if _initially_paused:
        _log.info("Restored %d manual printer pause(s) from the database", len(_initially_paused))
    # 266-04: cells of jobs that end while the hub runs, but whose outcome call is lost.
    reservation_sweep = SheetReservationSweep(async_session, queue, event_bus)
    app.state.sheet_reservation_sweep = reservation_sweep
    try:
        # Producers last: each probes once at start (no awaited probe at startup). Inside the
        # ``try`` so a failing start still reaches ``runtime.stop()`` (265-04).
        await runtime.start()
        await reservation_sweep.start()
        yield
    finally:
        # The sweep first: it asks the queue, which the runtime stops. Then the producers, the
        # queue (once, longest attached timeout), then the page clients.
        await reservation_sweep.stop()
        await runtime.stop()
        await cleanup_task.stop()
        unregister_outcome_handler("sheet_page", sheet_outcome)
        unregister_recovery_check("sheet_page", sheet_recovery)
        await engine.dispose()
        # Close shared HTTP clients held by integration plugins that support it.
        # Plugins that pre-date connection pooling may not have aclose(); skip them.
        for _plugin in IntegrationRegistry.all().values():
            _aclose = getattr(_plugin, "aclose", None)
            if callable(_aclose):
                await _aclose()
        # Clear the registry so that subsequent lifespan runs (e.g. during test
        # suite execution or server hot-reload) discover and instantiate fresh
        # plugin instances rather than reusing stale ones whose httpx pools have
        # already been closed.
        IntegrationRegistry.clear()


class _LifespanManager:
    """ASGI wrapper that runs the app's lifespan on the first non-lifespan call.

    httpx's ``ASGITransport`` sends only HTTP/WebSocket scopes — it never sends
    the ``lifespan`` scope.  This wrapper fills that gap so that tests using
    ``AsyncClient(transport=ASGITransport(app=...))`` still trigger startup and
    get early-failure exceptions propagated.

    A real ASGI server (uvicorn) sends the ``lifespan`` scope directly; this
    wrapper detects that and passes it straight through, so production behaviour
    is unchanged.

    Thread-safety note: the startup gate is protected by an ``asyncio.Lock`` so
    concurrent requests on the first tick can't race each other.
    """

    def __init__(self, app: FastAPI) -> None:
        self._app = app
        self._started = False
        self._startup_exc: BaseException | None = None
        self._lock: asyncio.Lock | None = None  # created lazily (event-loop bound)
        self._lifespan_task: asyncio.Task[None] | None = None
        self._send_queue: asyncio.Queue[dict[str, Any]] | None = None
        self._receive_queue: asyncio.Queue[dict[str, Any]] | None = None

    def _get_lock(self) -> asyncio.Lock:
        """Return the asyncio.Lock, creating it inside the running event loop."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def _start_lifespan(self) -> None:
        """Send a lifespan.startup event to the wrapped app and wait for ack."""
        self._send_queue = asyncio.Queue()
        self._receive_queue = asyncio.Queue()
        send_q = self._send_queue
        recv_q = self._receive_queue

        scope: dict[str, Any] = {
            "type": "lifespan",
            "asgi": {"version": "3.0"},
            "state": {},
        }

        async def receive() -> dict[str, Any]:
            return await recv_q.get()

        async def send(message: dict[str, Any]) -> None:
            await send_q.put(message)

        # Feed the startup event so the lifespan coroutine proceeds past its
        # first ``await receive()`` call.
        await recv_q.put({"type": "lifespan.startup"})
        self._lifespan_task = asyncio.create_task(
            self._app(scope, receive, send),  # type: ignore[arg-type]  # dict/MutableMapping compat
            name="lifespan",
        )

        # Wait for the app to ack startup (complete or failed).
        msg = await send_q.get()
        if msg["type"] == "lifespan.startup.complete":
            self._started = True
            _log.debug("_LifespanManager: startup complete")
        else:
            # startup.failed — the lifespan task is about to re-raise; harvest it.
            # If the task exits cleanly (shouldn't happen), surface the message.
            exc_from_task: BaseException = RuntimeError(
                f"Lifespan startup failed: {msg.get('message', '')}"
            )
            try:
                await self._lifespan_task
            except BaseException as exc:
                exc_from_task = exc
            self._startup_exc = exc_from_task
            raise exc_from_task

    async def _ensure_started(self) -> None:
        """Idempotent: runs lifespan startup exactly once; re-raises on failure."""
        if self._started:
            return
        if self._startup_exc is not None:
            raise self._startup_exc

        async with self._get_lock():
            # Double-check inside the lock (another coroutine may have completed
            # startup while we waited for the lock — mypy can't track this).
            if self._started:
                return  # type: ignore[unreachable]
            if self._startup_exc is not None:
                raise self._startup_exc
            try:
                await self._start_lifespan()
            except BaseException as exc:
                self._startup_exc = exc
                raise

    async def _run_lifespan_for_server(
        self,
        scope: dict[str, Any],  # noqa: ARG002  # unused; received from ASGI server but not forwarded
        receive: Any,
        send: Any,
    ) -> None:
        """Handle a lifespan scope sent by a real ASGI server (uvicorn, TestClient).

        The server sends ``lifespan.startup``; we start the inner app's lifespan
        via our internal queue pair, then relay the ack back to the server.
        On shutdown the server sends ``lifespan.shutdown``; we forward it to the
        inner app and wait for the inner app's lifespan context to finish.
        """
        # --- startup ---
        await receive()  # consume lifespan.startup from the server
        try:
            await self._start_lifespan()
        except BaseException as exc:
            self._startup_exc = exc
            await send({"type": "lifespan.startup.failed", "message": str(exc)})
            raise
        await send({"type": "lifespan.startup.complete"})

        # --- wait for shutdown signal ---
        await receive()  # consume lifespan.shutdown from the server

        # Signal the inner lifespan task to proceed past its ``yield``.
        if self._receive_queue is not None:
            await self._receive_queue.put({"type": "lifespan.shutdown"})

        # Wait for the inner task to finish cleanup.
        if self._lifespan_task is not None:
            with suppress(BaseException):
                await self._lifespan_task

        await send({"type": "lifespan.shutdown.complete"})

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Any,
        send: Any,
    ) -> None:
        if scope["type"] == "lifespan":
            # A real ASGI server is managing the lifecycle.
            # Intercept the lifespan scope and run startup/shutdown ourselves so
            # we can relay the results back to the server while keeping our own
            # _start_lifespan() state consistent. This prevents the inner FastAPI
            # app from receiving a duplicate lifespan scope (which would run the
            # lifespan twice).
            await self._run_lifespan_for_server(scope, receive, send)
            return
        await self._ensure_started()
        await self._app(scope, receive, send)


# Once per process, at import: a page job of this kind is drawn by this renderer (spec 13.2).
register_page_renderer("calibration_page", render_calibration_page)
register_page_renderer("sheet_page", render_sheet_page)
register_page_renderer("test_page", render_test_page)


def _may_name_default_printer(auth: AuthContext | None, state: Any) -> bool:
    """Whether the caller may learn the default printer's id (a restricted key may not)."""
    pid = getattr(state, "printer_id", None)
    if auth is None or pid is None or not auth.allowed_printer_ids:
        return True
    return str(pid) in auth.allowed_printer_ids


def create_app() -> _LifespanManager:
    """Build the FastAPI app. Kept as a factory so tests can re-instantiate."""
    install_log_buffer()
    # aiosqlite logs every statement and bound parameter at DEBUG; with the root logger at
    # DEBUG that would put device serials and key hashes into the log buffer (263-50).
    logging.getLogger("aiosqlite").setLevel(logging.INFO)
    app = FastAPI(
        lifespan=lifespan,
        title="Labelyard API",
        description=(
            "REST + SSE API of Labelyard, the self-hosted Label Printer Hub, "
            "which also serves the web UI. "
            "The OpenAPI spec is at /openapi.json; humans browse the interactive "
            "reference (Scalar) at /docs."
        ),
        version=HUB_VERSION,
        openapi_url="/openapi.json",
        # Interactive docs are served by app.web.api_docs (Scalar, no CDN).
        docs_url=None,
        redoc_url=None,
        license_info={"name": PROJECT_LICENSE, "identifier": PROJECT_LICENSE},
    )
    # Pin the OpenAPI document version per ADR 0011 via the supported
    # extension point: replace `app.openapi` with our wrapped builder.
    app.openapi = lambda: _pinned_openapi_schema(app)  # type: ignore[method-assign]

    @app.get(
        "/healthz",
        response_model=Healthz,
        tags=["meta"],
        summary="Liveness probe",
        description=(
            "Returns 200 OK with a fixed shape. No authentication required. "
            "Used by Docker, Kubernetes, and reverse proxies to decide whether "
            "the backend is up. Has zero dependencies — does not touch the "
            "database, the printer queue, SNMP, or any integration. "
            "``sse_active_subscribers`` reflects the current EventBus subscriber "
            "count; zero means no live SSE clients or the bus is uninitialised."
        ),
    )
    async def healthz(request: Request) -> Healthz:
        # async def avoids the threadpool roundtrip for this hot, dependency-
        # free endpoint. FastAPI runs sync route handlers in a threadpool
        # by default, which is wasted overhead for trivial responders.
        bus: EventBus | None = getattr(request.app.state, "event_bus", None)
        return Healthz(
            status="ok",
            version=HUB_VERSION,
            revision=HUB_REVISION,
            build_date=HUB_BUILD_DATE,
            repository=public_repo_url(HUB_REPO_URL),
            sse_active_subscribers=bus.distinct_subscriber_count() if bus else 0,
        )

    @app.get(
        "/readiness",
        response_model=ReadinessResponse,
        tags=["meta"],
        summary="Readiness probe",
        description=(
            "Deep readiness check: database connectivity, alembic migration "
            "state, printer wiring, SNMP probe recency, "
            "print-queue liveness, SSE subscriber capacity, and stuck render slots "
            "(`render_slots`: page renders past `LABELYARD_RENDER_TIMEOUT_S` whose "
            "thread still runs; fails when every slot is stuck, a hub restart frees them). "
            "Returns 200 with status in {ready, degraded} when all critical "
            "checks pass; 503 with status=not-ready when any critical check "
            "(database / alembic) fails."
        ),
        responses={503: {"model": ReadinessResponse}},
    )
    async def readiness(
        response: Response,
        session: Annotated[AsyncSession, Depends(get_session)],
        _auth: Annotated[AuthContext, Depends(require_read)] = None,  # type: ignore[assignment]
    ) -> ReadinessResponse:
        body = await build_readiness_response(
            session,
            app.state,
            get_settings(),
            version=HUB_VERSION,
            revision=HUB_REVISION,
            reveal_printer_id=_may_name_default_printer(_auth, app.state),
        )
        if body.status == "not-ready":
            response.status_code = 503
        return body

    register_error_handlers(app)
    app.include_router(print_router)
    app.include_router(render_router)
    app.include_router(batch_routes.router)
    app.include_router(batches_routes.router)
    app.include_router(events_v1_routes.router)
    app.include_router(printers_routes.router)
    app.include_router(printer_roll_routes.router)
    app.include_router(jobs_routes.router)
    app.include_router(lookup_routes.router)
    app.include_router(webhooks_routes.router)
    app.include_router(qr_routes.router)
    app.include_router(admin_api_keys_router)
    app.include_router(auth_session_routes.router)
    app.include_router(admin_printers_api_router)
    app.include_router(settings_api_router)
    app.include_router(sheet_types_router)
    app.include_router(sheets_router)
    app.include_router(sheet_print_routes.router)
    app.include_router(calibration_router)
    app.include_router(test_print_routes.router)
    app.include_router(capabilities_router)
    app.include_router(info_routes.router)

    # D1: the same process serves the web app. Mounted after every router so the
    # catch-all only sees what no API route claimed.
    add_security_headers(app)
    add_version_header(app, HUB_VERSION)
    mount_api_docs(app, get_settings().web_dist_dir)
    mount_spa(app, get_settings().web_dist_dir)

    return _LifespanManager(app)


app = create_app()
