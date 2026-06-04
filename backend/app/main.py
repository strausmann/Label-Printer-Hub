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
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated, Any, cast

# ---------------------------------------------------------------------------
# F3 — Early settings validation with a friendly error message.
#
# app.config.get_settings() is called at module load by engine.py (imported
# below) and by integration plugins (imported via app.integrations).  If an
# env var fails Pydantic validation (e.g. PRINTER_HUB_WEBHOOK_API_KEY is
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
    # Honour both the app-prefixed var (PRINTER_HUB_LOG_LEVEL, consistent with
    # all other Settings fields) and the short alias (LOG_LEVEL) that uvicorn
    # and other tools conventionally set.
    _debug = (
        os.environ.get("PRINTER_HUB_LOG_LEVEL", "").upper() == "DEBUG"
        or os.environ.get("LOG_LEVEL", "").upper() == "DEBUG"
    )
    if _debug:
        raise
    _lines = ["❌  Configuration error — fix the following before starting:\n"]
    for _err in _cfg_exc.errors():
        _field = ".".join(str(_p) for _p in _err["loc"])
        _msg = _err["msg"]
        _lines.append(f"   • PRINTER_HUB_{_field.upper()}: {_msg}\n")
    _lines.append("\n")
    _lines.append("Hint: see backend/.env.example for all supported variables.\n")
    sys.stderr.writelines(_lines)
    sys.exit(78)  # sysexits.h EX_CONFIG

from fastapi import Depends, FastAPI, Request, Response
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

import app.integrations as _integrations_init  # triggers integration plugin discovery
from app import __version__
from app.api.error_handlers import register_error_handlers
from app.api.routes import batch as batch_routes
from app.api.routes import batches as batches_routes
from app.api.routes import events as events_routes
from app.api.routes import jobs as jobs_routes
from app.api.routes import lookup as lookup_routes
from app.api.routes import printers as printers_routes
from app.api.routes import qr as qr_routes
from app.api.routes import templates as templates_routes
from app.api.routes import webhooks as webhooks_routes
from app.api.routes.admin_api_keys import router as admin_api_keys_router
from app.api.routes.print import router as print_router
from app.api.routes.templates_preview import router as templates_preview_router
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_read
from app.config import get_settings
from app.db.engine import async_session, engine
from app.db.lifespan import (
    ensure_printer_state,
    run_migrations,
    seed_templates,
    upsert_runtime_printers,
    verify_alembic_at_head,
)
from app.db.session import get_session
from app.integrations.registry import IntegrationRegistry
from app.printer_backends.exceptions import SnmpDiscoveryError
from app.printer_backends.snmp_helper import query_model_pjl
from app.printer_models.registry import ModelRegistry
from app.schemas.readiness import ReadinessResponse
from app.services.backend_router import BackendRouter
from app.services.cleanup_task import CleanupTask
from app.services.event_bus import EventBus
from app.services.job_store_sqlite import SQLiteJobStore
from app.services.label_renderer import LabelRenderer
from app.services.lookup_service import AppLookupService
from app.services.print_queue import PrintQueue
from app.services.print_service import PrintService
from app.services.printer_config_loader import PrinterConfigLoader
from app.services.producers.print_queue_producer import PrintQueueProducer
from app.services.producers.status_probe_producer import StatusProbeProducer
from app.services.producers.tape_change_producer import TapeChangeProducer
from app.services.readiness import build_readiness_response
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


