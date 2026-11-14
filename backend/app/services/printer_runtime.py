# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""PrinterRuntime (#224): the one code path that wires a printer into the running hub.

The lifespan attaches every enabled printer at startup; an admin change calls ``reconcile``
(Task 7). Both go through ``attach`` and ``detach``, so a printer wired at runtime is wired
exactly as one wired at startup.

What a wired printer owns:

- tape printer: its ``BackendRouter`` entry and ``PrintService``, the model driver, the queue
  printer, and (with ``snmp.discover``) a ``StatusProbeProducer`` with a ``TapeChangeProducer``;
- page (IPP) printer: an ``IppClient`` for page jobs, an ``IppPrinterState``, the
  ``IppPagePrinter`` in the queue, and an ``IppStatusProducer`` with its own client.

Ordering rules:

- one ``asyncio.Lock`` per printer id serializes attach, detach and reconcile of that printer
  (the outer serialization; the queue serializes its own add and remove too);
- a producer is stopped before its printer leaves the queue, so it never reaches the queue's
  pause control for a printer the queue no longer knows (``resume_printer`` raises
  ``KeyError`` then);
- producers run only after ``start()``; until then ``attach`` builds them without starting,
  so startup never waits for a probe (both producers probe first, then sleep);
- a page printer without a running status producer (it could not be built or started) is
  attached degraded: the queue holds it paused with the reason ``status-unavailable`` (nothing
  could ever start its jobs or lift a hardware pause), and the runtime retries the producer
  start with the probe backoff. A successful start lifts that pause only, never a user's;
- a failure after a printer joined the queue takes it out again, so a failed attach leaves no
  worker behind.

Logs name the printer slug and the error class, never a URI or host.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import UUID

from sqlalchemy import select
from sqlmodel import col

from app.models.printer import Printer
from app.models.printer_state import PrinterState
from app.models.printer_tray import PrinterTray
from app.printer_backends.exceptions import SnmpDiscoveryError
from app.printer_backends.ipp.client import IppClient
from app.printer_backends.snmp_helper import ObservedIdentity, query_model_pjl
from app.printer_models.registry import ModelRegistry
from app.repositories import printer_identity as identity_repo
from app.schemas.label_layout import parse_layout_defaults
from app.services.backend_router import (
    BackendRouter,
    CutDefaults,
    PrinterYAMLConfig,
    QueueConfig,
    SNMPConfig,
)
from app.services.event_bus import BusEvent
from app.services.hardware_identity import IdentityOutcome, record_identity
from app.services.lookup_service import AppLookupService
from app.services.page_jobs import IppPagePrinter
from app.services.print_service import PrintService
from app.services.producers.ipp_status_producer import (
    MAX_BACKOFF_DOUBLINGS,
    MAX_BACKOFF_S,
    IppPrinterState,
    IppStatusProducer,
)
from app.services.producers.status_probe_producer import StatusProbeProducer
from app.services.producers.tape_change_producer import TapeChangeProducer
from app.services.producers.tape_description import TapeDescription
from app.services.roll_tracker import RollTracker
from app.services.tape_registry import TapeRegistry

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.config import Settings
    from app.services.print_queue import PrintQueue

_log = logging.getLogger(__name__)

# At most this many IPP printers are probed at the same moment.
_IPP_PROBE_CONCURRENCY = 4
_DEFAULT_SHUTDOWN_WAIT_S = 30
# The pause reason of a page printer whose status producer is not running (265-06).
STATUS_UNAVAILABLE = "status-unavailable"


def shutdown_wait_s(tape_timeouts_s: Sequence[int], page_timeouts_s: Sequence[int]) -> float:
    """How long ``queue.stop`` waits for the workers: the largest queue timeout of any worker,
    tape or page, so no printer's worker is cut off before its own request limit.
    """
    return float(max([*tape_timeouts_s, *page_timeouts_s], default=_DEFAULT_SHUTDOWN_WAIT_S))


def tape_config(p: Any) -> PrinterYAMLConfig:
    """The runtime config of a stored tape printer (missing connection fields get defaults)."""
    conn: dict[str, Any] = p.connection or {}
    snmp_raw: dict[str, Any] = conn.get("snmp", {}) or {}
    return PrinterYAMLConfig.model_construct(
        slug=p.slug,
        name=p.name,
        backend=p.backend,
        model=p.model,
        host=conn.get("host", ""),
        port=int(conn.get("port", 9100)),
        snmp=SNMPConfig(
            discover=snmp_raw.get("discover", False),
            community=snmp_raw.get("community", "public"),
        ),
        queue=QueueConfig(timeout_s=getattr(p, "queue_timeout_s", 30)),
        cut_defaults=CutDefaults(
            half_cut=getattr(p, "cut_defaults_half_cut", False),
            cut_at_end=True,
        ),
    )


