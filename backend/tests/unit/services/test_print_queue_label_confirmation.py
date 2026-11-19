# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""#393: a tape job is done only when the printer confirmed it.

A shortfall (``LabelsNotConfirmedError``) fails a single job with ``labels_not_confirmed``; in a
group, the labels the printer confirmed are done and the rest failed, so a reprint starts at the
first one that did not print. The printer is not paused for it.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from app.models.job import JobState as DbJobState
from app.printer_backends.exceptions import LabelsNotConfirmedError, PrinterOfflineError
from app.services.job_lifecycle import JobState
from app.services.job_store import MemoryJobStore
from app.services.print_queue import PrintQueue
from PIL import Image

from tests.unit.services.test_print_queue_tape_runs import _run, _states, _stopped, _until

pytestmark = pytest.mark.anyio


class _Confirming:
    """A tape printer whose check after sending raises the next error of *outcomes* (``None``:
    confirmed)."""

    def __init__(self, *outcomes: Exception | None) -> None:
        self.id = uuid4()
        self.outcomes = list(outcomes)
        self.calls: list[int] = []

    async def print_image(self, image: Image.Image, *, tape_mm: int, **options: Any) -> None:
        self.calls.append(1)

    async def print_images(
        self, images: list[Image.Image], *, tape_mm: int, **options: Any
    ) -> None:
        self.calls.append(len(images))

    def _next(self) -> None:
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if outcome is not None:
            raise outcome

    async def check_after_send(self) -> None:
        self._next()

    async def check_status(self) -> None:
        self._next()


async def _single(printer: _Confirming) -> tuple[PrintQueue, Any]:
    queue = PrintQueue([printer])
    await queue.start()
    job_id = await queue.submit(printer.id, Image.new("1", (306, 120)), tape_mm=29)
    await queue.wait_for_job(job_id, timeout_s=5)
    return queue, await queue.get(job_id)


async def test_a_single_job_the_printer_did_not_confirm_fails() -> None:
    printer = _Confirming(LabelsNotConfirmedError(printed=0, expected=1))
    queue, job = await _single(printer)
    try:
        assert job.state == JobState.FAILED
        assert job.error_code == "labels_not_confirmed"
        assert job.error_message == "0 of 1 labels printed"
        assert job.error_detail == {"printed": 0, "expected": 1}
        assert not queue.is_paused(printer.id)
    finally:
        await queue.stop()


async def test_a_retry_of_an_unconfirmed_job_prints_it_again() -> None:
    printer = _Confirming(LabelsNotConfirmedError(printed=0, expected=1))
    queue, job = await _single(printer)
    try:
        new_id = await queue.retry_job(job.id)
        assert new_id is not None
        await queue.wait_for_job(new_id, timeout_s=5)
        assert (await queue.get(new_id)).state == JobState.COMPLETED
        assert printer.calls == [1, 1]
    finally:
        await queue.stop()


async def test_a_status_that_cannot_be_read_still_counts_as_printed() -> None:
    # Network error path: unchanged from #389.
    printer = _Confirming(PrinterOfflineError("timeout"))
    queue, job = await _single(printer)
    try:
        assert job.state == JobState.COMPLETED
    finally:
        await queue.stop()


async def test_a_group_of_five_with_three_confirmed_completes_three_and_fails_two() -> None:
    printer = _Confirming(LabelsNotConfirmedError(printed=3, expected=5))
    store = MemoryJobStore()
    queue, run_id, ids, store = await _run(printer, 5, store=store)  # type: ignore[arg-type]
    try:
        await _until(_stopped(queue, run_id))
        assert await _states(queue, ids) == [JobState.COMPLETED] * 3 + [JobState.FAILED] * 2
        codes = [(await queue.get(j)).error_code for j in ids[3:]]
        assert codes == ["labels_not_confirmed"] * 2
        rows = [await store.get(j) for j in ids]
        assert [r.state for r in rows] == [DbJobState.DONE.value] * 3 + [  # type: ignore[union-attr]
            DbJobState.FAILED.value
        ] * 2
        assert not queue.is_paused(printer.id)
        info = queue.run_info(run_id)
        assert info is not None
        assert info.stop_code == "labels_not_confirmed"
        assert (info.reprint_from, info.reprint_to) == (4, 4)
    finally:
        await queue.stop(timeout_s=2.0)


async def test_a_reprint_after_a_shortfall_prints_only_the_unconfirmed_labels() -> None:
    printer = _Confirming(LabelsNotConfirmedError(printed=3, expected=5))
    queue, run_id, _ids, _ = await _run(printer, 5)  # type: ignore[arg-type]
    try:
        await _until(_stopped(queue, run_id))
        result = await queue.reprint_from(run_id, 4)
        assert len(result.new_job_ids) == 2
        await _until(lambda: queue.run_info(run_id) is None)
        assert printer.calls == [5, 2]
        assert await _states(queue, list(result.new_job_ids)) == [JobState.COMPLETED] * 2
    finally:
        await queue.stop(timeout_s=2.0)


async def test_a_group_with_no_label_confirmed_fails_every_label() -> None:
    printer = _Confirming(LabelsNotConfirmedError(printed=0, expected=4))
    queue, run_id, ids, _ = await _run(printer, 4)  # type: ignore[arg-type]
    try:
        await _until(_stopped(queue, run_id))
        assert await _states(queue, ids) == [JobState.FAILED] * 4
    finally:
        await queue.stop(timeout_s=2.0)
