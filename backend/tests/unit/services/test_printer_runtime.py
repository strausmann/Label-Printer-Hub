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
