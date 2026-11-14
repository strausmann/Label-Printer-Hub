# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""PrinterRuntime (#224): one code path wires a printer, at startup and on a runtime change.

The page printer is ``FakeIppPrinter`` behind an ASGI transport and SNMP is patched, so no
network is touched. Every wait is bounded.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import app.models
import app.printer_models.ql  # noqa: F401 — registers the QL driver
import httpx
import pytest
import pytest_asyncio
from app.config import get_settings
from app.models.job import Job as DbJob
from app.models.job import JobState as DbJobState
from app.models.printer import Printer
from app.models.printer_status_cache import PrinterStatusCache
from app.printer_backends.exceptions import SnmpDiscoveryError
from app.printer_backends.snmp_helper import PreflightStatus
from app.printer_models.registry import ModelRegistry
from app.services.event_bus import EventBus
from app.services.job_store_sqlite import SQLiteJobStore
from app.services.layout_engine import LayoutEngine
from app.services.print_queue import PrintQueue
from app.services.printer_runtime import PrinterRuntime, wiring_key
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.helpers.fake_ipp_printer import FAKE_URI, FakeIppPrinter
from tests.helpers.page_jobs import RecordingHandler, payload, registered

TEST_TIMEOUT_S = 10.0
URI_2 = "ipp://printer-2.example.invalid/ipp/print"


class _RecordingTransport(httpx.AsyncBaseTransport):
    """Hands every request to *inner*; remembers whether the owning client closed it."""

    def __init__(self, inner: httpx.AsyncBaseTransport, uri: str) -> None:
        self.inner = inner
        self.uri = uri
        self.closed = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self.inner.handle_async_request(request)

    async def aclose(self) -> None:
        self.closed = True


class _BlockingTransport(httpx.AsyncBaseTransport):
    """A printer that never answers."""

    def __init__(self) -> None:
        self.calls = 0
        self.closed = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        await asyncio.Event().wait()
        raise AssertionError("unreachable")  # pragma: no cover

    async def aclose(self) -> None:
        self.closed = True


@dataclass
class Env:
    app: FastAPI
    queue: PrintQueue
    runtime: PrinterRuntime
    factory: async_sessionmaker[AsyncSession]
    fake: FakeIppPrinter
    transports: list[_RecordingTransport] = field(default_factory=list)


async def _until(
    predicate: Callable[[], Awaitable[bool]], timeout_s: float = TEST_TIMEOUT_S
) -> None:
    async with asyncio.timeout(timeout_s):
        while not await predicate():
            await asyncio.sleep(0.02)


def _ipp(
    *,
    slug: str = "page-1",
    uri: str = FAKE_URI,
    queue_timeout_s: int = 30,
    created_at: datetime | None = None,
    printer_id: UUID | None = None,
) -> Printer:
    return Printer(
        id=printer_id or uuid4(),
        name=slug,
        slug=slug,
        model="x",
        backend="ipp",
        connection={"uri": uri, "tls_verify": True},
        enabled=True,
        queue_timeout_s=queue_timeout_s,
        created_at=created_at or datetime.now(UTC),
    )


def _tape(
    *,
    slug: str = "tape-1",
    model: str = "PT-P750W",
    backend: str = "ptouch",
    discover: bool = False,
    created_at: datetime | None = None,
    printer_id: UUID | None = None,
) -> Printer:
    return Printer(
        id=printer_id or uuid4(),
        name=slug,
        slug=slug,
        model=model,
        backend=backend,
        connection={
            "host": "192.0.2.10",
            "port": 9100,
            "snmp": {"discover": discover, "community": "public"},
        },
        enabled=True,
        created_at=created_at or datetime.now(UTC),
    )


async def _store_row(factory: async_sessionmaker[AsyncSession], printer: Printer) -> None:
    async with factory() as s:
        s.add(Printer.model_validate(printer.model_dump()))
        await s.commit()


async def _make_env(
    factory: async_sessionmaker[AsyncSession],
    *,
    interval_s: float = 3600.0,
    fake: FakeIppPrinter | None = None,
    transport: Callable[[str], httpx.AsyncBaseTransport] | None = None,
) -> Env:
    ModelRegistry.ensure_discovered()
    fake = fake or FakeIppPrinter()
    app = FastAPI()
    store = SQLiteJobStore(factory)
    bus = EventBus(queue_size=32)
    engine = LayoutEngine()
    queue = PrintQueue(printers=[], store=store, engine=engine)
    app.state.print_queue = queue
    app.state.event_bus = bus
    app.state.engine = engine
    app.state.job_store = store
    env = Env(app=app, queue=queue, runtime=None, factory=factory, fake=fake)  # type: ignore[arg-type]

    def _factory(uri: str) -> httpx.AsyncBaseTransport:
        if transport is not None:
            return transport(uri)
        rec = _RecordingTransport(httpx.ASGITransport(app=fake), uri)
        env.transports.append(rec)
        return rec

    app.state.ipp_transport_factory = _factory
    settings = get_settings().model_copy(update={"sse_probe_interval_s": interval_s})
    env.runtime = PrinterRuntime(app, settings, session_factory=factory)
    return env


async def _start(env: Env) -> None:
    await env.queue.start()
    await env.runtime.start()


