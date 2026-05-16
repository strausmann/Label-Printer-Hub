"""FastAPI application entry point.

This module exposes the ASGI app that uvicorn runs in the container. It owns:

- The OpenAPI metadata (title, version, description, /openapi.json, /docs, /redoc)
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
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel, ConfigDict

import app.integrations as _integrations_init  # triggers integration plugin discovery
from app import __version__
from app.api.error_handlers import register_error_handlers
from app.api.routes import events as events_routes
from app.api.routes import jobs as jobs_routes
from app.api.routes import lookup as lookup_routes
from app.api.routes import printers as printers_routes
from app.api.routes import qr as qr_routes
from app.api.routes import templates as templates_routes
from app.api.routes import webhooks as webhooks_routes
from app.api.routes.print import router as print_router
from app.config import Settings, get_settings
from app.db.engine import async_session, engine
from app.db.lifespan import (
    ensure_printer_state,
    recover_inflight_jobs,
    run_migrations,
    seed_templates,
)
from app.integrations.registry import IntegrationRegistry
from app.printer_backends import BackendRegistry
from app.printer_backends.exceptions import SnmpDiscoveryError
from app.printer_backends.snmp_helper import query_model_pjl
from app.printer_models.registry import ModelRegistry
from app.services.event_bus import EventBus
from app.services.label_renderer import LabelRenderer
from app.services.lookup_service import AppLookupService
from app.services.print_queue import PrintQueue
from app.services.print_service import PrintService
from app.services.tape_registry import TapeRegistry
from app.services.template_loader import TemplateLoader

# Per ADR 0011 we pin the OpenAPI version explicitly rather than relying on
# FastAPI's default, so a FastAPI upgrade can't drift the API contract version.
OPENAPI_VERSION = "3.1.0"

# Build-info ENV vars are set by the Dockerfile at build time. Fall back to
# sensible defaults so local non-container runs and unit tests still work.
HUB_VERSION: str = os.environ.get("HUB_VERSION") or __version__
HUB_REVISION: str = os.environ.get("HUB_REVISION", "unknown")
HUB_BUILD_DATE: str = os.environ.get("HUB_BUILD_DATE", "1970-01-01T00:00:00Z")
HUB_REPO_URL: str = os.environ.get(
    "HUB_REPO_URL", "https://github.com/strausmann/label-printer-hub"
)

_SEED_TEMPLATES_DIR = Path(__file__).parent / "seed" / "templates"
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
    )
    return app.openapi_schema


def _build_backend(settings: Settings) -> Any:
    """Resolve and instantiate the configured printer backend.

    Calls BackendRegistry.ensure_discovered() to guarantee entry-points are
    loaded, then delegates construction to the factory's from_settings().
    """
    BackendRegistry.ensure_discovered()
    factory: Any = BackendRegistry.find_by_backend_id(settings.printer_backend)
    return factory.from_settings(settings)


async def _resolve_model_id(settings: Settings, host: str) -> str:
    """SNMP discovery first, fall back to settings.printer_model on failure.

    Sends a single SNMP GET for the Brother PJL OID. On success the PJL string
    is matched against ModelRegistry to return the canonical model_id.

    On SnmpDiscoveryError the fallback path is taken only when
    settings.printer_model is non-empty; otherwise the error is re-raised so
    the application fails fast rather than starting with an unknown printer.
    """
    try:
        pjl = await query_model_pjl(host, community=settings.printer_snmp_community)
    except SnmpDiscoveryError as exc:
        if settings.printer_model:
            _log.warning(
                "SNMP discovery failed (%s); falling back to printer_model=%r",
                exc,
                settings.printer_model,
            )
            return settings.printer_model
        raise
    driver_cls = ModelRegistry.find_by_pjl(pjl)
    return driver_cls.model_id


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Wire all application-level singletons into app.state.

    Startup sequence
    ----------------
    1. Load seed templates (idempotent, skipped when directory is absent).
    2. Discover model + backend plugins via entry_points (idempotent).
    3. Resolve the active model_id: SNMP-first when a host is configured and
       discovery is enabled; falls back to settings.printer_model on
       SnmpDiscoveryError (logged as a warning). Raises when neither source
       can supply a model_id.
    4. Instantiate the backend (factory.from_settings).
    5. Resolve driver class via ModelRegistry and bind it to the backend.
    6. Build the _PrinterLike via driver.make_queue_printer(tape_registry).
    7. Start the PrintQueue.
    8. Wire PrintService and helper state into app.state.

    Shutdown sequence
    -----------------
    queue.stop() drains in-flight jobs up to printer_queue_timeout_s, then
    cancels remaining workers forcibly.
    """
    settings = get_settings()

    # --- DB startup: migrations + recovery + seed + printer state --------
    await run_migrations()
    async with async_session() as s:
        await recover_inflight_jobs(s)
        await seed_templates(s, TemplateLoader)
        await ensure_printer_state(s)
    # ---------------------------------------------------------------------

    # Re-run integration plugin discovery if the registry was cleared (e.g. by
    # test fixtures that call IntegrationRegistry._plugins.clear()). This is
    # idempotent: _discover_plugins skips names that are already registered.
    if not IntegrationRegistry.names():
        _integrations_init._discover_plugins()

    if _SEED_TEMPLATES_DIR.exists():
        TemplateLoader.load_dir(_SEED_TEMPLATES_DIR)

    ModelRegistry.ensure_discovered()

    discovery_host = settings.pt750w_host or ""
    if discovery_host and settings.printer_discover_via_snmp:
        model_id = await _resolve_model_id(settings, discovery_host)
    else:
        model_id = settings.printer_model
        if not model_id:
            raise ValueError(
                "printer_model is empty and SNMP discovery is disabled "
                "(or pt750w_host is not configured). "
                "Set PRINTER_HUB_PRINTER_MODEL or enable SNMP discovery."
            )

    backend = _build_backend(settings)
    driver_cls: Any = ModelRegistry.find_by_model_id(model_id)
    driver: Any = driver_cls(backend=backend)

    tape_registry = TapeRegistry()
    printer = driver.make_queue_printer(tape_registry)
    queue = PrintQueue(printers=[printer])
    await queue.start()

    # --- SSE EventBus ---
    event_bus = EventBus(queue_size=settings.sse_queue_size)
    app.state.event_bus = event_bus
    # ----- end SSE ------

    app.state.print_queue = queue
    app.state.printer_id = printer.id
    app.state.printer_host = discovery_host
    app.state.printer_snmp_community = settings.printer_snmp_community
    app.state.print_service = PrintService(
        template_loader=TemplateLoader,
        renderer=LabelRenderer(),
        print_queue=queue,
        lookup_service=AppLookupService(),
        printer_id=printer.id,
        backend=backend,
    )

    try:
        yield
    finally:
        await queue.stop(timeout_s=settings.printer_queue_timeout_s)
        await engine.dispose()


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


def create_app() -> _LifespanManager:
    """Build the FastAPI app. Kept as a factory so tests can re-instantiate."""
    app = FastAPI(
        lifespan=lifespan,
        title="Label Printer Hub — backend",
        description=(
            "REST + SSE API for the Label Printer Hub backend. "
            "The Go frontend consumes the OpenAPI spec at /openapi.json via "
            "oapi-codegen; humans browse the interactive docs at /docs "
            "(Swagger UI) or /redoc."
        ),
        version=__version__,
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
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
            repository=HUB_REPO_URL,
            sse_active_subscribers=bus.total_subscriber_count() if bus else 0,
        )

    register_error_handlers(app)
    app.include_router(print_router)
    app.include_router(events_routes.router)
    app.include_router(printers_routes.router)
    app.include_router(templates_routes.router)
    app.include_router(jobs_routes.router)
    app.include_router(lookup_routes.router)
    app.include_router(webhooks_routes.router)
    app.include_router(qr_routes.router)
    return _LifespanManager(app)


app = create_app()
