# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""#277: tape jobs of at most 50 labels, sent in checked groups of 10.

A tape batch of more than ``MAX_LABELS_PER_TAPE_JOB`` labels is split into sub-jobs; the next one
starts only after ``confirm_run``. Inside a sub-job the labels go out in groups of
``TAPE_GROUP_SIZE`` with a status check after each group. When the tape runs out (or another
error ends a group) the finished groups are done, the current group's outcome is unknown, every
label after it is not started, and the printer is paused. ``reprint_from`` re-queues label N to
the end of the unknown group plus the labels that were not started.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from functools import partial
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.models.job import Job as DbJob
from app.models.job import JobState as DbJobState
from app.printer_backends.exceptions import (
    PrintFailedError,
    TapeEmptyError,
    TapeMismatchError,
    refused_before_sending,
)
from app.services.job_lifecycle import JobState
from app.services.job_store import MemoryJobStore
from app.services.print_queue import (
    MAX_LABELS_PER_TAPE_JOB,
    TAPE_GROUP_SIZE,
    PrintQueue,
    RunStateError,
)
from PIL import Image

pytestmark = pytest.mark.anyio


class TapeRoll:
    """A tape printer whose tape runs out after ``k`` labels (``None``: never).

    ``mid_stream_error``: the label stream breaks when the tape ends inside a call (the hub sees
    a write error); otherwise the printer just stops and the call returns. The SNMP check says
    ``noPaper`` once the tape is used up.
    """

    def __init__(self, k: int | None = None, *, mid_stream_error: bool = False) -> None:
        self.id = uuid4()
        self.k = k
        self.mid_stream_error = mid_stream_error
        self.printed = 0
        self.calls: list[int] = []
        self.options: list[dict[str, Any]] = []
        self.checks = 0
        self.gate: asyncio.Event | None = None  # set: a call waits for it before printing
        self.started = asyncio.Event()

    async def print_image(self, image: Image.Image, *, tape_mm: int, **options: Any) -> None:
        await self.print_images([image], tape_mm=tape_mm, **options)

    async def print_images(
        self, images: list[Image.Image], *, tape_mm: int, **options: Any
    ) -> None:
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        self.calls.append(len(images))
        self.options.append(dict(options))
        if self.k is not None and self.printed + len(images) > self.k:
            self.printed = max(self.printed, self.k)
            if self.mid_stream_error:
                raise PrintFailedError("write failed")
            return
        self.printed += len(images)

    async def check_status(self) -> None:
        self.checks += 1
        if self.k is not None and self.printed >= self.k:
            raise TapeEmptyError()


def _img() -> Image.Image:
    return Image.new("1", (80, 40), color=1)


async def _run(
    printer: TapeRoll,
    n: int,
    store: MemoryJobStore | None = None,
    on_run_change: Callable[[UUID, UUID, str], None] | None = None,
    **options: Any,
) -> tuple[PrintQueue, UUID, list[UUID], MemoryJobStore]:
    store = store or MemoryJobStore()
    queue = PrintQueue([printer], store=store, on_run_change=on_run_change)
    await queue.start()  # running before the rows exist, as in the hub: no recovery of them
    ids = [uuid4() for _ in range(n)]
    for i, jid in enumerate(ids):
        await store.save_queued(
            DbJob(
                id=jid,
                printer_id=printer.id,
                payload={
                    "tape_mm": 12,
                    "content_type": "qr_two_lines",
                    "rendered_tape_mm": 12,
                    "label_data": {
                        "source_app": "manual",
                        "title": f"L{i + 1}",
                        "primary_id": f"P{i + 1}",
                        "qr_payload": f"https://x.example.invalid/{i + 1}",
                    },
                    "options": {},
                    "tape_run": {"awaits_confirmation": i >= MAX_LABELS_PER_TAPE_JOB},
                },
            )
        )
    run_id = await queue.enqueue_batch(
        printer_id=printer.id,
        images=[_img() for _ in range(n)],
        job_ids=ids,
        tape_mm=12,
        options={"half_cut": True, "orientation": "across", "layout_preset": "qr_left", **options},
    )
    return queue, run_id, ids, store


async def _until(cond: Callable[[], bool], timeout: float = 3.0) -> None:
    async with asyncio.timeout(timeout):
        while not cond():
            await asyncio.sleep(0.01)


async def _states(queue: PrintQueue, ids: list[UUID]) -> list[JobState]:
    return [(await queue.get(j)).state for j in ids]


async def _codes(queue: PrintQueue, ids: list[UUID]) -> list[str | None]:
    return [(await queue.get(j)).error_code for j in ids]


def _stopped(queue: PrintQueue, run_id: UUID) -> Callable[[], bool]:
    return lambda: queue.run_info(run_id) is not None and queue.run_info(run_id).state == "stopped"  # type: ignore[union-attr]


def test_the_limits_are_named_constants() -> None:
    assert MAX_LABELS_PER_TAPE_JOB == 50
    assert TAPE_GROUP_SIZE == 10


async def test_a_sub_job_goes_out_in_groups_with_a_check_after_each() -> None:
    printer = TapeRoll()
    queue, run_id, ids, store = await _run(printer, 25)
    try:
        await _until(lambda: queue.run_info(run_id) is None)  # done runs are forgotten
        assert printer.calls == [10, 10, 5]
        assert printer.checks == 3
        assert await _states(queue, ids) == [JobState.COMPLETED] * 25
        assert {(await store.get(j)).state for j in ids} == {DbJobState.DONE.value}  # type: ignore[union-attr]
        # every group carries the job's QL/PT options (#258: orientation and preset)
        assert all(o["orientation"] == "across" for o in printer.options)
        assert all(o["layout_preset"] == "qr_left" for o in printer.options)
    finally:
        await queue.stop(timeout_s=2.0)


@pytest.mark.parametrize("mid_stream_error", [False, True])
async def test_tape_end_inside_a_group(mid_stream_error: bool) -> None:
    printer = TapeRoll(15, mid_stream_error=mid_stream_error)
    queue, run_id, ids, store = await _run(printer, 30)
    try:
        await _until(_stopped(queue, run_id))
        states = await _states(queue, ids)
        codes = await _codes(queue, ids)
        assert states[:10] == [JobState.COMPLETED] * 10
        assert states[10:] == [JobState.FAILED] * 20
        assert codes[10:20] == ["outcome_unknown"] * 10
        assert codes[20:] == ["not_started"] * 10
        assert printer.calls == [10, 10]  # nothing after the unknown group is sent
        assert queue.is_paused(printer.id)
        assert queue.pause_info(printer.id).reason_code in ("tape_empty", "print_failed")  # type: ignore[union-attr]
        rows = [await store.get(j) for j in ids]
        assert {r.state for r in rows[10:20]} == {DbJobState.FAILED_RESTART.value}  # type: ignore[union-attr]
        assert {r.state for r in rows[20:]} == {DbJobState.FAILED.value}  # type: ignore[union-attr]
        info = queue.run_info(run_id)
        assert info is not None and (info.unknown_from, info.unknown_to) == (11, 20)
    finally:
        await queue.stop(timeout_s=2.0)


async def test_tape_end_at_a_group_boundary() -> None:
    printer = TapeRoll(20)
    queue, run_id, ids, _ = await _run(printer, 30)
    try:
        await _until(_stopped(queue, run_id))
        states = await _states(queue, ids)
        codes = await _codes(queue, ids)
        assert states[:10] == [JobState.COMPLETED] * 10
        # the group that used the last label up: the check after it says noPaper, so its
        # outcome is unknown (the user counts at most one group)
        assert codes[10:20] == ["outcome_unknown"] * 10
        assert codes[20:] == ["not_started"] * 10
        assert queue.pause_info(printer.id).reason_code == "tape_empty"  # type: ignore[union-attr]
    finally:
        await queue.stop(timeout_s=2.0)


