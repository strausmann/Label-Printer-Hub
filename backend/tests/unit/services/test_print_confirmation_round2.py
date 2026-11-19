# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""#393 review round 2: the real QL backend over ``FakeIppPrinter``, through the queue.

- N1: a timed-out job whose Cancel-Job fails ends ``outcome_unknown`` even with a new error bit.
- N2: a job the printer purged before the Cancel-Job is left to the label counter.
- N3: a label that finishes while the printer comes to its stop point counts as printed.
- Edge: an aborted job that still reports every impression is printed; with a blocking bit the
  run stops with nothing to reprint from that group.
- N4: a printer whose test print stored ``raw`` gets its next test print over TCP 9100.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.printer_backends import post_send
from app.printer_backends.brother_ql_backend import BrotherQLBackend
from app.printer_backends.exceptions import LabelsNotConfirmedError, TapeEmptyError
from app.printer_backends.snmp_helper import PreflightStatus
from app.printer_backends.tape_confirmation import ConfirmationRecord
from app.printer_models.ql import QL820NWBDriver
from app.services.job_lifecycle import JobState
from app.services.print_queue import MAX_LABELS_PER_TAPE_JOB, TAPE_GROUP_SIZE, PrintQueue
from app.services.tape_registry import TapeRegistry
from PIL import Image

from tests.helpers.fake_ipp_printer import FailingTransport, FakeIppPrinter
from tests.unit.services.test_print_queue_tape_runs import (
    TapeRoll,
    _codes,
    _run,
    _SlowDoneStore,
    _states,
    _stopped,
    _until,
)

pytestmark = pytest.mark.anyio

RASTER = ["application/octet-stream"]


@pytest.fixture(autouse=True)
def _fast_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Confirmation timeouts of a fraction of a second, polls every millisecond."""
    from app.printer_backends import tape_confirmation

    monkeypatch.setattr(post_send, "confirm_timeout_s", lambda labels: 0.1)
    monkeypatch.setattr(post_send, "CONFIRM_POLL_S", 0.001)
    monkeypatch.setattr(tape_confirmation, "CONFIRM_POLL_S", 0.001, raising=False)
    monkeypatch.setattr(tape_confirmation, "CANCEL_STOP_S", 0.5, raising=False)


class _Printer:
    """SNMP and TCP 9100 of a QL, faked; the IPP side is a ``FakeIppPrinter``."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        transport: httpx.AsyncBaseTransport,
        *,
        tape_mm: int = 29,
        counter: int | None = 100,
    ) -> None:
        self.counter = counter
        self.flags_after: list[str] = []
        self.reads = 0
        self.raw_sent = 0
        self.count_on_raw = False

        async def preflight(host: str, **_: Any) -> PreflightStatus:
            self.reads += 1
            first = self.reads == 1  # the read before sending
            return PreflightStatus(
                hr_printer_status="idle",
                loaded_tape_mm=tape_mm,
                error_flags=[] if first else list(self.flags_after),
                media_raw=f"{tape_mm}mm",
                marker_count=self.counter,
            )

        def send(*_a: Any, **_k: Any) -> dict[str, str]:
            self.raw_sent += 1
            if self.count_on_raw and self.counter is not None:
                self.counter += 1
            return {"outcome": "sent"}

        monkeypatch.setattr("app.printer_backends.brother_ql_backend.query_preflight", preflight)
        monkeypatch.setattr("app.printer_backends.brother_ql_backend._helpers_send", send)
        self.backend = BrotherQLBackend(host="192.0.2.60", ipp_transport=transport)
        self.queue_printer = QL820NWBDriver(backend=self.backend).make_queue_printer(
            TapeRegistry(), printer_id=uuid4()
        )
        self.queue_printer.post_send_settle_s = 0


def _asgi(fake: FakeIppPrinter) -> httpx.AsyncBaseTransport:
    return httpx.ASGITransport(app=fake)  # type: ignore[arg-type]


async def _single(printer: _Printer, **options: Any) -> Any:
    queue = PrintQueue([printer.queue_printer])
    await queue.start()
    job_id = await queue.submit(
        printer.queue_printer.id, Image.new("1", (306, 120)), tape_mm=29, **options
    )
    await queue.wait_for_job(job_id, timeout_s=10)
    return queue, await queue.get(job_id)


def _cancel_fails(fake: FakeIppPrinter) -> httpx.AsyncBaseTransport:
    return FailingTransport(_asgi(fake), "Cancel-Job", httpx.ReadError)


# ---------------------------------------------------------------------------- N1


async def test_a_failed_cancel_with_a_new_bit_is_outcome_unknown_for_a_single_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeIppPrinter(formats=RASTER, job_script=[5], impressions_script=[0])
    printer = _Printer(monkeypatch, _cancel_fails(fake))
    printer.flags_after = ["noPaper"]
    queue, job = await _single(printer)
    try:
        assert job.state == JobState.FAILED
        assert job.error_code == "outcome_unknown"
        assert "may still print" in (job.error_message or "")
    finally:
        await queue.stop()