async def _resolve_model_id_from_config(printer_cfg: PrinterYAMLConfig) -> str:
    """SNMP discovery first, fall back to ``printer_cfg.model`` on failure.

    Raises ``ValueError`` when neither source has a model, ``SnmpDiscoveryError`` when the
    discovery fails and there is no fallback.
    """
    host: str = printer_cfg.host
    community: str = printer_cfg.snmp.community
    model_fallback: str = printer_cfg.model

    if not host or not printer_cfg.snmp.discover:
        if not model_fallback:
            raise ValueError(
                "printer_cfg.model is empty and SNMP discovery is off. "
                "Set 'model' on the printer or enable snmp.discover."
            )
        return model_fallback

    try:
        pjl = await query_model_pjl(host, community=community)
    except SnmpDiscoveryError as exc:
        if model_fallback:
            _log.warning(
                "SNMP discovery failed for slug=%s (%s); falling back to model=%r",
                printer_cfg.slug,
                type(exc).__name__,
                model_fallback,
            )
            return model_fallback
        raise
    driver_cls = ModelRegistry.find_by_pjl(pjl)
    return driver_cls.model_id


def wiring_key(printer: Printer, *, tray_keys: Sequence[str] = ()) -> tuple[object, ...]:
    """What the wiring of *printer* depends on; equal keys need no re-wire (Task 7).

    Name, label and cut defaults are not in it (cut defaults come with each request), nor
    the layout defaults (#258): ``reconcile`` hands a changed value to the service.
    ``queue_timeout_s`` is in it for IPP printers only: both IPP clients take it at
    construction; a tape printer uses it only for the detach and shutdown waits, and
    ``reconcile`` takes a changed value over without a re-wire.
    *tray_keys* are the page printer's tray keys (the trays live in their own table).
    The SNMP settings of a tape printer (discovery switch, community) are part of the
    connection JSON (element 3), so a change of either changes the key.
    """
    is_ipp = printer.backend == "ipp"
    conn = dict(printer.connection or {})
    return (
        bool(printer.enabled),
        printer.backend,
        json.dumps(conn, sort_keys=True, default=str),
        printer.model,
        tuple(sorted(tray_keys)) if is_ipp else (),
        int(printer.queue_timeout_s) if is_ipp else None,
    )