async def test_tape_end_in_the_last_group_of_a_sub_job_stops_the_next_sub_jobs_too() -> None:
    printer = TapeRoll(45)
    queue, run_id, ids, _ = await _run(printer, 60)
    try:
        await _until(_stopped(queue, run_id))
        codes = await _codes(queue, ids)
        states = await _states(queue, ids)
        assert states[:40] == [JobState.COMPLETED] * 40
        assert codes[40:50] == ["outcome_unknown"] * 10
        assert codes[50:] == ["not_started"] * 10  # sub-job 2 never started
        assert queue.is_paused(printer.id)
    finally:
        await queue.stop(timeout_s=2.0)


async def test_fifty_labels_are_one_sub_job() -> None:
    printer = TapeRoll()
    queue, run_id, ids, _ = await _run(printer, 50)
    try:
        await _until(lambda: queue.run_info(run_id) is None)
        assert printer.calls == [10] * 5
        assert await _states(queue, ids) == [JobState.COMPLETED] * 50
    finally:
        await queue.stop(timeout_s=2.0)


async def test_fifty_one_labels_wait_for_confirmation_before_the_second_sub_job() -> None:
    printer = TapeRoll()
    queue, run_id, ids, _ = await _run(printer, 51)
    try:
        await _until(lambda: queue.run_info(run_id).state == "awaiting_confirmation")  # type: ignore[union-attr]
        info = queue.run_info(run_id)
        assert info is not None and (info.current_sub_job, info.sub_jobs) == (2, 2)
        await asyncio.sleep(0.2)
        assert printer.calls == [10] * 5  # sub-job 2 has not started
        assert (await queue.get(ids[50])).state == JobState.QUEUED

        await queue.confirm_run(run_id)

        await _until(lambda: queue.run_info(run_id) is None)
        assert printer.calls == [10] * 5 + [1]
        assert (await queue.get(ids[50])).state == JobState.COMPLETED
    finally:
        await queue.stop(timeout_s=2.0)


class _SlowDoneStore(MemoryJobStore):
    """A store whose ``mark_done`` of one label waits for ``release`` (a slow database write)."""

    def __init__(self) -> None:
        super().__init__()
        self.slow: UUID | None = None
        self.reached = asyncio.Event()
        self.release = asyncio.Event()

    async def mark_done(self, job_id: UUID) -> None:
        if job_id == self.slow:
            self.reached.set()
            await self.release.wait()
        await super().mark_done(job_id)


async def _drained(queue: PrintQueue, printer: TapeRoll) -> None:
    """Wait until everything queued for *printer* so far is through: one more label, queued
    behind it, has printed (the queue is FIFO per printer). Event-driven, no sleep."""
    sentinel = await queue.submit(printer.id, _img(), 12)
    await queue.wait_for_job(sentinel, timeout_s=3.0)


async def _start(
    printer: TapeRoll, store: _SlowDoneStore, n: int, *, slot: UUID | None = None
) -> tuple[PrintQueue, UUID, list[UUID]]:
    queue = PrintQueue([printer], store=store)
    await queue.start()
    ids = [uuid4() for _ in range(n)]
    for jid in ids:
        await store.save_queued(DbJob(id=jid, printer_id=printer.id, payload={"tape_mm": 12}))
    run_id = await queue.enqueue_batch(
        printer_id=printer.id, images=[_img() for _ in ids], job_ids=ids, tape_mm=12, options={}
    )
    return queue, run_id, ids


async def test_a_part_whose_labels_are_done_takes_the_continue_while_its_rows_are_written() -> None:
    """#347: the print status offers Continue as soon as every label of the part is done (the job
    events say so). The rows of the last group are written after those events; the run must
    already wait for the confirmation then, or the Continue gets ``run_not_awaiting_confirmation``.
    """
    printer = TapeRoll()
    store = _SlowDoneStore()
    queue = PrintQueue([printer], store=store)
    await queue.start()
    ids = [uuid4() for _ in range(51)]
    store.slow = ids[MAX_LABELS_PER_TAPE_JOB - TAPE_GROUP_SIZE]  # the first row of the last group
    for jid in ids:
        await store.save_queued(DbJob(id=jid, printer_id=printer.id, payload={"tape_mm": 12}))
    run_id = await queue.enqueue_batch(
        printer_id=printer.id, images=[_img() for _ in ids], job_ids=ids, tape_mm=12, options={}
    )
    try:
        await asyncio.wait_for(store.reached.wait(), 3.0)
        # What the client sees: labels 1-50 done, label 51 queued. The rows are still being written.
        assert await _states(queue, ids[:MAX_LABELS_PER_TAPE_JOB]) == [JobState.COMPLETED] * 50
        assert (await queue.get(ids[50])).state == JobState.QUEUED
        info = queue.run_info(run_id)
        assert info is not None and info.state == "awaiting_confirmation"

        await queue.confirm_run(run_id)  # the Continue of the print status
        store.release.set()

        await _until(lambda: queue.run_info(run_id) is None)
        await _drained(queue, printer)
        # the second part printed once (the last 1 is the drain label): the end of the first
        # part did not hold or start it again
        assert printer.calls == [10] * 5 + [1] + [1]
        assert (await queue.get(ids[50])).state == JobState.COMPLETED
    finally:
        store.release.set()
        await queue.stop(timeout_s=2.0)


async def test_a_part_whose_tail_was_cancelled_takes_the_continue_after_its_last_group() -> None:
    """#347 review I1: labels 41-50 of part 1 are cancelled while queued. Group 4 is then the last
    group that prints; once it is done the client sees part 1 over and offers Continue, while the
    rows of group 4 are still being written. The run must wait already."""
    printer = TapeRoll()
    printer.gate = asyncio.Event()
    store = _SlowDoneStore()
    queue, run_id, ids = await _start(printer, store, 51)
    store.slow = ids[30]  # the first row of group 4
    try:
        await printer.started.wait()  # group 1 is at the printer
        for jid in ids[40:50]:
            assert await queue.cancel(str(jid))
        printer.gate.set()
        await asyncio.wait_for(store.reached.wait(), 3.0)
        assert await _states(queue, ids[:40]) == [JobState.COMPLETED] * 40
        assert await _states(queue, ids[40:50]) == [JobState.CANCELLED] * 10
        assert (await queue.get(ids[50])).state == JobState.QUEUED
        info = queue.run_info(run_id)
        assert info is not None and info.state == "awaiting_confirmation"

        await queue.confirm_run(run_id)
        store.release.set()

        await _until(lambda: queue.run_info(run_id) is None)
        await _drained(queue, printer)
        assert printer.calls == [10] * 4 + [1] + [1]
        assert (await queue.get(ids[50])).state == JobState.COMPLETED
    finally:
        printer.gate.set()
        store.release.set()
        await queue.stop(timeout_s=2.0)


