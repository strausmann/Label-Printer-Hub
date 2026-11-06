"""IppStatusProducer: cache write, change-only events, offline handling, jobs ahead, auto-resume.

The printer is ``FakeIppPrinter`` behind an ASGI transport; no network is touched.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import app.models  # noqa: F401
import httpx
from app.models.printer_status_cache import PrinterStatusCache
from app.printer_backends.ipp.client import IppClient
from app.printer_backends.ipp.codec import Attr, Tag
from app.services.event_bus import EventBus
from app.services.print_queue import PauseInfo
from app.services.producers.ipp_status_producer import (
    MAX_BACKOFF_S,
    IppPrinterState,
    IppStatusProducer,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.helpers.fake_ipp_printer import FAKE_URI, FailingTransport, FakeIppPrinter

PDF = b"%PDF-1.4\n%%EOF\n"


def _bus() -> MagicMock:
    bus = MagicMock(spec=EventBus)
    bus.next_event_id.return_value = 1
    return bus


class _Pause:
    """A fake ``PauseControl`` that remembers resumes."""

    def __init__(self, info: PauseInfo | None) -> None:
        self.info = info
        self.resumed: list[UUID] = []

    def pause_info(self, printer_id: UUID) -> PauseInfo | None:
        return self.info

    async def resume_printer(self, printer_id: UUID) -> None:
        self.resumed.append(printer_id)
        self.info = None


def _pause(source: str, reason: str) -> _Pause:
    return _Pause(PauseInfo(source=source, reason_code=reason, since=datetime.now(UTC)))  # type: ignore[arg-type]


def _make(
    fake: FakeIppPrinter,
    factory: async_sessionmaker[AsyncSession],
    *,
    bus: MagicMock | None = None,
    pause: _Pause | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    state: IppPrinterState | None = None,
    interval_s: float = 30.0,
) -> tuple[IppStatusProducer, uuid4, MagicMock, IppPrinterState]:
    pid = uuid4()
    bus = bus or _bus()
    state = state or IppPrinterState()
    client = IppClient(FAKE_URI, transport=transport or httpx.ASGITransport(app=fake))
    producer = IppStatusProducer(
        bus=bus,
        printer_id=pid,
        client=client,
        session_factory=factory,
        state=state,
        pause_control=pause,
        interval_s=interval_s,
    )
    return producer, pid, bus, state


async def _cache(factory: async_sessionmaker[AsyncSession], pid: UUID) -> PrinterStatusCache:
    async with factory() as s:
        row = await s.get(PrinterStatusCache, pid)
        assert row is not None
        return row


async def test_probe_writes_cache_and_publishes(async_session_factory) -> None:
    fake = FakeIppPrinter()
    producer, pid, bus, state = _make(fake, async_session_factory)
    record = await producer.probe_once()
    assert record is not None and record.online

    row = await _cache(async_session_factory, pid)
    assert row.parsed["kind"] == "page"
    assert row.parsed["online"] is True
    assert row.captured_at is not None
    assert state.status is record and state.summary is record.summary
    assert bus.publish.call_count == 1
    channel, event = bus.publish.call_args[0]
    assert channel == f"printer:{pid}:state"
    assert event.event_type == "printer.status"
    assert event.data["kind"] == "page" and event.data["online"] is True

    await producer.probe_once()  # nothing changed
    assert bus.publish.call_count == 1
    fake.reasons = ["media-empty-error"]
    await producer.probe_once()
    assert bus.publish.call_count == 2
    assert bus.publish.call_args[0][1].data["blocking_reason"] == "media-empty"
    await producer.stop()


async def test_offline_on_unreachable(async_session_factory) -> None:
    fake = FakeIppPrinter()
    producer, pid, bus, state = _make(
        fake,
        async_session_factory,
        transport=FailingTransport(
            httpx.ASGITransport(app=fake), "Get-Printer-Attributes", httpx.ConnectError
        ),
    )
    assert await producer.probe_once() is None  # no exception
    row = await _cache(async_session_factory, pid)
    assert row.parsed["online"] is False
    assert row.parsed["last_error"] == "IppUnreachableError"
    assert state.status is not None and state.status.online is False
    assert bus.publish.call_count == 1
    assert bus.publish.call_args[0][1].data["online"] is False
    assert await producer.probe_once() is None
    assert bus.publish.call_count == 1  # still offline: no second event
    await producer.stop()


async def test_offline_keeps_last_snapshot_and_recovers(async_session_factory) -> None:
    fake = FakeIppPrinter(markers=[{"name": "Black Toner", "level": 40, "type": "toner"}])
    producer, pid, bus, _state = _make(fake, async_session_factory)
    first = await producer.probe_once()
    assert first is not None and first.markers
    fake.accepting_jobs = True
    producer._client = IppClient(  # the printer disappears
        FAKE_URI,
        transport=FailingTransport(
            httpx.ASGITransport(app=fake), "Get-Printer-Attributes", httpx.ConnectError
        ),
    )
    assert await producer.probe_once() is None
    row = await _cache(async_session_factory, pid)
    assert row.parsed["online"] is False and row.parsed["markers"]
    assert producer._failures == 1
    producer._client = IppClient(FAKE_URI, transport=httpx.ASGITransport(app=fake))
    assert await producer.probe_once() is not None
    assert producer._failures == 0
    assert (await _cache(async_session_factory, pid)).parsed["online"] is True
    assert bus.publish.call_count == 3  # online, offline, online again
    await producer.stop()


async def test_garbage_answer_does_not_raise(async_session_factory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"\x01\x01\x00\x00garbage")

    producer, pid, _b, _state = _make(
        FakeIppPrinter(), async_session_factory, transport=httpx.MockTransport(handler)
    )
    assert await producer.probe_once() is None
    assert (await _cache(async_session_factory, pid)).parsed["online"] is False
    await producer.stop()


async def test_cache_write_failure_is_swallowed(async_session_factory) -> None:
    class Broken:
        def __call__(self) -> object:
            raise RuntimeError("db down")

    fake = FakeIppPrinter()
    producer, _pid, bus, _state = _make(fake, Broken())  # type: ignore[arg-type]
    assert await producer.probe_once() is not None
    assert bus.publish.call_count == 1
    await producer.stop()


async def test_auto_resume_only_printer_error_pause(async_session_factory) -> None:
    fake = FakeIppPrinter(reasons=["toner-empty-error"])
    err = _pause("printer_error", "toner-empty")
    producer, pid, _b, _state = _make(fake, async_session_factory, pause=err)
    await producer.probe_once()
    assert err.resumed == []  # reason still present
    fake.reasons = ["none"]
    await producer.probe_once()
    assert err.resumed == [pid]

    fake2 = FakeIppPrinter(reasons=["none"])
    user = _pause("user", "user")
    producer2, _pid2, _b2, _s2 = _make(fake2, async_session_factory, pause=user)
    await producer2.probe_once()
    assert user.resumed == [] and user.info is not None  # a user pause is never touched

    unpaused = _Pause(None)
    producer3, _p3, _b3, _s3 = _make(fake2, async_session_factory, pause=unpaused)
    await producer3.probe_once()
    assert unpaused.resumed == []
    for p in (producer, producer2, producer3):
        await p.stop()


async def test_no_auto_resume_while_offline(async_session_factory) -> None:
    fake = FakeIppPrinter()
    err = _pause("printer_error", "toner-empty")
    producer, _pid, _b, _state = _make(
        fake,
        async_session_factory,
        pause=err,
        transport=FailingTransport(
            httpx.ASGITransport(app=fake), "Get-Printer-Attributes", httpx.ConnectError
        ),
    )
    await producer.probe_once()
    assert err.resumed == []
    await producer.stop()


async def test_auto_resume_failure_is_swallowed(async_session_factory) -> None:
    class Raising(_Pause):
        async def resume_printer(self, printer_id: UUID) -> None:
            raise KeyError(printer_id)

    err = Raising(PauseInfo(source="printer_error", reason_code="x", since=datetime.now(UTC)))
    producer, _pid, _b, _state = _make(FakeIppPrinter(), async_session_factory, pause=err)
    assert await producer.probe_once() is not None
    await producer.stop()


async def test_jobs_ahead_excludes_own_job(async_session_factory) -> None:
    fake = FakeIppPrinter(job_script=[3])  # jobs stay pending
    client = IppClient(FAKE_URI, transport=httpx.ASGITransport(app=fake))
    own = await client.print_job(PDF, [], [Attr("document-format", Tag.MIME, ["application/pdf"])])
    foreign = await client.print_job(
        PDF, [], [Attr("document-format", Tag.MIME, ["application/pdf"])]
    )
    await client.aclose()
    state = IppPrinterState(own_job_ids={own.job_id})
    producer, _pid, _b, _s = _make(fake, async_session_factory, state=state)
    record = await producer.probe_once()
    assert record is not None and record.jobs_ahead == 1
    assert foreign.job_id not in state.own_job_ids
    state.own_job_ids.clear()
    record = await producer.probe_once()
    assert record is not None and record.jobs_ahead == 2
    await producer.stop()


async def test_jobs_query_failure_keeps_attribute_count(async_session_factory) -> None:
    fake = FakeIppPrinter()
    producer, _pid, _b, _s = _make(
        fake,
        async_session_factory,
        transport=FailingTransport(httpx.ASGITransport(app=fake), "Get-Jobs", httpx.ReadTimeout),
    )
    record = await producer.probe_once()
    assert record is not None and record.online
    assert record.jobs_ahead == 0  # from queued-job-count
    await producer.stop()


async def test_backoff_doubles_and_is_capped(async_session_factory) -> None:
    producer, *_ = _make(FakeIppPrinter(), async_session_factory, interval_s=30.0)
    assert producer.next_delay() == 30.0
    producer._failures = 1
    assert producer.next_delay() == 60.0
    producer._failures = 3
    assert producer.next_delay() == 240.0
    producer._failures = 50
    assert producer.next_delay() == MAX_BACKOFF_S
    await producer.stop()


async def test_limiter_bounds_concurrent_probes(async_session_factory) -> None:
    running = 0
    peak = 0

    class Slow(httpx.AsyncBaseTransport):
        def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
            self.inner = inner

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.02)
            running -= 1
            return await self.inner.handle_async_request(request)

    fake = FakeIppPrinter()
    limiter = asyncio.Semaphore(1)
    producers = []
    for _ in range(3):
        p, *_rest = _make(
            fake, async_session_factory, transport=Slow(httpx.ASGITransport(app=fake))
        )
        p._limiter = limiter
        producers.append(p)
    await asyncio.gather(*(p.probe_once() for p in producers))
    assert peak == 1
    for p in producers:
        await p.stop()


async def test_loop_survives_and_stops(async_session_factory) -> None:
    fake = FakeIppPrinter()
    producer, _pid, bus, _s = _make(fake, async_session_factory, interval_s=0.01)
    await producer.start()
    await asyncio.sleep(0.15)
    await producer.stop()
    assert bus.publish.call_count == 1


async def test_sse_snapshot_describes_a_page_printer(async_session_factory) -> None:
    from app.services.sse_snapshot import build_snapshot

    fake = FakeIppPrinter(reasons=["media-empty-error"])
    producer, pid, _b, _s = _make(fake, async_session_factory)
    await producer.probe_once()
    await producer.stop()
    async with async_session_factory() as s:
        events = await build_snapshot(s, pid)
    status = next(e for e in events if e["type"] == "printer.status")
    assert status["data"]["kind"] == "page"
    assert status["data"]["blocking_reason"] == "media-empty"
    assert status["data"]["reasons"] == ["media-empty"]
    assert all(e["type"] != "printer.tape_changed" for e in events)