async def test_a_failed_cancel_with_a_new_bit_is_outcome_unknown_for_a_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeIppPrinter(formats=RASTER, job_script=[5], impressions_script=[1])
    printer = _Printer(monkeypatch, _cancel_fails(fake), tape_mm=12)
    printer.flags_after = ["noPaper"]
    queue, run_id, ids, _ = await _run(printer.queue_printer, 3)
    try:
        await _until(_stopped(queue, run_id))
        assert await _codes(queue, ids) == ["outcome_unknown"] * 3
    finally:
        await queue.stop(timeout_s=2.0)


# ---------------------------------------------------------------------------- N2


class _PurgeBeforeCancel(httpx.AsyncBaseTransport):
    """The printer finishes and drops the job right before the Cancel-Job reaches it."""

    def __init__(self, fake: FakeIppPrinter) -> None:
        self.fake = fake
        self.inner = _asgi(fake)
        self.on_purge: Any = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        if b"\x00\x08" in body[2:4]:  # operation-id Cancel-Job
            self.fake.forget_jobs()
            if self.on_purge is not None:
                self.on_purge()
        return await self.inner.handle_async_request(request)


async def test_a_job_purged_before_the_cancel_is_left_to_the_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeIppPrinter(formats=RASTER, job_script=[5], impressions_script=[0])
    transport = _PurgeBeforeCancel(fake)
    printer = _Printer(monkeypatch, transport)

    def came_out() -> None:
        printer.counter = 101  # the job finished and was purged: the label is out

    transport.on_purge = came_out
    queue, job = await _single(printer)
    try:
        assert job.state == JobState.COMPLETED
        assert [op.operation for op in fake.received].count("Cancel-Job") == 1
    finally:
        await queue.stop()


async def test_a_job_purged_before_the_cancel_without_a_counter_counts_as_printed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fake = FakeIppPrinter(formats=RASTER, job_script=[5], impressions_script=[0])
    printer = _Printer(monkeypatch, _PurgeBeforeCancel(fake), counter=None)
    with caplog.at_level(logging.WARNING, logger="app.printer_backends.post_send"):
        queue, job = await _single(printer)
    try:
        assert job.state == JobState.COMPLETED
        assert any("counted as printed" in r.message for r in caplog.records)
    finally:
        await queue.stop()


# ---------------------------------------------------------------------------- N3


async def test_a_label_that_finishes_during_the_cancel_counts_as_printed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Two labels; the cancel takes two polls to reach the stop point, one label finished then.
    fake = FakeIppPrinter(
        formats=RASTER,
        job_script=[5],
        impressions_script=[0],
        cancel_steps=2,
        impressions_after_cancel=1,
    )
    printer = _Printer(monkeypatch, _asgi(fake))
    await printer.backend.print_images([Image.new("1", (306, 120))] * 2, _spec_29())
    with pytest.raises(LabelsNotConfirmedError) as err:
        await printer.queue_printer.check_after_send()
    assert (err.value.printed, err.value.expected) == (1, 2)
    assert [op.operation for op in fake.received].count("Get-Job-Attributes") >= 3


def _spec_29() -> Any:
    from app.services.status_block import MediaType

    return TapeRegistry.lookup_ql(29, MediaType.CONTINUOUS_LENGTH_TAPE)


# ---------------------------------------------------------------------------- edge: printed == N


async def test_an_aborted_job_that_reports_every_impression_is_printed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeIppPrinter(formats=RASTER, job_script=[8], impressions_script=[1])
    printer = _Printer(monkeypatch, _asgi(fake))
    queue, job = await _single(printer)
    try:
        assert job.state == JobState.COMPLETED
    finally:
        await queue.stop()


async def test_every_impression_with_a_bit_completes_the_single_job_and_pauses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeIppPrinter(formats=RASTER, job_script=[8], impressions_script=[1])
    printer = _Printer(monkeypatch, _asgi(fake))
    printer.flags_after = ["noPaper"]
    queue, job = await _single(printer)
    try:
        assert job.state == JobState.COMPLETED
        assert queue.is_paused(printer.queue_printer.id)
    finally:
        await queue.stop()


async def test_every_impression_of_a_group_with_a_bit_stops_the_run_after_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeIppPrinter(formats=RASTER, job_script=[8], impressions_script=[TAPE_GROUP_SIZE])
    printer = _Printer(monkeypatch, _asgi(fake), tape_mm=12)
    printer.flags_after = ["noPaper"]
    queue, run_id, ids, _ = await _run(printer.queue_printer, TAPE_GROUP_SIZE + 3)
    try:
        await _until(_stopped(queue, run_id))
        states = await _states(queue, ids)
        assert states[:TAPE_GROUP_SIZE] == [JobState.COMPLETED] * TAPE_GROUP_SIZE
        assert await _codes(queue, ids[TAPE_GROUP_SIZE:]) == ["not_started"] * 3
        assert queue.is_paused(printer.queue_printer.id)
        info = queue.run_info(run_id)
        assert info is not None
        assert info.reprint_from == TAPE_GROUP_SIZE + 1
        result = await queue.reprint_from(run_id, TAPE_GROUP_SIZE + 1)
        assert len(result.new_job_ids) == 3
    finally:
        await queue.stop(timeout_s=2.0)