async def test_the_last_part_ends_the_run_while_its_rows_are_written() -> None:
    """#347 review M1a: when the last part's labels are done the run is over at once: a Continue
    then is refused as for a finished run (KeyError, the API's 404), and nothing starts again."""
    printer = TapeRoll()
    store = _SlowDoneStore()
    queue, run_id, ids = await _start(printer, store, 51)
    store.slow = ids[50]
    try:
        await _until(lambda: queue.run_info(run_id).state == "awaiting_confirmation")  # type: ignore[union-attr]
        await queue.confirm_run(run_id)
        await asyncio.wait_for(store.reached.wait(), 3.0)
        assert (await queue.get(ids[50])).state == JobState.COMPLETED
        assert queue.run_info(run_id) is None
        with pytest.raises(KeyError):
            await queue.confirm_run(run_id)
        store.release.set()
        await _drained(queue, printer)
        assert printer.calls == [10] * 5 + [1] + [1]
    finally:
        store.release.set()
        await queue.stop(timeout_s=2.0)


async def test_a_discard_while_the_rows_are_written_cancels_the_waiting_part_only() -> None:
    """#347 review M1c: a discard in the write window cancels label 51; the rows of the printed
    group are still written done, and nothing prints twice."""
    printer = TapeRoll()
    store = _SlowDoneStore()
    queue, run_id, ids = await _start(printer, store, 51)
    store.slow = ids[40]
    try:
        await asyncio.wait_for(store.reached.wait(), 3.0)
        await queue.discard_run(run_id)
        assert (await queue.get(ids[50])).state == JobState.CANCELLED
        store.release.set()
        await _drained(queue, printer)
        assert printer.calls == [10] * 5 + [1]  # the 1 is the drain label
        rows = [await store.get(j) for j in ids]
        assert [r.state for r in rows if r is not None][:50] == [DbJobState.DONE.value] * 50
        assert queue.run_info(run_id) is None
    finally:
        store.release.set()
        await queue.stop(timeout_s=2.0)


async def test_cancelling_the_tail_during_the_row_writes_never_gives_a_409_window() -> None:
    """#347 re-review R2: group 4 is printed, its rows are being written, labels 41-50 are still
    queued (so the group is not the last one when it is decided). Cancelling them in that window
    leaves nothing of the part to print: the run must wait for the Continue at once, not only
    when the worker gets to its fallback after the writes."""
    printer = TapeRoll()
    store = _SlowDoneStore()
    queue, run_id, ids = await _start(printer, store, 51)
    store.slow = ids[30]  # the first row of group 4
    try:
        await asyncio.wait_for(store.reached.wait(), 3.0)
        assert not _waits(queue, run_id)  # labels 41-50 are queued: the part is not over
        for jid in ids[40:50]:
            assert await queue.cancel(str(jid))
        assert _waits(queue, run_id)  # the rows are still not written
        await queue.confirm_run(run_id)  # no 409
        printer.gate = asyncio.Event()  # part 2 stops at the printer
        store.release.set()
        async with asyncio.timeout(3.0):  # the worker has finished part 1 (rows written)
            while (row := await store.get(ids[39])) is None or row.state != DbJobState.DONE.value:
                await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)  # lets the worker run its end-of-sub-job step
        # part 2 is under way: the worker must not advance the run a second time
        info = queue.run_info(run_id)
        assert info is not None and info.state == "printing"
        printer.gate.set()
        await _until(lambda: queue.run_info(run_id) is None)
        await _drained(queue, printer)
        # part 1 printed 30 labels before the write (3 groups) + group 4; part 2 once; no repeat
        assert printer.calls == [10] * 4 + [1] + [1]
        assert (await queue.get(ids[50])).state == JobState.COMPLETED
    finally:
        store.release.set()
        await queue.stop(timeout_s=2.0)


async def test_a_part_emptied_by_cancels_before_the_worker_takes_it_does_not_advance_twice() -> (
    None
):
    """#347 re-review 2 I1: part 2 is confirmed while the printer is paused, all its labels are
    cancelled (the cancel advances the run to part 3), part 3 is confirmed. When the worker then
    takes part 2's (empty) batch it must not advance the run again: part 3 is printing."""
    printer = TapeRoll()
    store = _SlowDoneStore()
    queue, run_id, ids = await _start(printer, store, 101)  # parts 50 / 50 / 1
    try:
        await _until(lambda: _waits(queue, run_id))
        await queue.pause_printer(printer.id, reason="user")
        await queue.confirm_run(run_id)  # part 2 is queued, the worker is held by the pause
        for jid in ids[50:100]:
            assert await queue.cancel(str(jid))
        assert _waits(queue, run_id)  # the cancel moved the run on to part 3
        await queue.confirm_run(run_id)  # part 3 is queued behind part 2's item
        printer.gate = asyncio.Event()
        printer.started.clear()
        await queue.resume_printer(printer.id)
        await asyncio.wait_for(printer.started.wait(), 3.0)  # part 3's label is at the printer
        info = queue.run_info(run_id)
        state = info.state if info else None
        printer.gate.set()
        await _drained(queue, printer)
        assert (await queue.get(ids[100])).state == JobState.COMPLETED
        assert state == "printing", f"run state while part 3 prints: {state}"
    finally:
        if printer.gate is not None:
            printer.gate.set()
        await queue.stop(timeout_s=2.0)


class _FailingDoneStore(MemoryJobStore):
    """A store whose ``mark_done`` of one label raises *exc* (a failing or cut-short write)."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_on: UUID | None = None
        self.exc: BaseException = RuntimeError("store down")

    async def mark_done(self, job_id: UUID) -> None:
        if job_id == self.fail_on:
            raise self.exc
        await super().mark_done(job_id)


@pytest.mark.parametrize("exc", [RuntimeError("store down"), asyncio.CancelledError()])
async def test_labels_of_a_limit_discarded_run_are_not_left_queued_when_the_done_write_fails(
    exc: BaseException,
) -> None:
    """#347 re-review R1: a third waiting run discards the oldest one in memory. When the rows of
    the printed group then fail (or the worker is cancelled), the discarded run's rows must still
    be written ``cancelled``, not left ``queued`` while memory says they are gone."""
    printer = TapeRoll()
    store = _FailingDoneStore()
    queue = PrintQueue([printer], store=store)
    await queue.start()
    try:
        runs: list[tuple[UUID, list[UUID]]] = []
        for _ in range(2):
            ids = [uuid4() for _ in range(51)]
            for jid in ids:
                await store.save_queued(DbJob(id=jid, printer_id=printer.id, payload={}))
            run_id = await queue.enqueue_batch(
                printer_id=printer.id,
                images=[_img() for _ in ids],
                job_ids=ids,
                tape_mm=12,
                options={},
            )
            runs.append((run_id, ids))
            await _until(partial(_waits, queue, run_id))
        third_ids = [uuid4() for _ in range(51)]
        for jid in third_ids:
            await store.save_queued(DbJob(id=jid, printer_id=printer.id, payload={}))
        store.fail_on = third_ids[MAX_LABELS_PER_TAPE_JOB - 1]
        store.exc = exc
        await queue.enqueue_batch(
            printer_id=printer.id,
            images=[_img() for _ in third_ids],
            job_ids=third_ids,
            tape_mm=12,
            options={},
        )
        discarded = runs[0][1][50]
        await _until(lambda: queue._jobs[str(discarded)].state == JobState.CANCELLED)
        row = None
        async with asyncio.timeout(3.0):
            while row is None or row.state == DbJobState.QUEUED.value:
                await asyncio.sleep(0.01)
                row = await store.get(discarded)
        assert row.state == DbJobState.CANCELLED.value
    finally:
        await queue.stop(timeout_s=2.0)


class _CancelWindowStore(_SlowDoneStore):
    """``_SlowDoneStore`` plus two hooks: ``mark_done`` of ``fail_on`` raises ``exc``, and
    ``mark_cancelled`` of ``gate_cancel`` sets ``cancel_reached`` and waits for
    ``cancel_release`` (then raises ``cancel_exc`` if set). The test lands a cancel exactly in
    that write."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_on: UUID | None = None
        self.exc: BaseException = RuntimeError("store down")
        self.gate_cancel: UUID | None = None
        self.cancel_reached = asyncio.Event()
        self.cancel_release = asyncio.Event()
        self.cancel_exc: BaseException | None = None

    async def mark_done(self, job_id: UUID) -> None:
        if job_id == self.fail_on:
            raise self.exc
        await super().mark_done(job_id)

    async def mark_cancelled(self, job_id: UUID, *, allow_printing: bool = False) -> None:
        if job_id == self.gate_cancel:
            self.cancel_reached.set()
            await self.cancel_release.wait()
            if self.cancel_exc is not None:
                raise self.cancel_exc
        await super().mark_cancelled(job_id, allow_printing=allow_printing)


