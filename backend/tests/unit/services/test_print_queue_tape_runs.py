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
from collections.abc import Callable
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
    MAX_HELD_RUNS_PER_PRINTER,
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
    printer: TapeRoll, n: int, store: MemoryJobStore | None = None, **options: Any
) -> tuple[PrintQueue, UUID, list[UUID], MemoryJobStore]:
    store = store or MemoryJobStore()
    queue = PrintQueue([printer], store=store)
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

        await _until(lambda: all(r.state != DbJobState.QUEUED.value for r in clones()))
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
        await queue.discard_run(run_id)
        assert queue.run_info(run_id) is None
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
        await queue.discard_run(run_id)
        assert queue.run_info(run_id) is None
        assert (await queue.get(ids[25])).error_code == "not_started"  # unchanged
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
    """I3: a sixth held run discards the oldest, with ``run_discarded_limit``."""
    printer = TapeRoll()
    store = MemoryJobStore()
    queue = PrintQueue([printer], store=store)
    await queue.start()
    try:
        runs: list[tuple[UUID, list[UUID]]] = []
        for _ in range(MAX_HELD_RUNS_PER_PRINTER + 1):
            ids = [uuid4() for _ in range(51)]
            run_id = await queue.enqueue_batch(
                printer_id=printer.id,
                images=[_img() for _ in ids],
                job_ids=ids,
                tape_mm=12,
                options={},
            )
            runs.append((run_id, ids))
            await _until(
                lambda r=run_id: (
                    queue.run_info(r) is not None
                    and queue.run_info(r).state == "awaiting_confirmation"
                )
            )  # type: ignore[misc,union-attr]
        held = [info.run_id for info in queue.held_runs(printer.id)]
        assert held == [r for r, _ in runs[1:]]  # oldest first, the first one gone
        oldest_label = runs[0][1][50]
        assert (await queue.get(oldest_label)).error_code == "run_discarded_limit"
    finally:
        await queue.stop(timeout_s=2.0)