async def test_every_impression_of_a_group_without_a_bit_lets_the_run_go_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeIppPrinter(formats=RASTER, job_script=[8], impressions_script=[3])
    printer = _Printer(monkeypatch, _asgi(fake), tape_mm=12)
    queue, run_id, ids, _ = await _run(printer.queue_printer, 3)
    try:
        await _until(lambda: queue.run_info(run_id) is None)
        assert await _states(queue, ids) == [JobState.COMPLETED] * 3
    finally:
        await queue.stop(timeout_s=2.0)


# ---------------------------------------------------------------------------- N4


async def test_a_test_print_after_an_incomplete_ipp_job_goes_over_9100(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The printer took an earlier test label over IPP and never completed it: IPP is not tried
    # again, the label counter confirms the 9100 send (I1: a refused IPP is tried again).
    fake = FakeIppPrinter(formats=RASTER, job_script=[9])
    printer = _Printer(monkeypatch, _asgi(fake))
    printer.count_on_raw = True
    printer.backend.send_state.record = ConfirmationRecord(
        "raw", False, datetime(2026, 11, 18, tzinfo=UTC), ipp_incomplete=True
    )
    stored: list[ConfirmationRecord] = []

    async def sink(record: ConfirmationRecord) -> None:
        stored.append(record)

    printer.backend.send_state.sink = sink
    queue, job = await _single(printer, detect_confirmation=True)
    try:
        assert job.state == JobState.COMPLETED
        assert "Print-Job" not in [op.operation for op in fake.received]
        assert printer.raw_sent == 1
        assert [(r.confirm_transport, r.label_counter, r.ipp_incomplete) for r in stored] == [
            ("raw", True, True)
        ]
    finally:
        await queue.stop()


# ---------------------------------------------------------------------------- F1 (round 3)


async def test_the_last_group_fully_printed_with_a_bit_finishes_the_run_and_pauses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeIppPrinter(formats=RASTER, job_script=[8], impressions_script=[3])
    printer = _Printer(monkeypatch, _asgi(fake), tape_mm=12)
    printer.flags_after = ["noPaper"]
    queue, run_id, ids, _ = await _run(printer.queue_printer, 3)
    try:
        await _until(lambda: queue.run_info(run_id) is None)  # finished, not held as stopped
        assert await _states(queue, ids) == [JobState.COMPLETED] * 3
        assert queue.is_paused(printer.queue_printer.id)
        assert queue.held_runs(printer.queue_printer.id) == []
    finally:
        await queue.stop(timeout_s=2.0)


# ---------------------------------------------------------------------------- M3 (final review)


class _BitWithTheFirstGroup(TapeRoll):
    """Every label of the first group printed, and the roll reported a blocking bit with it."""

    async def check_status(self) -> None:
        self.checks += 1
        if self.checks == 1:
            exc = TapeEmptyError()
            exc.printed = TAPE_GROUP_SIZE
            raise exc


async def test_a_stop_after_the_group_holds_the_next_part_when_its_own_is_cancelled() -> None:
    """The rows of the printed group are written before the run stops. A cancel of the part's
    other labels in that window ends the part and moves the run on to the next part; the stop
    must still hold the next part's labels as not started, not leave them queued."""
    printer = _BitWithTheFirstGroup()
    store = _SlowDoneStore()
    queue, run_id, ids, _ = await _run(printer, MAX_LABELS_PER_TAPE_JOB + 10, store=store)
    store.slow = ids[0]
    try:
        await asyncio.wait_for(store.reached.wait(), 3.0)
        for jid in ids[TAPE_GROUP_SIZE:MAX_LABELS_PER_TAPE_JOB]:  # the rest of the first part
            assert await queue.cancel(str(jid))
        store.release.set()
        await _until(_stopped(queue, run_id))
        await _until(lambda: queue.is_paused(printer.id))
        states = await _states(queue, ids)
        assert states[:TAPE_GROUP_SIZE] == [JobState.COMPLETED] * TAPE_GROUP_SIZE
        assert states[TAPE_GROUP_SIZE:MAX_LABELS_PER_TAPE_JOB] == [JobState.CANCELLED] * 40
        assert await _codes(queue, ids[MAX_LABELS_PER_TAPE_JOB:]) == ["not_started"] * 10
        info = queue.run_info(run_id)
        assert info is not None and info.reprint_from == TAPE_GROUP_SIZE + 1
    finally:
        store.release.set()
        await queue.stop(timeout_s=2.0)