async def _held_runs(
    queue: PrintQueue, store: MemoryJobStore, printer: TapeRoll, count: int = 2
) -> list[list[UUID]]:
    """*count* runs of 51 labels, each waiting for the Continue of its second part."""
    held: list[list[UUID]] = []
    for _ in range(count):
        ids = [uuid4() for _ in range(51)]
        for jid in ids:
            await store.save_queued(DbJob(id=jid, printer_id=printer.id, payload={}))
        run_id = await queue.enqueue_batch(
            printer_id=printer.id, images=[_img() for _ in ids], job_ids=ids, tape_mm=12, options={}
        )
        await _until(partial(_waits, queue, run_id))
        held.append(ids)
    return held


async def _third_run_in_its_write_window(
    queue: PrintQueue, store: _CancelWindowStore, printer: TapeRoll
) -> tuple[UUID, list[UUID]]:
    """A third run of 51 labels; group 4's rows are being written and labels 41-49 are
    cancelled, so cancelling label 50 empties the part and the held limit discards the oldest
    run."""
    ids = [uuid4() for _ in range(51)]
    store.slow = ids[30]  # group 4's first row: the write window
    for jid in ids:
        await store.save_queued(DbJob(id=jid, printer_id=printer.id, payload={}))
    run_id = await queue.enqueue_batch(
        printer_id=printer.id, images=[_img() for _ in ids], job_ids=ids, tape_mm=12, options={}
    )
    await asyncio.wait_for(store.reached.wait(), 3.0)
    for jid in ids[40:49]:
        assert await queue.cancel(str(jid))
    return run_id, ids


async def test_a_client_cancel_in_the_discarded_rows_write_still_stores_them() -> None:
    """#347 re-review 3 N2 (M2): ``cancel()`` empties the part, the held limit discards the
    oldest run, and the client goes away while the discarded rows are written. The label's own
    row is already ``cancelled``; the discarded row is written by the shielded retry."""
    printer = TapeRoll()
    store = _CancelWindowStore()
    queue = PrintQueue([printer], store=store)
    await queue.start()
    try:
        held = await _held_runs(queue, store, printer)
        run_id, ids = await _third_run_in_its_write_window(queue, store, printer)
        discarded = held[0][50]
        store.gate_cancel = discarded
        task = asyncio.create_task(queue.cancel(str(ids[49])))
        await asyncio.wait_for(store.cancel_reached.wait(), 3.0)
        task.cancel()  # the client goes away inside the discarded rows' write
        store.cancel_release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        own = await store.get(ids[49])
        assert own is not None and own.state == DbJobState.CANCELLED.value
        row = await store.get(discarded)
        assert row is not None and row.state == DbJobState.CANCELLED.value
        assert _waits(queue, run_id)
    finally:
        store.release.set()
        store.cancel_release.set()
        await queue.stop(timeout_s=2.0)


@pytest.mark.parametrize("own_error", [None, RuntimeError("store down")])
async def test_discarded_rows_are_stored_when_the_labels_own_write_is_cut_short(
    own_error: BaseException | None,
) -> None:
    """#347 re-review 3 N1: the client goes away (``None``: a task cancel) or the store fails
    while ``cancel()`` writes the label's own row. The runs the held limit discarded in that
    step must still be written ``cancelled``, not left ``queued`` while memory says they are
    gone; the label itself is kept as unpersisted."""
    printer = TapeRoll()
    store = _CancelWindowStore()
    queue = PrintQueue([printer], store=store)
    await queue.start()
    try:
        held = await _held_runs(queue, store, printer)
        run_id, ids = await _third_run_in_its_write_window(queue, store, printer)
        discarded = held[0][50]
        store.gate_cancel = ids[49]
        store.cancel_exc = own_error
        task = asyncio.create_task(queue.cancel(str(ids[49])))
        await asyncio.wait_for(store.cancel_reached.wait(), 3.0)
        if own_error is None:
            task.cancel()
        store.cancel_release.set()
        with pytest.raises(asyncio.CancelledError if own_error is None else RuntimeError):
            await task
        assert str(ids[49]) in queue._unpersisted
        row = await store.get(discarded)
        assert row is not None and row.state == DbJobState.CANCELLED.value
        assert _waits(queue, run_id)
    finally:
        store.release.set()
        store.cancel_release.set()
        await queue.stop(timeout_s=2.0)


async def test_a_worker_cancelled_in_the_error_paths_write_keeps_the_original_error() -> None:
    """#347 re-review 3 N2 (M3): the rows of the printed group fail, the worker's error path
    writes the discarded run's rows, and the worker is cancelled inside that write. The shielded
    retry finishes the write and the worker ends with the original error, not the cancel."""
    printer = TapeRoll()
    store = _CancelWindowStore()
    queue = PrintQueue([printer], store=store)
    await queue.start()
    try:
        held = await _held_runs(queue, store, printer)
        ids = [uuid4() for _ in range(51)]
        for jid in ids:
            await store.save_queued(DbJob(id=jid, printer_id=printer.id, payload={}))
        store.fail_on = ids[MAX_LABELS_PER_TAPE_JOB - 1]
        discarded = held[0][50]
        store.gate_cancel = discarded
        worker = queue._workers[printer.id]
        await queue.enqueue_batch(
            printer_id=printer.id, images=[_img() for _ in ids], job_ids=ids, tape_mm=12, options={}
        )
        await asyncio.wait_for(store.cancel_reached.wait(), 3.0)  # inside the error path
        worker.cancel()
        store.cancel_release.set()
        done, _ = await asyncio.wait({worker}, timeout=3.0)
        assert worker in done
        assert not worker.cancelled()
        assert isinstance(worker.exception(), RuntimeError)
        row = await store.get(discarded)
        assert row is not None and row.state == DbJobState.CANCELLED.value
    finally:
        store.cancel_release.set()
        await queue.stop(timeout_s=2.0)