async def _resolve_model_id_from_config(printer_cfg: Any) -> str:
    """SNMP discovery first, fall back to printer_cfg.model on failure.

    Phase 1i CA-1: ersetzt _resolve_model_id(settings, host) — liest SNMP-
    und Fallback-Parameter aus PrinterYAMLConfig statt aus entfernten
    Settings-Feldern.
    """
    host: str = printer_cfg.host
    community: str = printer_cfg.snmp.community
    model_fallback: str = printer_cfg.model

    if not host or not printer_cfg.snmp.discover:
        if not model_fallback:
            raise ValueError(
                "printer_cfg.model ist leer und SNMP-Discovery ist deaktiviert. "
                "Setze 'model' in printers.yaml oder aktiviere snmp.discover."
            )
        return model_fallback

    try:
        pjl = await query_model_pjl(host, community=community)
    except SnmpDiscoveryError as exc:
        if model_fallback:
            _log.warning(
                "SNMP discovery failed (%s); falling back to model=%r",
                exc,
                model_fallback,
            )
            return model_fallback
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

    # Phase 1i CA-1: Drucker-Konfiguration aus printers.yaml laden.
    # Dies ersetzt die entfernten Settings-Felder (printer_model, pt750w_host, …).
    # Der Loader ist ein Klassenattribut-Cache — load_file() befüllt ihn atomic.
    _printers_config_path = Path(settings.printers_config)
    PrinterConfigLoader.load_file(_printers_config_path)
    _printer_configs = PrinterConfigLoader.all()
    if not _printer_configs:
        raise RuntimeError(
            f"printers.yaml unter {_printers_config_path} enthält keine Drucker. "
            "Mindestens ein Drucker-Eintrag ist erforderlich."
        )
    # --- DB startup: migrations first, then in-memory state, then DB writes ---
    await run_migrations()
    await verify_alembic_at_head(settings)

    # 2. Plugin registries (idempotent — skips already-registered names).
    # Must run BEFORE TemplateLoader.load_dir() because load_dir validates
    # each template's `app` field against IntegrationRegistry.  Re-run if the
    # registry was cleared (e.g. by test fixtures that call
    # IntegrationRegistry._plugins.clear()).
    if not IntegrationRegistry.names():
        _integrations_init._discover_plugins()

    ModelRegistry.ensure_discovered()

    # 3. Populate in-memory template cache BEFORE any DB writes that depend on it.
    # load_dir must come after plugin discovery (above) and before seed_templates
    # (below) — the seed step reads from the cache that load_dir populates.
    if _SEED_TEMPLATES_DIR.exists():
        TemplateLoader.load_dir(_SEED_TEMPLATES_DIR)
    else:
        raise RuntimeError(
            f"Seed templates directory not found: {_SEED_TEMPLATES_DIR}. "
            "The application package is incomplete — reinstall or rebuild the image."
        )

    # 4. DB-bound init — plugin registry and template cache are populated.
    async with async_session() as s:
        # Phase 2: recover_inflight_jobs() entfernt (Spec R1-C1) —
        # PrintQueue.start() übernimmt Recovery mit korrekter QUEUED/PRINTING-Differenzierung.
        await seed_templates(s, TemplateLoader)
        db_printer_ids = await upsert_runtime_printers(s, _printer_configs)
        await ensure_printer_state(s)
        # upsert_runtime_printers already commits; ensure_printer_state may need commit
        await s.commit()
    # -------------------------------------------------------------------------

    # Phase 2: JobStore + CleanupTask
    # 'async_session' ist die async_sessionmaker aus app.db.engine (R2-M5)
    job_store = SQLiteJobStore(async_session)

    cleanup_task = CleanupTask(
        store=job_store,
        retention_days=settings.job_retention_days,
    )
    await cleanup_task.start()
    app.state.cleanup_task = cleanup_task

    # Phase 1i H — Multi-Printer-Wiring (Task 7b)
    # Real BackendRouter (from Task 5) — baut Backends aus PrinterYAMLConfig.
    backend_router = BackendRouter(_printer_configs)
    app.state.backend_router = backend_router

    tape_registry = TapeRegistry()
    queue_printers: list[Any] = []
    slug_to_printer_id: dict[Any, Any] = {}

    for cfg, printer_id in zip(_printer_configs, db_printer_ids, strict=True):
        # Phase 1i CA-1: Model-Auflösung pro Drucker — SNMP-first mit Fallback.
        model_id = await _resolve_model_id_from_config(cfg)
        backend = backend_router.get(cfg.slug)
        driver_cls: Any = ModelRegistry.find_by_model_id(model_id)
        driver: Any = driver_cls(backend=backend)
        # R4-A-C5-Fix: make_queue_printer wird von Task 8 (QLSeriesModel) implementiert.
        # Lifespan-Tests für QL-Konfigurationen mocken diese Methode via unittest.mock.patch.
        printer = driver.make_queue_printer(tape_registry, printer_id=printer_id)
        queue_printers.append(printer)
        slug_to_printer_id[cfg.slug] = printer.id

    # --- SSE EventBus ---
    event_bus = EventBus(queue_size=settings.sse_queue_size)
    app.state.event_bus = event_bus
    # ----- end SSE ------

    # Shared LabelRenderer reused by both PrintService, preview endpoint and
    # PrintQueue Recovery. Constructing it once avoids repeated font-loading
    # overhead on every POST /api/render/preview request.
    # Moved before PrintQueue construction so Recovery in queue.start() can use it.
    shared_renderer = LabelRenderer()
    app.state.label_renderer = shared_renderer

    pq_producer = PrintQueueProducer(bus=event_bus)
    queue = PrintQueue(
        printers=queue_printers,
        on_state_change=pq_producer.handle_transition,
        store=job_store,
        renderer=shared_renderer,
        loader=TemplateLoader,
    )
    await queue.start()

    # StatusProbeProducer pro Drucker — R4-MA1-Fix Degraded-Start:
    # Probe-Fehler werden geloggt, Hub startet trotzdem.
    status_producers: list[StatusProbeProducer] = []
    for cfg in _printer_configs:
        _discovery_host = cfg.host or ""
        if _discovery_host and cfg.snmp.discover:
            _printer_id = slug_to_printer_id[cfg.slug]
            try:
                # F7: driver beschreibt Tape-Klassen via describe_tape() —
                # TapeChangeProducer nutzt driver statt tape_registry.lookup_pt().
                # Im Multi-Printer-Modus übergeben wir model=None als Fallback
                # da wir keinen direkten Driver-Zugang pro-Drucker im Producer-Kontext haben.
                # Task 8 kann dies verfeinern wenn QL-Driver describe_tape() implementiert.
                tape_producer = TapeChangeProducer(
                    bus=event_bus,
                    tape_registry=tape_registry,
                    model=None,
                )
                producer = StatusProbeProducer(
                    bus=event_bus,
                    printer_id=str(_printer_id),
                    host=_discovery_host,
                    interval_s=settings.sse_probe_interval_s,
                    community=cfg.snmp.community,
                    tape_change_producer=tape_producer,
                )
                await producer.start()
                status_producers.append(producer)
            except Exception as probe_exc:
                _log.warning(
                    "Degraded-Start: StatusProbeProducer für slug=%s (host=%s) fehlgeschlagen: %s. "
                    "Hub startet ohne diesen Drucker — SNMP-Status bleibt unreachable.",
                    cfg.slug,
                    _discovery_host,
                    probe_exc,
                )

    app.state.print_queue = queue
    app.state.slug_to_printer_id = slug_to_printer_id

    # R4-A-C2-Fix (Volle Multi-Printer): PrintService-Map — eine Instanz pro Drucker.
    for cfg, printer_id in zip(_printer_configs, db_printer_ids, strict=True):
        printer_backend = backend_router.get(cfg.slug)
        assert printer_backend is not None, (
            f"BackendRouter missing backend for slug={cfg.slug!r} — "
            "should have been registered during BackendRouter.__init__"
        )
        # cast: PrinterBackend satisfies _BackendProto at runtime (both concrete
        # backends implement preflight_check). _BackendProto is a private Protocol
        # in print_service and cannot be imported here for a clean annotation.
        service = PrintService(
            template_loader=TemplateLoader,
            renderer=shared_renderer,
            print_queue=queue,
            lookup_service=AppLookupService(),
            printer_id=printer_id,
            backend=cast(Any, printer_backend),
            store=job_store,
        )
        backend_router.register_service(cfg.slug, service)

    # Backward-Compat: app.state.print_service und app.state.printer_id zeigen
    # auf den ersten konfigurierten Drucker — für Pfade die noch nicht auf
    # service_for() migriert sind (z.B. POST /print Einzel-Druck-Route).
    first_cfg = _printer_configs[0]
    first_printer_id = slug_to_printer_id[first_cfg.slug]
    app.state.printer_id = first_printer_id
    app.state.printer_host = first_cfg.host or ""
    app.state.printer_snmp_community = first_cfg.snmp.community
    app.state.print_service = backend_router.service_for(first_cfg.slug)

    try:
        yield
    finally:
        for sp in status_producers:
            await sp.stop()
        max_timeout = max(
            (c.queue.timeout_s for c in _printer_configs),
            default=30,
        )
        await queue.stop(timeout_s=float(max_timeout))
        await cleanup_task.stop()
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
            sse_active_subscribers=bus.distinct_subscriber_count() if bus else 0,
        )

    @app.get(
        "/readiness",
        response_model=ReadinessResponse,
        tags=["meta"],
        summary="Readiness probe",
        description=(
            "Deep readiness check: database connectivity, alembic migration "
            "state, template seed, printer wiring, SNMP probe recency, "
            "print-queue liveness, and SSE subscriber capacity. "
            "Returns 200 with status in {ready, degraded} when all critical "
            "checks pass; 503 with status=not-ready when any critical check "
            "(database / alembic / template_seed) fails."
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
        )
        if body.status == "not-ready":
            response.status_code = 503
        return body

    register_error_handlers(app)
    app.include_router(print_router)
    app.include_router(batch_routes.router)
    app.include_router(batches_routes.router)
    app.include_router(events_routes.router)
    app.include_router(printers_routes.router)
    app.include_router(templates_routes.router)
    app.include_router(templates_routes.render_router)
    app.include_router(jobs_routes.router)
    app.include_router(lookup_routes.router)
    app.include_router(webhooks_routes.router)
    app.include_router(qr_routes.router)
    app.include_router(admin_api_keys_router)
    app.include_router(templates_preview_router)

    _static_dir = Path(__file__).parent / "static"
    if _static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

    return _LifespanManager(app)


app = create_app()