def _key_digest(key: tuple[object, ...]) -> str:
    """A SHA-256 of *key*: the key holds the SNMP community and the IPP URI, so the runtime
    keeps only the digest (never logged, never returned)."""
    return hashlib.sha256(repr(key).encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@dataclass
class _Wiring:
    """Everything the runtime built for one attached printer."""

    printer_id: UUID
    slug: str
    kind: Literal["tape", "page"]
    created_at: datetime
    queue_timeout_s: int
    key_digest: str  # ``_key_digest(wiring_key(...))``; the key itself carries secrets
    producer: StatusProbeProducer | IppStatusProducer | None = None
    # tape
    driver: Any = None
    service: PrintService | None = None
    # page
    page_client: IppClient | None = None
    state: IppPrinterState | None = None
    # Builds a fresh status producer (with its own client); set for page printers only.
    make_producer: Callable[[], Awaitable[IppStatusProducer]] | None = None


class PrinterRuntime:
    """Attaches and detaches printers; owns their backends, clients, states and producers.

    Reads from ``app.state`` (set by the lifespan before the first ``attach``):
    ``print_queue``, ``event_bus``, ``engine`` (the shared ``LayoutEngine``), ``job_store``
    and the optional ``ipp_transport_factory`` (tests). Writes ``backend_router``,
    ``slug_to_printer_id``, ``ipp_printer_states`` and the back-compat fields
    ``print_service`` / ``printer_id`` (the first wired tape printer by ``created_at``).

    ``roll_tracker`` is the one tracker of this runtime, handed to every tape producer (it
    takes ``event_bus`` from ``app.state`` at construction); ``reconciles`` holds the running
    reconcile tasks of the admin routes (strong references, per app).
    """

    def __init__(
        self,
        app: FastAPI,
        settings: Settings,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._app = app
        self._settings = settings
        self._session_factory = session_factory
        self._locks: dict[UUID, asyncio.Lock] = {}
        self._lock_users: dict[UUID, int] = {}
        self._retries: dict[UUID, asyncio.Task[None]] = {}
        self.reconciles: set[asyncio.Task[None]] = set()
        self.roll_tracker = RollTracker(getattr(app.state, "event_bus", None), session_factory)
        self._wired: dict[UUID, _Wiring] = {}
        self._ipp_limiter = asyncio.Semaphore(_IPP_PROBE_CONCURRENCY)
        self._tape_registry = TapeRegistry()
        self._started = False
        self._closed = False
        self._router = BackendRouter([])
        self._slug_to_id: dict[str, UUID] = {}
        self._ipp_states: dict[UUID, IppPrinterState] = {}
        state = app.state
        state.backend_router = self._router
        state.slug_to_printer_id = self._slug_to_id
        state.ipp_printer_states = self._ipp_states
        state.print_service = None
        state.printer_id = None

    # ------------------------------------------------------------------ public

    async def attach(self, printer: Printer, *, fatal: bool = False) -> None:
        """Wire *printer* (a disabled one is not wired). An attached id is re-wired.

        ``fatal=True`` (lifespan only): an unresolvable tape model raises, as before #224.
        Otherwise a wiring failure is logged (slug and error class) and the printer stays
        detached. Re-wiring an attached id detaches it first, and a store failure there
        (``remove_printer`` ending the in-flight job) can still raise; ``reconcile`` catches it.
        """
        if self._closed:
            return
        async with self._serialized(printer.id):
            if self._is_closed():  # stop() may have run while this waited for the lock
                return
            await self._attach_locked(printer, fatal=fatal)

    async def detach(self, printer_id: UUID) -> None:
        """Unwire a printer: stop its producer, take it out of the queue, close its clients.

        A job printing on it may finish within its queue timeout; waiting jobs stay queued.
        Unknown ids are a no-op, and so is any call after ``stop()`` (the queue is stopped and
        ``stop()`` closed every client).
        """
        if self._closed:
            return
        async with self._serialized(printer_id):
            if self._is_closed():  # stop() may have run while this waited for the lock
                return
            await self._detach_locked(printer_id)

    async def reconcile(self, printer_id: UUID) -> None:
        """Bring the wiring of *printer_id* in line with its stored row (the admin routes).

        No-op after ``stop()``. A missing or disabled row ends detached. When the row's
        ``wiring_key`` (with its tray keys) equals the attached one, nothing is re-wired: a
        rename keeps the producer, the clients and any job in flight; only the tape queue
        timeout, which is not in the key, is taken over.

        Does not raise on a wiring or store failure: it logs the printer id and the error
        class and leaves the printer detached (no producer, unknown to the queue), so the
        status endpoint shows the last probe with its age and new jobs are refused (409).
        Cancellation still propagates (the admin routes shield the call).
        """
        if self._closed:
            return
        async with self._serialized(printer_id):
            if self._is_closed():  # stop() may have run while this waited for the lock
                return
            try:
                await self._reconcile_locked(printer_id)
            except Exception as exc:
                _log.warning(
                    "Printer id=%s not reconciled (%s); left detached",
                    printer_id,
                    type(exc).__name__,
                )
                try:
                    await self._detach_locked(printer_id)
                except Exception as exc2:  # the wiring is already dropped by its finally
                    _log.warning(
                        "Printer id=%s detach after a failed reconcile failed (%s)",
                        printer_id,
                        type(exc2).__name__,
                    )

    async def _reconcile_locked(self, printer_id: UUID) -> None:
        async with self._sessions()() as session:
            row = await session.get(Printer, printer_id)
        wiring = self._wired.get(printer_id)
        if row is not None and row.enabled and wiring is not None:
            trays = await self._tray_keys(printer_id) if row.backend == "ipp" else []
            same_key = _key_digest(wiring_key(row, tray_keys=trays)) == wiring.key_digest
            # 263-23: an equal key is no reason to keep a printer that should be polled but
            # has no producer (its start failed); re-wiring gives it a fresh one.
            if same_key and not self._producer_missing(row, wiring):
                # Not in the key for tape printers (only the shutdown and detach waits read
                # it), so take it over here or those waits would use the old value.
                wiring.queue_timeout_s = int(row.queue_timeout_s)
                # #258: the layout defaults are read per job, so an edit needs no re-wire.
                if wiring.service is not None:
                    wiring.service.set_layout_defaults(parse_layout_defaults(row.layout_defaults))
                return
        await self._detach_locked(printer_id)
        if row is not None and row.enabled:
            await self._attach_locked(row, fatal=False)

    @staticmethod
    def _producer_missing(row: Printer, wiring: _Wiring) -> bool:
        """True iff *row* is polled by design but *wiring* has no producer."""
        if wiring.producer is not None:
            return False
        if row.backend == "ipp":
            return True
        cfg = tape_config(row)
        return bool(cfg.host and cfg.snmp.discover)

    async def start(self) -> None:
        """Start the producers of every attached printer; later attaches start theirs at once."""
        if self._started or self._closed:
            return
        self._started = True
        for wiring in list(self._wired.values()):
            await self._start_producer(wiring)

    async def stop(self) -> None:
        """Stop producers, stop the queue once (longest attached timeout), close page clients.

        Later ``attach``/``reconcile`` calls are no-ops. A running attach or detach finishes
        first. Printers are not removed one by one. The page clients are closed even when the
        queue stop raises (the error still propagates).
        """
        if self._closed:
            return
        self._closed = True
        for lock in list(self._locks.values()):
            async with lock:
                pass
        for printer_id in list(self._retries):
            await self._cancel_retry(printer_id)
        wirings = list(self._wired.values())
        try:
            for wiring in wirings:
                await self._stop_producer(wiring)
            await self._queue().stop(
                timeout_s=shutdown_wait_s(
                    [w.queue_timeout_s for w in wirings if w.kind == "tape"],
                    [w.queue_timeout_s for w in wirings if w.kind == "page"],
                )
            )
        finally:  # 263-16: a failing queue stop must not leave the page clients open
            for wiring in wirings:
                await self._close_page_client(wiring)

    def describe_tape_for(self, printer_id: UUID, width_mm: int) -> TapeDescription:
        """The attached model driver's tape label; the generic ``"{N}mm"`` otherwise."""
        wiring = self._wired.get(printer_id)
        if wiring is not None and wiring.driver is not None:
            return cast(TapeDescription, wiring.driver.describe_tape(width_mm))
        return TapeDescription(label=f"{width_mm}mm")

    def is_polled(self, printer_id: UUID) -> bool:
        """True iff a status producer runs for *printer_id*."""
        wiring = self._wired.get(printer_id)
        return (
            self._started
            and not self._closed
            and wiring is not None
            and (wiring.producer is not None)
        )

    def print_service_for(self, printer_id: UUID) -> PrintService | None:
        """The ``PrintService`` of an attached tape printer, else ``None``."""
        wiring = self._wired.get(printer_id)
        return wiring.service if wiring is not None else None

    # ------------------------------------------------------------------ attach

    async def _attach_locked(self, printer: Printer, *, fatal: bool) -> None:
        if printer.id in self._wired:
            await self._detach_locked(printer.id)
        if not printer.enabled:
            return
        paused_since = await self._paused_since(printer.id)
        await self._load_identity_hold(printer.id)  # #231: before any worker for it can run
        if printer.backend == "ipp":
            wiring = await self._attach_page(printer, paused_since)
        else:
            wiring = await self._attach_tape(printer, paused_since, fatal=fatal)
        if wiring is None:
            return
        self._wired[printer.id] = wiring
        try:
            self._refresh_backcompat()
            if wiring.make_producer is not None and wiring.producer is None:
                # Built-failed page producer: held before any worker can run a job (263-77's
                # guard below covers a failure here too).
                await self._pause_status_unavailable(wiring)
            if self._started:
                await self._start_producer(wiring)
        except BaseException:
            # 263-77: the printer already joined the queue; a later failure takes it out again.
            with contextlib.suppress(Exception):
                await self._detach_locked(printer.id)
            raise

    async def _attach_tape(
        self, printer: Printer, paused_since: datetime | None, *, fatal: bool
    ) -> _Wiring | None:
        cfg = tape_config(printer)
        try:
            model_id = await _resolve_model_id_from_config(cfg)
            driver_cls: Any = ModelRegistry.find_by_model_id(model_id)
        except Exception as exc:
            if fatal:
                raise
            _log.warning(
                "Printer slug=%s not wired: tape model unresolved (%s)",
                cfg.slug,
                type(exc).__name__,
            )
            return None
        queue = self._queue()
        registered = False
        try:
            self._router.register(cfg)
            registered = True
            backend = self._router.get(cfg.slug)
            driver: Any = driver_cls(backend=backend)
            queue_printer = driver.make_queue_printer(self._tape_registry, printer_id=printer.id)
            service = PrintService(
                engine=self._app.state.engine,
                queue=queue,
                lookup_service=AppLookupService(),
                printer_id=printer.id,
                printer_slug=cfg.slug,
                backend=cast(Any, backend),
                store=self._app.state.job_store,
                layout_defaults=parse_layout_defaults(printer.layout_defaults),
            )
            self._router.register_service(cfg.slug, service)
            if self._started:
                # A page printer re-wired as a tape printer: its page job at the printer is
                # never resumed now (ruling a); settle it instead of at the next restart.
                await queue.settle_page_jobs_in_flight(printer.id)
            await queue.add_printer(queue_printer, paused_since=paused_since)
        except Exception as exc:
            if registered:
                self._router.unregister(cfg.slug)
            if fatal:
                raise
            _log.warning("Printer slug=%s not wired (%s)", cfg.slug, type(exc).__name__)
            return None
        self._slug_to_id[cfg.slug] = printer.id
        return _Wiring(
            printer_id=printer.id,
            slug=cfg.slug,
            kind="tape",
            created_at=_aware(printer.created_at),
            queue_timeout_s=int(printer.queue_timeout_s),
            key_digest=_key_digest(wiring_key(printer)),
            producer=self._tape_producer(cfg, printer.id),
            driver=driver,
            service=service,
        )

    def _tape_producer(
        self, cfg: PrinterYAMLConfig, printer_id: UUID
    ) -> StatusProbeProducer | None:
        if not (cfg.host and cfg.snmp.discover):
            return None
        try:
            tape_producer = TapeChangeProducer(
                bus=self._app.state.event_bus,
                tape_registry=self._tape_registry,
                model=None,
            )
            return StatusProbeProducer(
                bus=self._app.state.event_bus,
                printer_id=str(printer_id),
                host=cfg.host,
                interval_s=self._settings.sse_probe_interval_s,
                community=cfg.snmp.community,
                tape_change_producer=tape_producer,
                roll_tracker=self.roll_tracker,
                identity_sink=self._identity_sink,
            )
        except Exception as exc:
            _log.warning(
                "Degraded: status producer for slug=%s not built (%s)",
                cfg.slug,
                type(exc).__name__,
            )
            return None

    async def _attach_page(self, printer: Printer, paused_since: datetime | None) -> _Wiring | None:
        conn: dict[str, Any] = printer.connection or {}
        uri = str(conn.get("uri", ""))
        tls_verify = bool(conn.get("tls_verify", True))
        queue_timeout = float(printer.queue_timeout_s)
        factory = getattr(self._app.state, "ipp_transport_factory", None)
        # 263-77: read before anything is built or added; a failure here leaves nothing behind.
        tray_keys = await self._tray_keys(printer.id)
        try:
            page_client = IppClient(
                uri,
                tls_verify=tls_verify,
                query_timeout_s=min(5.0, queue_timeout),
                upload_timeout_s=queue_timeout,
                transport=factory(uri) if factory else None,
            )
        except Exception as exc:
            # A bad stored URI must not stop the hub (degraded, at startup and at runtime).
            _log.warning(
                "Degraded: IPP printer slug=%s not wired (%s)", printer.slug, type(exc).__name__
            )
            return None
        state = IppPrinterState()
        probe_timeout = min(5.0, queue_timeout)

        async def make_producer() -> IppStatusProducer:
            client = IppClient(
                uri,
                tls_verify=tls_verify,
                query_timeout_s=probe_timeout,
                upload_timeout_s=probe_timeout,
                transport=factory(uri) if factory else None,
            )
            try:
                return IppStatusProducer(
                    bus=self._app.state.event_bus,
                    printer_id=printer.id,
                    client=client,
                    session_factory=self._sessions(),
                    state=state,
                    pause_control=self._queue(),
                    interval_s=self._settings.sse_probe_interval_s,
                    limiter=self._ipp_limiter,
                    log_name=printer.slug,
                    identity_sink=self._identity_sink,
                )
            except BaseException:
                # L2: the producer owns the client only once it exists; a retry loop must not
                # leak one client per failed build.
                with contextlib.suppress(Exception):
                    await client.aclose()
                raise

        producer: IppStatusProducer | None
        try:
            producer = await make_producer()
        except Exception as exc:
            _log.warning(
                "Degraded: IPP status producer for slug=%s not built (%s)",
                printer.slug,
                type(exc).__name__,
            )
            producer = None
        try:
            await self._queue().add_page_printer(
                IppPagePrinter(id=printer.id, client=page_client, state=state),
                paused_since=paused_since,
            )
        except Exception as exc:
            _log.warning(
                "Degraded: IPP printer slug=%s not wired (%s)", printer.slug, type(exc).__name__
            )
            if producer is not None:
                await self._stop_producer_quietly(producer, printer.slug)
            with contextlib.suppress(Exception):
                await page_client.aclose()
            return None
        self._ipp_states[printer.id] = state
        return _Wiring(
            printer_id=printer.id,
            slug=printer.slug,
            kind="page",
            created_at=_aware(printer.created_at),
            queue_timeout_s=int(printer.queue_timeout_s),
            key_digest=_key_digest(wiring_key(printer, tray_keys=tray_keys)),
            producer=producer,
            page_client=page_client,
            state=state,
            make_producer=make_producer,
        )

    # ------------------------------------------------------------------ detach

    async def _detach_locked(self, printer_id: UUID) -> None:
        wiring = self._wired.pop(printer_id, None)
        if wiring is None:
            return
        try:
            await self._cancel_retry(printer_id)
            # The producer first: once stopped it cannot reach the queue's pause control
            # for a printer the queue has forgotten (ruling b).
            await self._stop_producer(wiring)
            await self._queue().remove_printer(printer_id, timeout_s=wiring.queue_timeout_s)
        finally:
            if wiring.kind == "tape":
                self.roll_tracker.forget(printer_id)
                self._router.unregister(wiring.slug)
                if self._slug_to_id.get(wiring.slug) == printer_id:
                    del self._slug_to_id[wiring.slug]
            else:
                self._ipp_states.pop(printer_id, None)
                await self._close_page_client(wiring)
            self._refresh_backcompat()

    # ------------------------------------------------------------------ helpers

    def _is_closed(self) -> bool:
        return self._closed

    @contextlib.asynccontextmanager
    async def _serialized(self, printer_id: UUID) -> AsyncIterator[None]:
        """Hold the per-printer lock; the entry is dropped when the last user leaves (263-17).

        Counted by users, not by ``Lock.locked()``: a released lock with a waiter reads
        unlocked until the waiter runs, and dropping it then would let a newcomer take a second
        lock for the same printer.
        """
        lock = self._locks.get(printer_id)
        if lock is None:
            lock = self._locks[printer_id] = asyncio.Lock()
        self._lock_users[printer_id] = self._lock_users.get(printer_id, 0) + 1
        try:
            async with lock:
                yield
        finally:
            users = self._lock_users[printer_id] - 1
            if users:
                self._lock_users[printer_id] = users
            else:
                del self._lock_users[printer_id]
                self._locks.pop(printer_id, None)

    async def _identity_sink(self, printer_id: UUID, observed: ObservedIdentity) -> IdentityOutcome:
        """The sink both status producers call after a successful probe (#231).

        A ``seen`` reading while the queue still holds the printer means the hold outlived its
        mismatch: a clear whose re-read failed keeps the hold (fail closed), and no later probe
        would announce a clear again. Re-sync it from the database then (263-48); the re-read
        only runs while a hold is set, and releases it only when verified.
        """
        outcome = await record_identity(
            printer_id,
            observed,
            datetime.now(UTC),
            session_factory=self._sessions(),
            on_mismatch=self._mismatch_changed,
        )
        if outcome in ("seen", "kind_upgraded") and self._queue().is_identity_held(printer_id):
            try:
                await self._mismatch_changed(printer_id, None)
            except Exception as exc:  # as ``record_identity``'s own hook call: never raises
                _log.warning("identity hold re-sync failed (%s)", type(exc).__name__)
        return outcome

    async def _mismatch_changed(self, printer_id: UUID, since: datetime | None) -> None:
        """A mismatch started or ended: hold or release, and tell the SSE readers.

        The state is re-read from the database, not taken from the direction of the call, so
        two hooks that interleave cannot leave the hold and the database disagreeing. The event
        carries the flag and its start, never an identity value."""
        try:
            current = await self._read_mismatch_since(printer_id)
        except Exception as exc:
            # Fail closed: an unverified answer may set a hold, never release one.
            _log.warning(
                "identity mismatch re-read failed for %s (%s)", printer_id, type(exc).__name__
            )
            if since is None:
                return  # a clear that cannot be verified leaves the hold as it is
            current = since
        queue = self._queue()
        changed = queue.is_identity_held(printer_id) != (current is not None)
        queue.set_identity_hold(printer_id, current is not None)
        bus = getattr(self._app.state, "event_bus", None)
        if bus is None or not changed:
            return  # a repeated call (the probe re-announces an unchanged mismatch) is silent
        channel = f"printer:{printer_id}:state"
        data: dict[str, Any] = {"mismatch": current is not None}
        if current is not None:
            data["since"] = _aware(current).isoformat()
        bus.publish(
            channel,
            BusEvent(
                channel=channel,
                event_id=bus.next_event_id(channel),
                event_type="printer.identity_mismatch",
                timestamp=datetime.now(UTC),
                data=data,
            ),
        )

    async def resync_identity_hold(self, printer_id: UUID) -> None:
        """Set the hold (and tell the readers) from the database, after an admin resolved a swap.

        Same fail-closed path as a probe: the state is re-read, and a read that fails never
        releases a hold. A different device seen right after the commit keeps the hold."""
        await self._mismatch_changed(printer_id, None)

    async def _read_mismatch_since(self, printer_id: UUID) -> datetime | None:
        async with self._sessions()() as session:
            row = await identity_repo.get(session, printer_id)
        return None if row is None else row.mismatch_since

    async def _load_identity_hold(self, printer_id: UUID) -> None:
        """A mismatch that began before the hub stopped is held again when the printer attaches.

        Called before the printer joins the queue: a running queue starts the worker (and
        recovers waiting jobs) inside the add, and a re-wire purged the hold on the way."""
        since = await self._read_mismatch_since(printer_id)
        self._queue().set_identity_hold(printer_id, since is not None)

    def _queue(self) -> PrintQueue:
        return cast("PrintQueue", self._app.state.print_queue)

    def _sessions(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is not None:
            return self._session_factory
        import app.db.engine as db_engine  # late: tests swap the module-level factory

        return db_engine.async_session

    async def _paused_since(self, printer_id: UUID) -> datetime | None:
        """The persisted manual pause, so it survives a re-wire (as ``load_manual_pauses``)."""
        async with self._sessions()() as session:
            row = await session.get(PrinterState, printer_id)
        if row is None or not row.paused:
            return None
        return _aware(row.updated_at)

    async def _tray_keys(self, printer_id: UUID) -> list[str]:
        async with self._sessions()() as session:
            result = await session.execute(
                select(col(PrinterTray.tray_key)).where(col(PrinterTray.printer_id) == printer_id)
            )
            return [str(k) for k in result.scalars()]

    async def _start_producer(self, wiring: _Wiring) -> None:
        producer = wiring.producer
        if producer is not None:
            try:
                await producer.start()
                return
            except Exception as exc:
                _log.warning(
                    "Degraded: status producer for slug=%s not started (%s)",
                    wiring.slug,
                    type(exc).__name__,
                )
                wiring.producer = None
                if wiring.make_producer is not None:  # a page printer: hold it first (L1)
                    await self._pause_status_unavailable(wiring)
                await self._stop_producer_quietly(producer, wiring.slug)
        if wiring.make_producer is not None:  # a page printer: held until a producer runs
            await self._pause_status_unavailable(wiring)
            self._ensure_retry(wiring)

    async def _pause_status_unavailable(self, wiring: _Wiring) -> None:
        """Hold a page printer whose status producer is not running (265-06).

        The existing pause with a reason; a user's pause stays what it is. When the producer
        could not be built, no await lies between ``add_page_printer`` returning and this call,
        so no worker runs a job first. When its start failed, the pause is the first thing after
        the failed call (``start`` only creates the probe task), before the broken producer is
        stopped; an await inside the failing call itself is the only gap.
        """
        try:
            await self._queue().pause_printer(
                wiring.printer_id, reason=STATUS_UNAVAILABLE, source="printer_error"
            )
        except Exception as exc:
            _log.warning(
                "Printer slug=%s not paused as status-unavailable (%s)",
                wiring.slug,
                type(exc).__name__,
            )

    async def _lift_status_pause(self, wiring: _Wiring) -> None:
        """Resume the printer if, and only if, the pause is our ``status-unavailable`` one."""
        queue = self._queue()
        info = queue.pause_info(wiring.printer_id)
        if info is None or info.source != "printer_error" or info.reason_code != STATUS_UNAVAILABLE:
            return
        try:
            await queue.resume_printer(wiring.printer_id)
        except Exception as exc:
            _log.warning(
                "Printer slug=%s status pause not lifted (%s)", wiring.slug, type(exc).__name__
            )

    def _retry_delay(self, failures: int) -> float:
        """The probe backoff: the interval, doubled per failed retry up to ``MAX_BACKOFF_S``."""
        interval = self._settings.sse_probe_interval_s
        doublings = min(failures, MAX_BACKOFF_DOUBLINGS)
        return float(min(MAX_BACKOFF_S, max(interval, interval * (2**doublings))))

    def _ensure_retry(self, wiring: _Wiring) -> None:
        existing = self._retries.get(wiring.printer_id)
        if existing is not None and not existing.done():
            return
        task = asyncio.create_task(
            self._retry_producer(wiring), name=f"producer-retry-{wiring.printer_id}"
        )
        self._retries[wiring.printer_id] = task

        def _forget(done: asyncio.Task[None]) -> None:
            if self._retries.get(wiring.printer_id) is done:
                del self._retries[wiring.printer_id]

        task.add_done_callback(_forget)

    async def _cancel_retry(self, printer_id: UUID) -> None:
        task = self._retries.pop(printer_id, None)
        if task is None or task is asyncio.current_task():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _retry_producer(self, wiring: _Wiring) -> None:
        """Start the status producer of a degraded page printer, with the probe backoff.

        Runs under the printer lock, so it never overlaps an attach, detach or reconcile; it
        gives up when its wiring is no longer the attached one.
        """
        failures = 0
        while True:
            await asyncio.sleep(self._retry_delay(failures))
            async with self._serialized(wiring.printer_id):
                if (
                    self._closed
                    or self._wired.get(wiring.printer_id) is not wiring
                    or wiring.producer is not None
                    or wiring.make_producer is None
                ):
                    return
                producer: IppStatusProducer | None = None
                try:
                    producer = await wiring.make_producer()
                    await producer.start()
                except Exception as exc:
                    failures += 1
                    (_log.warning if failures == 1 else _log.debug)(
                        "Status producer for slug=%s still not running (%s)",
                        wiring.slug,
                        type(exc).__name__,
                    )
                    if producer is not None:
                        await self._stop_producer_quietly(producer, wiring.slug)
                    continue
                wiring.producer = producer
                await self._lift_status_pause(wiring)
                _log.info("Status producer for slug=%s is running again", wiring.slug)
                return

    async def _stop_producer(self, wiring: _Wiring) -> None:
        producer, wiring.producer = wiring.producer, None
        if producer is not None:
            await self._stop_producer_quietly(producer, wiring.slug)

    @staticmethod
    async def _stop_producer_quietly(
        producer: StatusProbeProducer | IppStatusProducer, slug: str
    ) -> None:
        try:
            await producer.stop()
        except Exception as exc:  # one failing stop must not skip the rest
            _log.warning("Status producer stop for slug=%s failed (%s)", slug, type(exc).__name__)

    @staticmethod
    async def _close_page_client(wiring: _Wiring) -> None:
        client, wiring.page_client = wiring.page_client, None
        if client is None:
            return
        try:
            await client.aclose()
        except Exception as exc:  # one failing close must not skip the rest
            _log.warning(
                "IPP page client close for slug=%s failed (%s)", wiring.slug, type(exc).__name__
            )

    def _refresh_backcompat(self) -> None:
        """``print_service``/``printer_id``: the first wired tape printer by ``created_at``."""
        tapes = [w for w in self._wired.values() if w.service is not None]
        state = self._app.state
        if not tapes:
            state.print_service = None
            state.printer_id = None
            return
        first = min(tapes, key=lambda w: (w.created_at, str(w.printer_id)))
        state.print_service = first.service
        state.printer_id = first.printer_id