async def test_a_failed_write_of_discarded_rows_in_the_error_path_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """#347 re-review 3 N2 (M1): when the error path cannot store the discarded run's rows, it
    says so: a warning of the queue's logger with the run and the number of rows."""
    printer = TapeRoll()
    store = _CancelWindowStore()
    queue = PrintQueue([printer], store=store)
    await queue.start()
    caplog.set_level(logging.WARNING, logger="app.services.print_queue")
    try:
        held = await _held_runs(queue, store, printer)
        ids = [uuid4() for _ in range(51)]
        for jid in ids:
            await store.save_queued(DbJob(id=jid, printer_id=printer.id, payload={}))
        store.fail_on = ids[MAX_LABELS_PER_TAPE_JOB - 1]
        store.gate_cancel = held[0][50]
        store.cancel_exc = RuntimeError("store down")
        store.cancel_release.set()
        run_id = await queue.enqueue_batch(
            printer_id=printer.id, images=[_img() for _ in ids], job_ids=ids, tape_mm=12, options={}
        )
        await asyncio.wait_for(store.cancel_reached.wait(), 3.0)

        def logged() -> list[logging.LogRecord]:
            return [
                r
                for r in caplog.records
                if r.name == "app.services.print_queue"
                and r.levelno == logging.WARNING
                and "discarded runs could not be stored" in r.getMessage()
            ]

        await _until(lambda: bool(logged()))
        message = logged()[0].getMessage()
        assert str(run_id) in message
        assert ": 1 cancelled labels" in message
    finally:
        await queue.stop(timeout_s=2.0)


def _waits(queue: PrintQueue, run_id: UUID) -> bool:
    info = queue.run_info(run_id)
    return info is not None and info.state == "awaiting_confirmation"


async def test_the_held_limit_applies_when_the_part_ends_not_after_its_rows() -> None:
    """#347 review M3a: the run waits from the step that ends its part, so the limit of held runs
    (two per key on a printer) is applied in that step too, not after the rows are written."""
    printer = TapeRoll()
    store = _SlowDoneStore()
    queue = PrintQueue([printer], store=store)
    await queue.start()
    runs: list[tuple[UUID, list[UUID]]] = []
    try:
        for _ in range(2):
            ids = [uuid4() for _ in range(51)]
            run_id = await queue.enqueue_batch(
                printer_id=printer.id,
                images=[_img() for _ in ids],
                job_ids=ids,
                tape_mm=12,
                options={},
            )
            runs.append((run_id, ids))
            await _until(partial(_waits, queue, run_id))
        # The slow row is set before the batch is queued: the worker may take it at once.
        third_ids = [uuid4() for _ in range(51)]
        store.slow = third_ids[MAX_LABELS_PER_TAPE_JOB - 1]
        third = await queue.enqueue_batch(
            printer_id=printer.id,
            images=[_img() for _ in third_ids],
            job_ids=third_ids,
            tape_mm=12,
            options={},
        )
        await asyncio.wait_for(store.reached.wait(), 3.0)
        # the third run waits and the oldest is already discarded, while the rows are written
        assert [i.run_id for i in queue.held_runs(printer.id)] == [runs[1][0], third]
        assert (await queue.get(runs[0][1][50])).error_code == "run_discarded_limit"
        store.release.set()
        await _drained(queue, printer)
        assert [i.run_id for i in queue.held_runs(printer.id)] == [runs[1][0], third]
    finally:
        store.release.set()
        await queue.stop(timeout_s=2.0)


async def test_cancelling_every_label_of_the_waiting_part_ends_the_run() -> None:
    """#347 review M3b: a waiting part whose labels are all cancelled leaves nothing to continue:
    the run is over instead of waiting for ever."""
    printer = TapeRoll()
    states: list[str] = []
    queue, run_id, ids, _ = await _run(
        printer, 52, on_run_change=lambda _r, _p, state: states.append(state)
    )
    try:
        await _until(lambda: queue.run_info(run_id).state == "awaiting_confirmation")  # type: ignore[union-attr]
        assert await queue.cancel(str(ids[50]))
        assert queue.run_info(run_id) is not None  # label 52 still waits
        assert await queue.cancel(str(ids[51]))
        assert queue.run_info(run_id) is None
        assert states[-1] == "finished"
        with pytest.raises(KeyError):
            await queue.confirm_run(run_id)
    finally:
        await queue.stop(timeout_s=2.0)


async def test_confirm_is_refused_unless_the_run_waits_for_it() -> None:
    printer = TapeRoll()
    printer.gate = asyncio.Event()
    queue, run_id, _, _ = await _run(printer, 60)
    try:
        await printer.started.wait()
        with pytest.raises(RunStateError) as err:
            await queue.confirm_run(run_id)  # sub-job 1 is still printing
        assert err.value.code == "run_not_awaiting_confirmation"
        with pytest.raises(KeyError):
            await queue.confirm_run(uuid4())
    finally:
        printer.gate.set()
        await queue.stop(timeout_s=2.0)


async def test_reprint_from_n_requeues_n_to_the_end_of_the_group_and_the_not_started() -> None:
    printer = TapeRoll(15)
    queue, run_id, ids, store = await _run(printer, 30)
    try:
        await _until(_stopped(queue, run_id))
        printer.k = None  # the user put a new tape in

        result = await queue.reprint_from(run_id, 14)

        # labels 14..20 of the unknown group and 21..30 that never started: 17 new jobs
        assert len(result.new_job_ids) == 17
        assert result.confirmed_job_ids == ids[10:13]  # 11..13 printed, the user says
        # N2: the replaced labels keep no picture; the new jobs carry it.
        assert [(await queue.get(j)).image_payload for j in ids[10:]] == [None] * 20
        await _until(lambda: queue.run_info(run_id) is None)
        assert printer.calls[2:] == [10, 7]
        assert not queue.is_paused(printer.id)  # the reprint is the user's go-ahead
        for new in result.new_job_ids:
            assert (await queue.get(new)).state == JobState.COMPLETED
            row = await store.get(new)
            assert row is not None and row.state == DbJobState.DONE.value
        # the clones are the same labels: their payloads are copied from the originals
        first = await store.get(result.new_job_ids[0])
        assert first is not None and first.payload["label_data"]["title"] == "L14"
        assert result.job_ids == [*map(str, ids[:13]), *map(str, result.new_job_ids)]
    finally:
        await queue.stop(timeout_s=2.0)


async def test_reprint_of_a_retried_label_points_at_its_own_source() -> None:
    printer = TapeRoll(15)
    queue, run_id, ids, store = await _run(printer, 30)
    try:
        await _until(_stopped(queue, run_id))
        printer.k = None
        stale = str(uuid4())  # what a retried source carries: the id of ITS parent
        row = await store.get(ids[13])
        assert row is not None
        row.payload["retry_of"] = stale

        result = await queue.reprint_from(run_id, 14)

        first = await store.get(result.new_job_ids[0])
        assert first is not None and first.payload["label_data"]["title"] == "L14"
        assert first.payload["retry_of"] == str(ids[13])  # the reprint repeats the source
        assert first.payload["retry_of"] != stale  # not the source's own parent
    finally:
        await queue.stop(timeout_s=2.0)


@pytest.mark.parametrize("label", [10, 22, 0])
async def test_reprint_from_outside_the_unknown_group_is_refused(label: int) -> None:
    printer = TapeRoll(15)
    queue, run_id, _, _ = await _run(printer, 30)
    try:
        await _until(_stopped(queue, run_id))
        with pytest.raises(RunStateError) as err:
            await queue.reprint_from(run_id, label)
        assert err.value.code == "label_out_of_range"
    finally:
        await queue.stop(timeout_s=2.0)


async def test_reprint_from_after_the_group_requeues_only_the_not_started() -> None:
    printer = TapeRoll(15)
    queue, run_id, _, _ = await _run(printer, 30)
    try:
        await _until(_stopped(queue, run_id))
        printer.k = None
        result = await queue.reprint_from(run_id, 21)  # all of 11..20 printed
        assert len(result.new_job_ids) == 10
        await _until(lambda: queue.run_info(run_id) is None)
    finally:
        await queue.stop(timeout_s=2.0)