@pytest_asyncio.fixture
async def env(async_session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[Env]:
    e = await _make_env(async_session_factory)
    try:
        yield e
    finally:
        await e.runtime.stop()


def _probes(fake: FakeIppPrinter) -> int:
    return [r.operation for r in fake.received].count("Get-Printer-Attributes")


# --- IPP page printers --------------------------------------------------------------------


async def test_attach_ipp_status_without_waiting_an_interval(env: Env) -> None:
    await _start(env)
    printer = _ipp()
    await _store_row(env.factory, printer)
    await env.runtime.attach(printer)

    async def _captured() -> bool:
        async with env.factory() as s:
            row = await s.get(PrinterStatusCache, printer.id)
            return row is not None and row.captured_at is not None

    await _until(_captured, timeout_s=2.0)
    assert _probes(env.fake) == 1
    assert env.runtime.is_polled(printer.id)
    assert printer.id in env.app.state.ipp_printer_states


async def test_attach_does_not_await_probe(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    blocking: list[_BlockingTransport] = []

    def _transport(_uri: str) -> httpx.AsyncBaseTransport:
        t = _BlockingTransport()
        blocking.append(t)
        return t

    e = await _make_env(async_session_factory, transport=_transport)
    try:
        await _start(e)
        async with asyncio.timeout(0.5):
            await e.runtime.attach(_ipp())
        await _until(lambda: _async(any(t.calls for t in blocking)), timeout_s=2.0)
    finally:
        async with asyncio.timeout(TEST_TIMEOUT_S):
            await e.runtime.stop()


async def test_detach_stops_probes_and_closes_page_client(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    e = await _make_env(async_session_factory, interval_s=0.05)
    try:
        await _start(e)
        printer = _ipp()
        await e.runtime.attach(printer)
        await _until(lambda: _async(_probes(e.fake) >= 2))
        await e.runtime.detach(printer.id)
        after = _probes(e.fake)
        await asyncio.sleep(0.3)
        assert _probes(e.fake) == after
        assert not e.runtime.is_polled(printer.id)
        assert printer.id not in e.app.state.ipp_printer_states
        assert not e.queue.is_page_printer(printer.id)
        # Both clients of the printer (page jobs and probes) are closed.
        assert len(e.transports) == 2
        assert all(t.closed for t in e.transports)
    finally:
        await e.runtime.stop()


async def test_detach_stops_producer_before_queue_removal(env: Env) -> None:
    """Ruling (b): a stopped producer can no longer call the queue's pause control for a
    printer the queue has already forgotten (``resume_printer`` raises ``KeyError`` then)."""
    await _start(env)
    printer = _ipp()
    await env.runtime.attach(printer)
    order: list[str] = []
    producer = env.runtime._wired[printer.id].producer
    assert producer is not None
    real_stop = producer.stop
    real_remove = env.queue.remove_printer

    async def _stop() -> None:
        order.append("producer")
        await real_stop()

    async def _remove(printer_id: UUID, timeout_s: float) -> None:
        order.append("queue")
        await real_remove(printer_id, timeout_s)

    with (
        patch.object(producer, "stop", _stop),
        patch.object(env.queue, "remove_printer", _remove),
    ):
        await env.runtime.detach(printer.id)
    assert order == ["producer", "queue"]


async def test_attach_bad_uri_degrades(env: Env, caplog: pytest.LogCaptureFixture) -> None:
    await _start(env)
    bad = "not-a-uri-secret-host"
    printer = _ipp(uri=bad)
    with caplog.at_level(logging.WARNING, logger="app.services.printer_runtime"):
        await env.runtime.attach(printer)
    assert printer.id not in env.app.state.ipp_printer_states
    assert not env.queue.is_page_printer(printer.id)
    assert not env.runtime.is_polled(printer.id)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(printer.slug in r.getMessage() for r in warnings)
    assert all(bad not in r.getMessage() for r in caplog.records)


async def test_ipp_probes_share_one_semaphore(env: Env) -> None:
    first, second = _ipp(slug="page-a"), _ipp(slug="page-b", uri=URI_2)
    await env.runtime.attach(first)
    await env.runtime.attach(second)
    p1 = env.runtime._wired[first.id].producer
    p2 = env.runtime._wired[second.id].producer
    assert p1 is not None and p2 is not None
    assert p1._limiter is not None
    assert p1._limiter is p2._limiter


async def test_shutdown_wait_uses_attached_timeouts(env: Env) -> None:
    await _start(env)
    printer = _ipp(queue_timeout_s=30)
    await _store_row(env.factory, printer)
    await env.runtime.attach(printer)
    async with env.factory() as s:
        row = await s.get(Printer, printer.id)
        assert row is not None
        row.queue_timeout_s = 90
        await s.commit()
    await env.runtime.reconcile(printer.id)
    calls: list[float] = []
    real_stop = env.queue.stop

    async def _stop(timeout_s: float = 30.0) -> None:
        calls.append(timeout_s)
        await real_stop(timeout_s=1.0)

    with patch.object(env.queue, "stop", _stop):
        await env.runtime.stop()
    assert calls == [90.0]


# --- tape printers ------------------------------------------------------------------------


async def test_attach_tape_with_snmp_starts_producer(env: Env) -> None:
    await _start(env)
    printer = _tape(discover=True)
    await _store_row(env.factory, printer)
    probed = asyncio.Event()

    async def _preflight(*_args: Any, **_kwargs: Any) -> PreflightStatus:
        probed.set()
        return PreflightStatus(hr_printer_status="idle", loaded_tape_mm=12)

    with (
        patch(
            "app.services.printer_runtime._resolve_model_id_from_config",
            AsyncMock(return_value="PT-P750W"),
        ),
        patch("app.services.producers.status_probe_producer.query_preflight", _preflight),
    ):
        await env.runtime.attach(printer)
        async with asyncio.timeout(2.0):
            await probed.wait()
    assert env.runtime.is_polled(printer.id)
    assert env.runtime.print_service_for(printer.id) is not None
    assert env.app.state.slug_to_printer_id == {printer.slug: printer.id}
    assert env.app.state.backend_router.get(printer.slug) is not None


async def test_the_print_service_of_a_tape_printer_knows_its_slug(env: Env) -> None:
    """T12: the slug goes into the PrintService, so a ``printer_disabled`` answer names it."""
    await _start(env)
    printer = _tape(model="PT-P750W", discover=False)
    await _store_row(env.factory, printer)
    await env.runtime.attach(printer)
    service = env.runtime.print_service_for(printer.id)
    assert service is not None
    assert service._printer_slug == printer.slug


async def test_detach_of_a_tape_printer_forgets_its_roll_tracking(env: Env) -> None:
    """T10: a removed printer's lock and no-tape count leave the roll tracker with it."""
    await _start(env)
    printer = _tape(model="PT-P750W", discover=False)
    await _store_row(env.factory, printer)
    await env.runtime.attach(printer)
    env.runtime.roll_tracker._no_tape_streak[printer.id] = 1
    env.runtime.roll_tracker._locks[printer.id] = asyncio.Lock()
    await env.runtime.detach(printer.id)
    assert printer.id not in env.runtime.roll_tracker._no_tape_streak
    assert printer.id not in env.runtime.roll_tracker._locks


async def test_tape_printer_without_snmp_discovery_is_not_polled(env: Env) -> None:
    """No producer is built without ``snmp.discover``: the status endpoint reports it unpolled."""
    await _start(env)
    printer = _tape(model="PT-P750W", discover=False)
    await _store_row(env.factory, printer)
    await env.runtime.attach(printer)
    assert env.runtime.print_service_for(printer.id) is not None  # attached ...
    assert not env.runtime.is_polled(printer.id)  # ... but nobody probes it


async def test_attach_unresolvable_tape_model_degrades_at_runtime(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    await _start(env)
    printer = _tape(model="")  # no model and no SNMP discovery: nothing to resolve
    with caplog.at_level(logging.WARNING, logger="app.services.printer_runtime"):
        await env.runtime.attach(printer)  # does not raise
    assert env.runtime.print_service_for(printer.id) is None
    assert env.app.state.backend_router.get(printer.slug) is None
    assert printer.slug not in env.app.state.slug_to_printer_id
    assert env.app.state.print_service is None
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any(printer.slug in m and "ValueError" in m for m in warnings)
    assert all("192.0.2.10" not in r.getMessage() for r in caplog.records)


async def test_attach_unresolvable_tape_model_is_fatal_at_startup(env: Env) -> None:
    printer = _tape(discover=True)
    with (
        patch(
            "app.services.printer_runtime._resolve_model_id_from_config",
            AsyncMock(side_effect=SnmpDiscoveryError("no answer")),
        ),
        pytest.raises(SnmpDiscoveryError),
    ):
        await env.runtime.attach(printer, fatal=True)
    assert env.runtime.print_service_for(printer.id) is None


async def test_first_tape_printer_backcompat_by_created_at(env: Env) -> None:
    now = datetime.now(UTC)
    # The older printer has the larger id and is attached second.
    older = _tape(
        slug="older",
        created_at=now - timedelta(days=2),
        printer_id=UUID("ffffffff-0000-0000-0000-000000000001"),
    )
    newer = _tape(
        slug="newer",
        created_at=now - timedelta(days=1),
        printer_id=UUID("00000000-0000-0000-0000-000000000001"),
    )
    await env.runtime.attach(newer)
    assert env.app.state.printer_id == newer.id
    await env.runtime.attach(older)
    assert env.app.state.printer_id == older.id
    assert env.app.state.print_service is env.runtime.print_service_for(older.id)
    await env.runtime.detach(older.id)
    assert env.app.state.printer_id == newer.id
    await env.runtime.detach(newer.id)
    assert env.app.state.printer_id is None
    assert env.app.state.print_service is None


async def test_describe_tape_for_uses_model_driver(env: Env) -> None:
    ql = _tape(slug="ql", model="QL-820NWB", backend="brother_ql")
    await env.runtime.attach(ql)
    assert env.runtime.describe_tape_for(ql.id, 62).label != "62mm"
    assert env.runtime.describe_tape_for(ql.id, 62).label == "62mm DK"
    assert env.runtime.describe_tape_for(uuid4(), 62).label == "62mm"


async def test_kind_change_page_to_tape_settles_printing_page_job(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ruling (a): a page printer re-wired as a tape printer never resumes the tracking of its
    page job at the printer; the job ends as unknown at once, not at the next restart."""
    fake = FakeIppPrinter(job_script=[3, 5])  # sticks at 5: the page is printing
    e = await _make_env(async_session_factory, fake=fake)
    try:
        with registered(RecordingHandler()) as handler:
            await _start(e)
            page = _ipp(slug="switch", queue_timeout_s=1)
            await _store_row(e.factory, page)
            await e.runtime.attach(page)
            jid = await e.queue.submit_page_job(page.id, payload(), api_key_id=None, source_ip=None)

            async def _tracked() -> bool:
                async with e.factory() as s:
                    row = await s.get(DbJob, jid)
                    return row is not None and "ipp_job_id" in (row.result or {})

            await _until(_tracked)
            async with e.factory() as s:
                row = await s.get(Printer, page.id)
                assert row is not None
                row.backend = "ptouch"
                row.model = "PT-P750W"
                row.connection = {"host": "192.0.2.10", "port": 9100}
                row.queue_timeout_s = 0
                await s.commit()
            await e.runtime.reconcile(page.id)

            async with e.factory() as s:
                row = await s.get(DbJob, jid)
                assert row is not None
                assert row.state == DbJobState.FAILED_RESTART.value
            assert handler.names(jid)[-1] == "unknown"
            assert e.runtime.print_service_for(page.id) is not None
    finally:
        await e.runtime.stop()


# --- lifecycle ----------------------------------------------------------------------------


async def test_stop_stops_queue_once_and_closes_clients(env: Env) -> None:
    await _start(env)
    await env.runtime.attach(_ipp(slug="page-a"))
    await env.runtime.attach(_ipp(slug="page-b", uri=URI_2))
    calls: list[float] = []
    real_stop = env.queue.stop

    async def _stop(timeout_s: float = 30.0) -> None:
        calls.append(timeout_s)
        await real_stop(timeout_s=1.0)

    with patch.object(env.queue, "stop", _stop):
        await env.runtime.stop()
        await env.runtime.stop()  # a second stop is a no-op
    assert calls == [30.0]
    assert len(env.transports) == 4
    assert all(t.closed for t in env.transports)


async def test_reconcile_after_stop_is_noop(env: Env) -> None:
    await _start(env)
    printer = _ipp()
    await _store_row(env.factory, printer)
    await env.runtime.stop()
    await env.runtime.reconcile(printer.id)
    await env.runtime.attach(printer)
    assert printer.id not in env.app.state.ipp_printer_states
    assert env.transports == []


async def test_reconcile_waits_for_a_running_detach_of_the_same_printer(env: Env) -> None:
    """Ruling (c): the runtime's per-printer lock serializes a reconcile behind a detach of the
    same printer; the printer ends attached exactly once."""
    await _start(env)
    printer = _ipp()
    await _store_row(env.factory, printer)
    await env.runtime.attach(printer)
    gate = asyncio.Event()
    entered = asyncio.Event()
    real_remove = env.queue.remove_printer

    async def _remove(printer_id: UUID, timeout_s: float) -> None:
        entered.set()
        await gate.wait()
        await real_remove(printer_id, timeout_s)

    with patch.object(env.queue, "remove_printer", _remove):
        detach = asyncio.create_task(env.runtime.detach(printer.id))
        await entered.wait()
        reconcile = asyncio.create_task(env.runtime.reconcile(printer.id))
        try:
            await asyncio.sleep(0.05)
            assert not reconcile.done()  # waits for the detach
        finally:
            gate.set()  # a red run must not leave the detach (and the teardown) blocked
            async with asyncio.timeout(TEST_TIMEOUT_S):
                await asyncio.gather(detach, reconcile, return_exceptions=True)
    assert env.queue.is_page_printer(printer.id)
    assert env.runtime.is_polled(printer.id)
    assert list(env.app.state.ipp_printer_states) == [printer.id]


def test_wiring_key_ignores_name_label_and_cut_defaults() -> None:
    printer = _tape()
    renamed = printer.model_copy(update={"name": "Renamed", "cut_defaults_half_cut": True})
    assert wiring_key(renamed) == wiring_key(printer)
    moved = printer.model_copy(update={"connection": {"host": "192.0.2.99", "port": 9100}})
    assert wiring_key(moved) != wiring_key(printer)
    # queue_timeout_s is part of the key for IPP printers only.
    page = _ipp(queue_timeout_s=30)
    assert wiring_key(page.model_copy(update={"queue_timeout_s": 90})) != wiring_key(page)
    assert wiring_key(printer.model_copy(update={"queue_timeout_s": 90})) == wiring_key(printer)
    assert wiring_key(page, tray_keys=["tray-1"]) != wiring_key(page, tray_keys=["tray-2"])


async def _async(value: bool) -> bool:
    return value


# --- reconcile skip rule and failure handling (Task 7) -----------------------------------


async def _add_tray(factory: async_sessionmaker[AsyncSession], printer_id: UUID, key: str) -> None:
    from app.models.printer_tray import PrinterTray

    async with factory() as s:
        s.add(PrinterTray(printer_id=printer_id, tray_key=key, label=key, is_default=key == "auto"))
        await s.commit()


async def _update_row(
    factory: async_sessionmaker[AsyncSession], printer_id: UUID, **changes: Any
) -> None:
    async with factory() as s:
        row = await s.get(Printer, printer_id)
        assert row is not None
        for name, value in changes.items():
            setattr(row, name, value)
        await s.commit()


async def test_reconcile_unchanged_ipp_row_with_trays_keeps_the_wiring(env: Env) -> None:
    """The skip rule compares with the tray keys: an IPP printer with trays is not re-wired by
    a rename (its trays live in their own table, the stored key includes them)."""
    await _start(env)
    printer = _ipp()
    await _store_row(env.factory, printer)
    await _add_tray(env.factory, printer.id, "auto")
    await _add_tray(env.factory, printer.id, "tray-2")
    await env.runtime.reconcile(printer.id)
    state = env.app.state.ipp_printer_states[printer.id]
    clients = len(env.transports)
    await _update_row(env.factory, printer.id, name="Renamed")
    await env.runtime.reconcile(printer.id)
    assert len(env.transports) == clients  # no new IPP client: not re-wired
    assert env.app.state.ipp_printer_states[printer.id] is state
    assert not any(t.closed for t in env.transports)
    # A changed tray set is a change of the wiring.
    await _add_tray(env.factory, printer.id, "tray-3")
    await env.runtime.reconcile(printer.id)
    assert len(env.transports) == clients + 2
    assert env.app.state.ipp_printer_states[printer.id] is not state


async def test_reconcile_tape_timeout_only_change_takes_over_the_timeout(env: Env) -> None:
    """Ruling (b): the tape queue timeout is not in the key; a timeout-only edit does not
    re-wire, but the shutdown wait uses the new value (no stale timeout)."""
    await _start(env)
    printer = _tape()
    printer.queue_timeout_s = 30
    await _store_row(env.factory, printer)
    resolve = AsyncMock(return_value="PT-P750W")
    with patch("app.services.printer_runtime._resolve_model_id_from_config", resolve):
        await env.runtime.reconcile(printer.id)
        service = env.runtime.print_service_for(printer.id)
        await _update_row(env.factory, printer.id, queue_timeout_s=90)
        await env.runtime.reconcile(printer.id)
    assert resolve.await_count == 1  # not re-wired
    assert env.runtime.print_service_for(printer.id) is service
    calls: list[float] = []
    real_stop = env.queue.stop

    async def _stop(timeout_s: float = 30.0) -> None:
        calls.append(timeout_s)
        await real_stop(timeout_s=1.0)

    with patch.object(env.queue, "stop", _stop):
        await env.runtime.stop()
    assert calls == [90.0]


async def test_stored_layout_defaults_reach_the_service_and_follow_an_edit(env: Env) -> None:
    """#258: the layout default per tape lives on the row; editing it needs no re-wire."""
    from app.schemas.label_layout import LabelOrientation, LayoutDefault, QlLayoutPreset

    await _start(env)
    printer = _tape(model="QL-820NWB", backend="brother_ql")
    printer.layout_defaults = {"62": {"orientation": "across", "preset": "standard"}}
    await _store_row(env.factory, printer)
    resolve = AsyncMock(return_value="QL-820NWB")
    with patch("app.services.printer_runtime._resolve_model_id_from_config", resolve):
        await env.runtime.reconcile(printer.id)
        service = env.runtime.print_service_for(printer.id)
        assert service is not None
        assert service.layout_defaults == {
            62: LayoutDefault(orientation=LabelOrientation.ACROSS, preset=QlLayoutPreset.STANDARD)
        }
        await _update_row(env.factory, printer.id, layout_defaults={"62": {"orientation": "along"}})
        await env.runtime.reconcile(printer.id)
    assert resolve.await_count == 1  # not re-wired
    assert env.runtime.print_service_for(printer.id) is service
    assert service.layout_defaults == {62: LayoutDefault(orientation=LabelOrientation.ALONG)}


def test_wiring_key_ignores_layout_defaults() -> None:
    printer = _tape(model="QL-820NWB", backend="brother_ql")
    changed = printer.model_copy(update={"layout_defaults": {"62": {"orientation": "along"}}})
    assert wiring_key(changed) == wiring_key(printer)


async def test_reconcile_failure_is_logged_and_leaves_detached(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    """Ruling (d): a store failure during the re-wire does not raise into the caller; the
    printer ends detached, the log names the id and the error class only."""
    await _start(env)
    printer = _ipp()
    await _store_row(env.factory, printer)
    await env.runtime.reconcile(printer.id)
    await _update_row(env.factory, printer.id, connection={"uri": URI_2, "tls_verify": True})

    async def _remove(printer_id: UUID, timeout_s: float) -> None:
        raise RuntimeError(f"store down for {URI_2}")

    with (
        patch.object(env.queue, "remove_printer", _remove),
        caplog.at_level(logging.WARNING, logger="app.services.printer_runtime"),
    ):
        await env.runtime.reconcile(printer.id)  # does not raise
    assert not env.runtime.is_polled(printer.id)
    assert printer.id not in env.app.state.ipp_printer_states
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any(str(printer.id) in m and "RuntimeError" in m for m in warnings)
    assert all("example.invalid" not in r.getMessage() for r in caplog.records)


async def test_detach_after_stop_is_noop(env: Env) -> None:
    """Ruling (c, task-6 minor 1): a detach after ``stop()`` touches neither the queue nor the
    wiring."""
    await _start(env)
    printer = _ipp()
    await env.runtime.attach(printer)
    await env.runtime.stop()
    removed: list[UUID] = []

    async def _remove(printer_id: UUID, timeout_s: float) -> None:
        removed.append(printer_id)

    with patch.object(env.queue, "remove_printer", _remove):
        await env.runtime.detach(printer.id)
    assert removed == []


async def test_kind_change_tape_to_page_fails_queued_tape_jobs(env: Env) -> None:
    """Ruling (f): tape jobs queued for an id that becomes a page printer cannot be printed as
    pages; the page printer's recovery fails them (``recovery_invalid_page_payload``), the same
    outcome a restart gives."""
    await _start(env)
    printer = _tape()
    await _store_row(env.factory, printer)
    await env.runtime.reconcile(printer.id)
    assert env.runtime.print_service_for(printer.id) is not None
    async with env.factory() as s:
        job = DbJob(printer_id=printer.id, payload={"tape_mm": 12, "options": {}})
        s.add(job)
        await s.commit()
        jid = job.id
    await _update_row(
        env.factory,
        printer.id,
        backend="ipp",
        model="x",
        connection={"uri": FAKE_URI, "tls_verify": True},
    )
    await env.runtime.reconcile(printer.id)
    assert env.queue.is_page_printer(printer.id)
    async with env.factory() as s:
        row = await s.get(DbJob, jid)
        assert row is not None
        assert row.state == DbJobState.FAILED.value
        assert row.error == "recovery_invalid_page_payload"


# --- Task 6: stop, locks, key, reconcile tasks, roll tracker, failed attach -----------------


async def test_stop_closes_page_clients_when_queue_stop_raises(env: Env) -> None:
    """263-16: a failing ``queue.stop`` must not leave the page clients open."""
    await _start(env)
    await env.runtime.attach(_ipp(slug="page-a"))
    await env.runtime.attach(_ipp(slug="page-b", uri=URI_2))

    async def _boom(timeout_s: float = 30.0) -> None:
        raise RuntimeError("queue stop failed")

    with patch.object(env.queue, "stop", _boom), pytest.raises(RuntimeError, match="queue stop"):
        await env.runtime.stop()
    assert len(env.transports) == 4
    assert all(t.closed for t in env.transports)


async def test_lock_entry_removed_after_detach(env: Env) -> None:
    """263-17: the per-printer lock entry does not outlive the printer."""
    await _start(env)
    printer = _ipp()
    await env.runtime.attach(printer)
    await env.runtime.detach(printer.id)
    assert printer.id not in env.runtime._locks


async def test_lock_entry_kept_while_a_waiter_queues_behind_a_detach(env: Env) -> None:
    """263-17, interleaving: an attach waiting on the lock of a detach still runs strictly after
    it (the entry is not dropped under the waiter), and the entry is gone once both finished."""
    await _start(env)
    printer = _ipp()
    await env.runtime.attach(printer)
    gate = asyncio.Event()
    entered = asyncio.Event()
    real_remove = env.queue.remove_printer
    order: list[str] = []

    async def _remove(printer_id: UUID, timeout_s: float) -> None:
        order.append("remove-start")
        entered.set()
        await gate.wait()
        await real_remove(printer_id, timeout_s)
        order.append("remove-end")

    real_add = env.queue.add_page_printer

    async def _add(*args: Any, **kwargs: Any) -> None:
        order.append("add")
        await real_add(*args, **kwargs)

    with (
        patch.object(env.queue, "remove_printer", _remove),
        patch.object(env.queue, "add_page_printer", _add),
    ):
        detach = asyncio.create_task(env.runtime.detach(printer.id))
        await entered.wait()
        attach = asyncio.create_task(env.runtime.attach(printer))
        third = asyncio.create_task(env.runtime.detach(printer.id))
        try:
            await asyncio.sleep(0.05)
            assert order == ["remove-start"]  # both waiters are parked behind the detach
        finally:
            gate.set()
            async with asyncio.timeout(TEST_TIMEOUT_S):
                await asyncio.gather(detach, attach, third, return_exceptions=True)
    assert order.index("remove-end") < order.index("add")
    assert printer.id not in env.runtime._locks


def test_wiring_key_changes_when_community_changes() -> None:
    """263-18: the SNMP community is detected through the connection JSON alone."""
    printer = _tape(discover=True)
    other = printer.model_copy(
        update={
            "connection": {
                "host": "192.0.2.10",
                "port": 9100,
                "snmp": {"discover": True, "community": "other"},
            }
        }
    )
    assert wiring_key(other) != wiring_key(printer)
    toggled = printer.model_copy(
        update={
            "connection": {
                "host": "192.0.2.10",
                "port": 9100,
                "snmp": {"discover": False, "community": "public"},
            }
        }
    )
    assert wiring_key(toggled) != wiring_key(printer)
    assert len(wiring_key(printer)) == 6  # the duplicate SNMP element is gone


def _fail_first_producer_start() -> Any:
    """A patch under which the first ``IppStatusProducer.start`` raises, later ones work."""
    from app.services.producers.ipp_status_producer import IppStatusProducer

    real_start = IppStatusProducer.start
    calls: list[int] = []

    async def _start(self: IppStatusProducer) -> None:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("start failed")
        await real_start(self)

    return patch.object(IppStatusProducer, "start", _start)


async def test_rename_restarts_a_failed_producer(env: Env) -> None:
    """263-23: a rename-only update (equal key) re-wires a page printer whose producer is dead."""
    await _start(env)
    printer = _ipp()
    await _store_row(env.factory, printer)
    with _fail_first_producer_start():
        await env.runtime.reconcile(printer.id)
        assert not env.runtime.is_polled(printer.id)  # the start failed
        await _update_row(env.factory, printer.id, name="Renamed")
        await env.runtime.reconcile(printer.id)
    assert env.runtime.is_polled(printer.id)
    assert env.queue.is_page_printer(printer.id)


async def test_rename_keeps_a_tape_printer_without_snmp_wired(env: Env) -> None:
    """263-23 counter-case: a tape printer that is not polled by design is not re-wired."""
    await _start(env)
    printer = _tape(discover=False)
    await _store_row(env.factory, printer)
    await env.runtime.reconcile(printer.id)
    service = env.runtime.print_service_for(printer.id)
    assert service is not None
    await _update_row(env.factory, printer.id, name="Renamed")
    await env.runtime.reconcile(printer.id)
    assert env.runtime.print_service_for(printer.id) is service


async def test_reconcile_tasks_are_per_app(env: Env, async_session_factory: Any) -> None:
    """263-24: the running reconciles live on the runtime of the app, not in a module set."""
    import app.api.routes.admin_printers_api as admin_api

    other = await _make_env(async_session_factory)
    try:
        env.app.state.printer_runtime = env.runtime
        other.app.state.printer_runtime = other.runtime
        gate = asyncio.Event()
        entered = asyncio.Event()

        async def _reconcile(printer_id: UUID) -> None:
            entered.set()
            await gate.wait()

        with patch.object(env.runtime, "reconcile", _reconcile):
            request: Any = SimpleNamespace(app=env.app)
            call = asyncio.create_task(admin_api._apply_live(request, uuid4()))
            try:
                await entered.wait()
                assert len(env.runtime.reconciles) == 1
                assert other.runtime.reconciles == set()
                assert not hasattr(admin_api, "_RECONCILES")
            finally:
                gate.set()
                async with asyncio.timeout(TEST_TIMEOUT_S):
                    await call
        await asyncio.sleep(0)
        assert env.runtime.reconciles == set()
    finally:
        await other.runtime.stop()


async def test_overlapping_producers_emit_one_roll_changed(env: Env) -> None:
    """263-35: every producer gets the runtime's one ``RollTracker``; two producers of the same
    printer (an old and a re-wired one) report one change between them."""
    await _start(env)
    printer = _tape(discover=True)
    await _store_row(env.factory, printer)
    events = env.app.state.event_bus.subscribe(f"printer:{printer.id}:tape", "t")

    async def _preflight(*_args: Any, **_kwargs: Any) -> PreflightStatus:
        return PreflightStatus(hr_printer_status="idle", loaded_tape_mm=12)

    with (
        patch(
            "app.services.printer_runtime._resolve_model_id_from_config",
            AsyncMock(return_value="PT-P750W"),
        ),
        patch("app.services.producers.status_probe_producer.query_preflight", _preflight),
    ):
        await env.runtime.attach(printer)
        first = env.runtime._wired[printer.id].producer
        await env.runtime.attach(printer)  # a re-wire: a second producer for the same printer
        second = env.runtime._wired[printer.id].producer
    assert first is not None and second is not None and first is not second
    tracker = env.runtime.roll_tracker
    assert first._roll_tracker is tracker  # type: ignore[union-attr]
    assert second._roll_tracker is tracker  # type: ignore[union-attr]
    results = await asyncio.gather(
        first._roll_tracker.observe(printer.id, 12, "12mm"),  # type: ignore[union-attr]
        second._roll_tracker.observe(printer.id, 12, "12mm"),  # type: ignore[union-attr]
    )
    assert [r is not None for r in results].count(True) == 1
    published = []
    while not events.empty():
        event = events.get_nowait()
        if event is not None and event.event_type == "printer.roll_changed":
            published.append(event)
    assert len(published) == 1


async def test_failed_attach_leaves_no_worker(env: Env) -> None:
    """263-77: a failure after the page printer joined the queue takes it out again; tray keys
    are read before the add, so their failure never reaches the queue at all."""
    await _start(env)
    printer = _ipp()

    async def _boom(_pid: UUID) -> list[str]:
        raise RuntimeError("store down")

    with patch.object(env.runtime, "_tray_keys", _boom), pytest.raises(RuntimeError):
        await env.runtime.attach(printer)
    assert not env.queue.is_page_printer(printer.id)
    assert env.queue.pause_info(printer.id) is None
    assert printer.id not in env.app.state.ipp_printer_states
    assert env.transports == []  # the tray keys are read before any client is built


async def test_failed_attach_after_the_add_removes_the_printer(env: Env) -> None:
    """263-77: any later failure of the attach calls ``queue.remove_printer``."""
    await _start(env)
    printer = _ipp()

    def _boom() -> None:
        raise RuntimeError("late failure")

    with patch.object(env.runtime, "_refresh_backcompat", _boom), pytest.raises(RuntimeError):
        await env.runtime.attach(printer)
    assert not env.queue.is_page_printer(printer.id)
    assert printer.id not in env.app.state.ipp_printer_states
    assert not env.runtime.is_polled(printer.id)
    assert all(t.closed for t in env.transports)


# --- 265-06: a page printer without a status producer is held, not served blind -----------


async def test_dead_producer_pauses_page_printer(env: Env) -> None:
    await _start(env)
    printer = _ipp()
    with _fail_first_producer_start():
        await env.runtime.attach(printer)
    info = env.queue.pause_info(printer.id)
    assert info is not None
    assert (info.source, info.reason_code) == ("printer_error", "status-unavailable")
    assert env.queue.is_page_printer(printer.id)  # attached, degraded
    assert not env.runtime.is_polled(printer.id)


async def test_unbuildable_producer_pauses_page_printer_before_the_queue_runs(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """At startup the printer is paused before the queue (and any worker) exists."""
    from app.services.producers import ipp_status_producer

    e = await _make_env(async_session_factory)
    printer = _ipp()
    try:
        with patch.object(ipp_status_producer.IppStatusProducer, "__init__", _raising_init):
            await e.runtime.attach(printer, fatal=True)
        info = e.queue.pause_info(printer.id)
        assert info is not None and info.reason_code == "status-unavailable"
        await _start(e)
    finally:
        await e.runtime.stop()


def _raising_init(self: Any, **_kwargs: Any) -> None:
    raise RuntimeError("cannot build")


async def test_producer_retry_lifts_status_pause(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    e = await _make_env(async_session_factory, interval_s=0.05)
    try:
        await _start(e)
        printer = _ipp()
        with _fail_first_producer_start():
            await e.runtime.attach(printer)
            assert e.queue.pause_info(printer.id) is not None
            await _until(lambda: _async(e.queue.pause_info(printer.id) is None), timeout_s=5.0)
        assert e.runtime.is_polled(printer.id)
    finally:
        await e.runtime.stop()


async def test_producer_retry_keeps_a_user_pause(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A successful retry lifts the ``status-unavailable`` pause only, never a user's."""
    e = await _make_env(async_session_factory, interval_s=0.05)
    try:
        await _start(e)
        printer = _ipp()
        with _fail_first_producer_start():
            await e.runtime.attach(printer)
            await e.queue.pause_printer(printer.id, reason="user", source="user")
            await _until(lambda: _async(e.runtime.is_polled(printer.id)), timeout_s=5.0)
        info = e.queue.pause_info(printer.id)
        assert info is not None and info.source == "user"
    finally:
        await e.runtime.stop()


async def test_detach_cancels_the_producer_retry(env: Env) -> None:
    await _start(env)
    printer = _ipp()
    with _fail_first_producer_start():
        await env.runtime.attach(printer)
    retry = env.runtime._retries.get(printer.id)
    assert retry is not None and not retry.done()
    await env.runtime.detach(printer.id)
    assert retry.done()
    assert printer.id not in env.runtime._retries


async def test_wiring_keeps_only_a_digest_of_its_key(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    """Carried (#263): the key holds the IPP URI and the SNMP community, so the runtime keeps a
    SHA-256 digest only, and attach and reconcile log neither."""
    import re

    await _start(env)
    secret_uri = "ipp://secret-host.example.invalid/ipp/print"
    printer = _ipp(uri=secret_uri)
    await _store_row(env.factory, printer)
    with caplog.at_level(logging.DEBUG, logger="app.services.printer_runtime"):
        await env.runtime.attach(printer)
        await env.runtime.reconcile(printer.id)
    wiring = env.runtime._wired[printer.id]
    assert re.fullmatch(r"[0-9a-f]{64}", wiring.key_digest)
    assert "secret-host" not in repr(vars(wiring).get("key_digest"))
    assert not any(isinstance(v, tuple) for v in vars(wiring).values())
    assert all("secret-host" not in r.getMessage() for r in caplog.records)


# --- the producer retry task under concurrency (M1) ---------------------------------------


class _GatedStart:
    """``IppStatusProducer.start``: the first call raises; later calls park at ``gate`` first.

    The parked call runs inside the retry's critical section (the printer lock is held).
    """

    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.entered = asyncio.Event()
        self.started: list[Any] = []
        self._calls = 0

    def patch(self) -> Any:
        from app.services.producers.ipp_status_producer import IppStatusProducer

        real_start = IppStatusProducer.start
        outer = self

        async def _start(self: IppStatusProducer) -> None:
            outer._calls += 1
            if outer._calls == 1:
                raise RuntimeError("start failed")
            outer.started.append(self)
            outer.entered.set()
            await outer.gate.wait()
            await real_start(self)

        return patch.object(IppStatusProducer, "start", _start)


async def _retry_env(factory: async_sessionmaker[AsyncSession]) -> Env:
    return await _make_env(factory, interval_s=0.05)


def _running(producers: list[Any]) -> list[Any]:
    return [p for p in producers if p._task is not None and not p._task.done()]


async def test_detach_waits_for_a_retry_that_holds_the_lock(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """(a) A detach during the retry's start waits for it, then stops what the retry started."""
    e = await _retry_env(async_session_factory)
    gated = _GatedStart()
    try:
        await _start(e)
        printer = _ipp()
        with gated.patch():
            await e.runtime.attach(printer)
            async with asyncio.timeout(TEST_TIMEOUT_S):
                await gated.entered.wait()  # the retry is inside its critical section
            detach = asyncio.create_task(e.runtime.detach(printer.id))
            try:
                await asyncio.sleep(0.1)
                assert not detach.done()  # waits for the lock
            finally:
                gated.gate.set()
                async with asyncio.timeout(TEST_TIMEOUT_S):
                    await detach
        assert printer.id not in e.runtime._wired
        assert not e.queue.is_page_printer(printer.id)
        assert _running(gated.started) == []  # no producer left for the removed wiring
        assert e.runtime._retries == {}
        assert all(t.closed for t in e.transports[1:])
    finally:
        await e.runtime.stop()


async def test_reconcile_rewiring_while_a_retry_waits_leaves_one_producer(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """(b) The retry waits for the lock a reconcile holds; the reconcile re-wires. The waiting
    retry does not start a second producer or lift the new wiring's state."""
    e = await _retry_env(async_session_factory)
    gated = _GatedStart()
    gated.gate.set()  # later starts run through
    try:
        await _start(e)
        printer = _ipp()
        await _store_row(e.factory, printer)
        hold = asyncio.Event()
        real_trays = e.runtime._tray_keys

        async def _trays(pid: UUID) -> list[str]:
            await hold.wait()  # reconcile holds the lock here
            return await real_trays(pid)

        with gated.patch():
            await e.runtime.attach(printer)  # the first start fails: degraded, retry armed
            assert e.runtime._retries.get(printer.id) is not None
            with patch.object(e.runtime, "_tray_keys", _trays):
                reconcile = asyncio.create_task(e.runtime.reconcile(printer.id))
                await asyncio.sleep(0.2)  # the retry's delay has passed: it waits for the lock
                hold.set()
                async with asyncio.timeout(TEST_TIMEOUT_S):
                    await reconcile
            await asyncio.sleep(0.2)
        assert len(gated.started) == 1  # the re-wire's producer; the retry started none
        assert len(_running(gated.started)) == 1
        assert e.runtime.is_polled(printer.id)
        assert e.queue.pause_info(printer.id) is None
        assert e.runtime._retries == {}
    finally:
        await e.runtime.stop()


async def test_stop_waits_for_a_retry_that_holds_the_lock(
    async_session_factory: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    """(c) ``stop()`` during the retry's start waits for it, then stops its producer and closes
    every client; no task is destroyed pending."""
    import gc

    e = await _retry_env(async_session_factory)
    gated = _GatedStart()
    await _start(e)
    printer = _ipp()
    with gated.patch(), caplog.at_level(logging.ERROR, logger="asyncio"):
        await e.runtime.attach(printer)
        async with asyncio.timeout(TEST_TIMEOUT_S):
            await gated.entered.wait()
        stop = asyncio.create_task(e.runtime.stop())
        try:
            await asyncio.sleep(0.1)
            assert not stop.done()
        finally:
            gated.gate.set()
            async with asyncio.timeout(TEST_TIMEOUT_S):
                await stop
        gc.collect()
    assert _running(gated.started) == []
    assert e.runtime._retries == {}
    assert all(t.closed for t in e.transports)
    assert not [r for r in caplog.records if "destroyed" in r.getMessage()]


# --- L1 / L2 ------------------------------------------------------------------------------


async def test_degraded_page_printer_holds_a_queued_job_until_the_producer_runs(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """L1: a job submitted to a printer with a dead status producer waits; it prints once the
    retry has started the producer."""
    e = await _retry_env(async_session_factory)
    try:
        with registered(RecordingHandler()):
            await _start(e)
            printer = _ipp()
            await _store_row(e.factory, printer)
            gated = _GatedStart()
            with gated.patch():
                await e.runtime.attach(printer)
                jid = await e.queue.submit_page_job(
                    printer.id, payload(), api_key_id=None, source_ip=None
                )
                await asyncio.sleep(0.05)  # before the retry fires
                assert [r.operation for r in e.fake.received].count("Print-Job") == 0
                async with e.factory() as s:
                    row = await s.get(DbJob, jid)
                    assert row is not None and row.state == DbJobState.QUEUED.value
                gated.gate.set()
                await _until(
                    lambda: _async([r.operation for r in e.fake.received].count("Print-Job") == 1),
                    timeout_s=8.0,
                )
    finally:
        await e.runtime.stop()


async def test_failed_producer_build_closes_its_client(env: Env) -> None:
    """L2: an ``IppStatusProducer`` constructor that raises must not leak the client it was
    given (the retry would leak one per round)."""
    from app.services.producers import ipp_status_producer

    await _start(env)
    printer = _ipp()
    with patch.object(ipp_status_producer.IppStatusProducer, "__init__", _raising_init):
        await env.runtime.attach(printer)
    assert len(env.transports) == 2  # the page client's and the producer's
    assert [t.closed for t in env.transports] == [False, True]