async def test_reprint_is_refused_while_the_run_has_not_stopped() -> None:
    printer = TapeRoll()
    queue, run_id, _, _ = await _run(printer, 51)
    try:
        await _until(lambda: queue.run_info(run_id).state == "awaiting_confirmation")  # type: ignore[union-attr]
        with pytest.raises(RunStateError) as err:
            await queue.reprint_from(run_id, 1)
        assert err.value.code == "run_not_stopped"
    finally:
        await queue.stop(timeout_s=2.0)


async def test_a_reprint_of_more_than_fifty_labels_is_split_again() -> None:
    printer = TapeRoll(5)
    queue, run_id, ids, _ = await _run(printer, 80)
    try:
        await _until(_stopped(queue, run_id))
        printer.k = None
        result = await queue.reprint_from(run_id, 1)  # all 80 again
        assert len(result.new_job_ids) == 80
        await _until(lambda: queue.run_info(run_id).state == "awaiting_confirmation")  # type: ignore[union-attr]
        assert printer.calls[1:] == [10] * 5
        await queue.confirm_run(run_id)
        await _until(lambda: queue.run_info(run_id) is None)
        assert printer.calls[1:] == [10] * 8
        assert len(ids) == 80
    finally:
        await queue.stop(timeout_s=2.0)


# ---------------------------------------------------------------------------- concurrency


async def test_cancel_during_a_group_spares_the_group_and_skips_the_cancelled_label() -> None:
    printer = TapeRoll()
    printer.gate = asyncio.Event()
    queue, run_id, ids, _ = await _run(printer, 20)
    try:
        await printer.started.wait()  # group 1 is on the wire
        assert await queue.cancel(str(ids[3])) is False  # printing: never cancelled
        assert await queue.cancel(str(ids[15])) is True  # group 2 has not started
        printer.gate.set()
        await _until(lambda: queue.run_info(run_id) is None)
        assert printer.calls == [10, 9]
        assert (await queue.get(ids[3])).state == JobState.COMPLETED
        assert (await queue.get(ids[15])).state == JobState.CANCELLED
    finally:
        printer.gate.set()
        await queue.stop(timeout_s=2.0)


async def test_a_printer_removed_while_a_sub_job_waits_forgets_the_run() -> None:
    printer = TapeRoll()
    queue, run_id, ids, store = await _run(printer, 55)
    try:
        await _until(lambda: queue.run_info(run_id).state == "awaiting_confirmation")  # type: ignore[union-attr]
        await queue.remove_printer(printer.id, timeout_s=1.0)
        assert queue.run_info(run_id) is None
        with pytest.raises(KeyError):
            await queue.confirm_run(run_id)
        # the waiting labels stay queued in the store; the next add decides (see restart)
        row = await store.get(ids[50])
        assert row is not None and row.state == DbJobState.QUEUED.value
    finally:
        await queue.stop(timeout_s=2.0)


async def test_a_restart_fails_labels_that_waited_for_confirmation() -> None:
    printer = TapeRoll()
    queue, run_id, ids, store = await _run(printer, 55)
    await _until(lambda: queue.run_info(run_id).state == "awaiting_confirmation")  # type: ignore[union-attr]
    await queue.stop(timeout_s=2.0)

    fresh = PrintQueue([printer], store=store)
    await fresh.start()
    try:
        for jid in ids[50:]:
            row = await store.get(jid)
            assert row is not None and row.state == DbJobState.FAILED.value
            assert (row.error or "").startswith("tape_run_interrupted")
        await asyncio.sleep(0.2)
        assert printer.calls == [10] * 5  # nothing printed without the confirmation
    finally:
        await fresh.stop(timeout_s=2.0)


async def test_a_printer_without_a_status_check_still_prints_in_groups() -> None:
    class NoCheck(TapeRoll):
        check_status = None  # type: ignore[assignment]

    printer = NoCheck()
    queue, run_id, ids, _ = await _run(printer, 12)
    try:
        await _until(lambda: queue.run_info(run_id) is None)
        assert printer.calls == [10, 2]
        assert await _states(queue, ids) == [JobState.COMPLETED] * 12
    finally:
        await queue.stop(timeout_s=2.0)


# ---------------------------------------------------------------------------- the mock backend


@pytest.mark.parametrize(
    ("k", "done", "unknown"),
    [(15, 10, (10, 20)), (20, 10, (10, 20)), (45, 40, (40, 50))],
    ids=["inside a group", "at a group boundary", "in the last group of the sub-job"],
)
async def test_the_mock_backend_runs_out_of_tape_through_the_pt_adapter(
    k: int, done: int, unknown: tuple[int, int]
) -> None:
    """The real PT queue adapter over ``MockPrinterBackend(tape_runs_out_after=k)``."""
    from app.printer_backends.mock_backend import MockPrinterBackend
    from app.printer_models.pt import PTP750WDriver
    from app.services.tape_registry import TapeRegistry

    backend = MockPrinterBackend(loaded_tape_mm=12, tape_runs_out_after=k)
    printer = PTP750WDriver(backend=backend).make_queue_printer(TapeRegistry())
    queue = PrintQueue([printer])
    await queue.start()
    ids = [uuid4() for _ in range(60)]
    try:
        run_id = await queue.enqueue_batch(
            printer_id=printer.id,
            images=[_img() for _ in ids],
            job_ids=ids,
            tape_mm=12,
            options={"half_cut": True},
        )
        await _until(_stopped(queue, run_id))
        codes = await _codes(queue, ids)
        assert await _states(queue, ids[:done]) == [JobState.COMPLETED] * done
        assert codes[unknown[0] : unknown[1]] == ["outcome_unknown"] * (unknown[1] - unknown[0])
        assert codes[unknown[1] :] == ["not_started"] * (60 - unknown[1])
        assert len(backend.printed_images) == k
        info = queue.pause_info(printer.id)
        assert info is not None and info.reason_code == "tape_empty"
    finally:
        await queue.stop(timeout_s=2.0)


# ---------------------------------------------------------------------------- fix round 1


class Refuses(TapeRoll):
    """A printer whose preflight refuses call number ``on`` (1-based) before sending anything."""

    def __init__(self, on: int = 1) -> None:
        super().__init__()
        self.on = on

    async def print_images(
        self, images: list[Image.Image], *, tape_mm: int, **options: Any
    ) -> None:
        if len(self.calls) + 1 == self.on:
            self.calls.append(0)
            raise refused_before_sending(TapeMismatchError(expected_mm=12, loaded_mm=24))
        await super().print_images(images, tape_mm=tape_mm, **options)


@pytest.mark.parametrize("on", [1, 2])
async def test_a_refusal_before_sending_is_not_an_unknown_outcome(on: int) -> None:
    """I1: the preflight said no before a byte was sent: the labels did not print."""
    printer = Refuses(on)
    queue, run_id, ids, store = await _run(printer, 25)
    try:
        await _until(_stopped(queue, run_id))
        done = (on - 1) * 10
        codes = await _codes(queue, ids)
        assert "outcome_unknown" not in codes
        assert await _states(queue, ids[:done]) == [JobState.COMPLETED] * done
        assert codes[done : done + 10] == ["tape_mismatch"] * 10  # the real error code
        assert codes[done + 10 :] == ["not_started"] * (15 - done)
        row = await store.get(ids[done])
        assert row is not None and row.state == DbJobState.FAILED.value
        assert (row.error or "").startswith("tape_mismatch")
        info = queue.run_info(run_id)
        assert info is not None and info.stop_kind == "refused"
        assert (info.unknown_from, info.unknown_to) == (None, None)
        assert (info.reprint_from, info.reprint_to) == (done + 1, done + 1)
        assert queue.pause_info(printer.id).reason_code == "tape_mismatch"  # type: ignore[union-attr]

        with pytest.raises(RunStateError):
            await queue.reprint_from(run_id, done + 2)
        result = await queue.reprint_from(run_id, done + 1)
        assert len(result.new_job_ids) == 25 - done and result.confirmed_job_ids == []
        await _until(lambda: queue.run_info(run_id) is None)
        assert not queue.is_paused(printer.id)
    finally:
        await queue.stop(timeout_s=2.0)


async def test_the_mock_backend_flags_a_refusal_of_the_first_label_only() -> None:
    """A wrong tape refuses label 1: nothing sent. A refusal later in a group is unknown."""
    from app.printer_backends.mock_backend import MockPrinterBackend
    from app.printer_models.pt import PTP750WDriver
    from app.services.tape_registry import TapeRegistry

    backend = MockPrinterBackend(loaded_tape_mm=24)  # the batch asks for 12 mm
    printer = PTP750WDriver(backend=backend).make_queue_printer(TapeRegistry())
    queue = PrintQueue([printer])
    await queue.start()
    ids = [uuid4() for _ in range(12)]
    try:
        run_id = await queue.enqueue_batch(
            printer_id=printer.id, images=[_img() for _ in ids], job_ids=ids, tape_mm=12, options={}
        )
        await _until(_stopped(queue, run_id))
        codes = await _codes(queue, ids)
        assert codes == ["tape_mismatch"] * 10 + ["not_started"] * 2
    finally:
        await queue.stop(timeout_s=2.0)


class GatedStore(MemoryJobStore):
    """``save_queued`` waits for ``gate`` while it is set (the reviewer's probe)."""

    def __init__(self) -> None:
        super().__init__()
        self.gate: asyncio.Event | None = None
        self.entered = asyncio.Event()

    async def save_queued(self, job: DbJob) -> None:
        if self.gate is not None:
            self.entered.set()
            await self.gate.wait()
        await super().save_queued(job)


async def test_a_removal_during_a_reprint_leaves_no_row_queued_forever() -> None:
    """I2: the reprint holds the printer: the removal waits; after a re-add nothing hangs."""
    store = GatedStore()
    printer = TapeRoll(15)
    queue, run_id, _, _ = await _run(printer, 30, store=store)
    try:
        await _until(_stopped(queue, run_id))
        printer.k = None
        store.gate = asyncio.Event()
        reprint = asyncio.create_task(queue.reprint_from(run_id, 11))
        await store.entered.wait()
        removal = asyncio.create_task(queue.remove_printer(printer.id, timeout_s=1.0))
        await asyncio.sleep(0.05)
        assert not removal.done()  # it waits for the reprint
        store.gate.set()
        store.gate = None
        await reprint
        await removal
        await queue.add_printer(printer)

        def clones() -> list[DbJob]:
            return [
                r
                for r in store._jobs.values()
                if (r.payload or {}).get("tape_run", {}).get("reprint_of")
            ]

        terminal = {DbJobState.DONE.value, DbJobState.FAILED.value, DbJobState.CANCELLED.value}
        # Every clone has ended (not only left ``queued``: the last may still be printing).
        await _until(lambda: len(clones()) == 20 and all(r.state in terminal for r in clones()))
        assert len(clones()) == 20
        assert {r.state for r in clones()} <= {DbJobState.DONE.value, DbJobState.FAILED.value}
        assert [j for j in queue._jobs.values() if j.state == JobState.QUEUED] == []
    finally:
        await queue.stop(timeout_s=2.0)


async def test_a_store_failure_during_a_reprint_leaves_nothing_behind() -> None:
    class Breaks(MemoryJobStore):
        broken = False

        async def save_queued(self, job: DbJob) -> None:
            await super().save_queued(job)
            if (
                self.broken
                and len(
                    [
                        r
                        for r in self._jobs.values()
                        if r.payload.get("tape_run", {}).get("reprint_of")
                    ]
                )
                == 3
            ):
                raise RuntimeError("disk full")

    store = Breaks()
    printer = TapeRoll(15)
    queue, run_id, _, _ = await _run(printer, 30, store=store)
    try:
        await _until(_stopped(queue, run_id))
        store.broken = True
        with pytest.raises(RuntimeError, match="disk full"):
            await queue.reprint_from(run_id, 11)
        clones = [
            r for r in store._jobs.values() if r.payload.get("tape_run", {}).get("reprint_of")
        ]
        assert len(clones) == 3 and {r.state for r in clones} == {DbJobState.CANCELLED.value}
        assert all(str(r.id) not in queue._jobs for r in clones)
        assert queue.run_info(run_id).state == "stopped"  # type: ignore[union-attr]
    finally:
        await queue.stop(timeout_s=2.0)


async def test_double_reprint_and_double_confirm_each_act_once() -> None:
    """M4: the state is claimed before the first await: a second call is refused."""
    printer = TapeRoll(15)
    queue, run_id, _, _ = await _run(printer, 30)
    try:
        await _until(_stopped(queue, run_id))
        printer.k = None
        results = await asyncio.gather(
            queue.reprint_from(run_id, 11), queue.reprint_from(run_id, 11), return_exceptions=True
        )
        assert sorted(type(r).__name__ for r in results) == ["ReprintResult", "RunStateError"]
        await _until(lambda: queue.run_info(run_id) is None)
        assert printer.calls == [10, 10, 10, 10]  # every label once
    finally:
        await queue.stop(timeout_s=2.0)

    printer = TapeRoll()
    queue, run_id, _, _ = await _run(printer, 60)
    try:
        await _until(lambda: queue.run_info(run_id).state == "awaiting_confirmation")  # type: ignore[union-attr]
        results = await asyncio.gather(
            queue.confirm_run(run_id), queue.confirm_run(run_id), return_exceptions=True
        )
        assert sorted(type(r).__name__ for r in results) == ["RunInfo", "RunStateError"]
        await _until(lambda: queue.run_info(run_id) is None)
        await asyncio.sleep(0.1)
        assert printer.calls == [10] * 6
    finally:
        await queue.stop(timeout_s=2.0)


async def test_discard_cancels_the_waiting_part_and_frees_the_run() -> None:
    """I3: a run that waits can be given up; its waiting labels are cancelled."""
    printer = TapeRoll()
    queue, run_id, ids, store = await _run(printer, 55)
    try:
        await _until(lambda: queue.run_info(run_id).state == "awaiting_confirmation")  # type: ignore[union-attr]
        held = queue._runs[run_id]
        assert set(held.payloads) == {str(j) for j in ids[50:]}  # printed pictures are freed
        assert [(await queue.get(j)).image_payload for j in ids[:50]] == [None] * 50
        await queue.discard_run(run_id)
        assert queue.run_info(run_id) is None
        # N2: no PNG of the discarded run stays referenced, not on its jobs either.
        assert [(await queue.get(j)).image_payload for j in ids] == [None] * 55
        assert held.payloads == {}
        for jid in ids[50:]:
            job = await queue.get(jid)
            assert (job.state, job.error_code) == (JobState.CANCELLED, "run_discarded")
            row = await store.get(jid)
            assert row is not None and row.state == DbJobState.CANCELLED.value
        with pytest.raises(KeyError):
            await queue.confirm_run(run_id)
    finally:
        await queue.stop(timeout_s=2.0)


async def test_discard_frees_a_stopped_run_and_refuses_a_printing_one() -> None:
    printer = TapeRoll(15)
    queue, run_id, ids, _ = await _run(printer, 30)
    try:
        await _until(_stopped(queue, run_id))
        held = queue._runs[run_id]
        await queue.discard_run(run_id)
        assert queue.run_info(run_id) is None
        assert (await queue.get(ids[25])).error_code == "not_started"  # unchanged
        assert [(await queue.get(j)).image_payload for j in ids] == [None] * 30  # N2
        assert held.payloads == {}
    finally:
        await queue.stop(timeout_s=2.0)

    printer = TapeRoll()
    printer.gate = asyncio.Event()
    queue, run_id, _, _ = await _run(printer, 20)
    try:
        await printer.started.wait()
        with pytest.raises(RunStateError) as err:
            await queue.discard_run(run_id)
        assert err.value.code == "run_not_held"
    finally:
        printer.gate.set()
        await queue.stop(timeout_s=2.0)


async def test_at_most_five_runs_wait_per_printer_the_oldest_is_discarded() -> None:
    """I3: a sixth held run discards the oldest of its own key, with ``run_discarded_limit``.

    Three keys with two held runs each (a key keeps at most two on one printer): the sixth,
    of the third key, discards that key's first run.
    """
    printer = TapeRoll()
    store = MemoryJobStore()
    queue = PrintQueue([printer], store=store)
    await queue.start()
    keys = [k for k in (uuid4(), uuid4(), uuid4()) for _ in range(2)]
    try:
        runs: list[tuple[UUID, list[UUID]]] = []
        for key in keys:
            ids = [uuid4() for _ in range(51)]
            slot = queue.claim_run_slot(printer.id, key, per_printer=100, per_key=100)
            run_id = await queue.enqueue_batch(
                printer_id=printer.id,
                images=[_img() for _ in ids],
                job_ids=ids,
                tape_mm=12,
                options={},
                slot=slot,
            )
            runs.append((run_id, ids))
            await _until(
                lambda r=run_id: (
                    queue.run_info(r) is not None
                    and queue.run_info(r).state == "awaiting_confirmation"
                )
            )  # type: ignore[misc,union-attr]
        held = [info.run_id for info in queue.held_runs(printer.id)]
        assert held == [r for r, _ in [*runs[:4], runs[5]]]  # the third key's first run gone
        oldest_label = runs[4][1][50]
        assert (await queue.get(oldest_label)).error_code == "run_discarded_limit"
    finally:
        await queue.stop(timeout_s=2.0)


async def test_reprint_reports_every_confirmation_of_the_run_so_far() -> None:
    printer = TapeRoll(15)
    queue, run_id, ids, _ = await _run(printer, 25)
    try:
        await _until(_stopped(queue, run_id))
        printer.k = 22  # the new tape ends again inside the re-queued group
        first = await queue.reprint_from(run_id, 14)
        await _until(_stopped(queue, run_id))
        info = queue.run_info(run_id)
        assert info is not None and info.unknown_from is not None
        printer.k = None
        second = await queue.reprint_from(run_id, info.unknown_from + 2)
        assert first.all_confirmed_job_ids == first.confirmed_job_ids == ids[10:13]
        assert second.confirmed_job_ids and not set(second.confirmed_job_ids) & set(ids[10:13])
        assert second.all_confirmed_job_ids == [*first.confirmed_job_ids, *second.confirmed_job_ids]
    finally:
        await queue.stop(timeout_s=2.0)


async def test_a_run_that_starts_waiting_is_announced_after_its_state_is_set() -> None:
    printer = TapeRoll()
    seen: list[tuple[UUID, UUID, str, str | None]] = []
    holder: list[PrintQueue] = []

    def on_run_change(run_id: UUID, printer_id: UUID, state: str) -> None:
        info = holder[0].run_info(run_id)  # what a client refetching on the event would read
        seen.append((run_id, printer_id, state, None if info is None else info.state))

    queue, run_id, _, _ = await _run(printer, 51, on_run_change=on_run_change)
    holder.append(queue)
    try:
        await _until(lambda: queue.run_info(run_id).state == "awaiting_confirmation")  # type: ignore[union-attr]
        # the order matters: the state a reader sees when the event arrives is already the new one
        assert (run_id, printer.id, "awaiting_confirmation", "awaiting_confirmation") in seen
        await queue.confirm_run(run_id)
        assert (run_id, printer.id, "printing", "printing") in seen
    finally:
        await queue.stop(timeout_s=2.0)


async def test_a_stopped_run_is_announced_and_so_is_its_discard() -> None:
    printer = TapeRoll(15)
    seen: list[tuple[str, str | None]] = []
    holder: list[PrintQueue] = []

    def on_run_change(run_id: UUID, printer_id: UUID, state: str) -> None:
        info = holder[0].run_info(run_id)
        seen.append((state, None if info is None else info.state))

    queue, run_id, _, _ = await _run(printer, 25, on_run_change=on_run_change)
    holder.append(queue)
    try:
        await _until(_stopped(queue, run_id))
        assert ("stopped", "stopped") in seen
        await queue.discard_run(run_id)
        assert ("discarded", None) in seen  # the run is gone when the event arrives
    finally:
        await queue.stop(timeout_s=2.0)


async def test_a_failing_run_callback_does_not_break_the_run() -> None:
    printer = TapeRoll()

    def boom(run_id: UUID, printer_id: UUID, state: str) -> None:
        raise RuntimeError("callback bug")

    queue, run_id, _, _ = await _run(printer, 51, on_run_change=boom)
    try:
        await _until(lambda: queue.run_info(run_id).state == "awaiting_confirmation")  # type: ignore[union-attr]
        await queue.confirm_run(run_id)
        await _until(lambda: queue.run_info(run_id) is None)
    finally:
        await queue.stop(timeout_s=2.0)


async def test_cancel_during_reprint_registration_survives_restart() -> None:
    """263-75: a clone is registered in memory before its row is saved. A cancel in between
    finds no row to persist; the save then writes ``queued``. The reprint must persist the
    cancel, or a restart would print the label the user cancelled."""
    store = GatedStore()
    printer = TapeRoll(15)
    queue, run_id, ids, _ = await _run(printer, 30, store=store)
    restarted: PrintQueue | None = None
    try:
        await _until(_stopped(queue, run_id))
        printer.k = None
        store.gate = asyncio.Event()
        reprint = asyncio.create_task(queue.reprint_from(run_id, 11))
        await store.entered.wait()
        known = {str(j) for j in ids}
        (clone,) = [j for j in queue._jobs if j not in known]  # the first clone, being saved
        assert await queue.cancel(clone)
        store.gate.set()
        store.gate = None
        result = await reprint
        assert str(result.new_job_ids[0]) == clone

        row = await store.get(UUID(clone))
        assert row is not None and row.state == DbJobState.CANCELLED.value
        await _until(lambda: queue.run_info(run_id) is None)
        printed = printer.printed
        await queue.stop(timeout_s=2.0)

        restarted = PrintQueue([printer], store=store)
        await restarted.start()
        await asyncio.sleep(0.1)
        assert printer.printed == printed  # nothing was resurrected
        assert [r for r in store._jobs.values() if r.state == DbJobState.QUEUED.value] == []
    finally:
        await queue.stop(timeout_s=2.0)
        if restarted is not None:
            await restarted.stop(timeout_s=2.0)
