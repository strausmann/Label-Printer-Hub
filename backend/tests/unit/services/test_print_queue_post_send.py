# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""#389: after a tape job was sent, the queue asks the printer's status once.

An error state the printer reports fails the job (with its code, retryable, the printer paused);
a status that cannot be read after sending leaves the job printed (the label was sent).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from app.printer_backends.exceptions import (
    PrinterOfflineError,
    PrinterReportedError,
    TapeMismatchError,
)
from app.services.job_lifecycle import JobState
from app.services.print_queue import PrintQueue
from PIL import Image

_PRINTER = UUID("aaaaaaaa-0000-0000-0000-000000000389")


class _Printer:
    """A queue printer with a post-send check whose outcome the test chooses."""

    def __init__(self, after_send: Exception | None = None) -> None:
        self.id = _PRINTER
        self.after_send = after_send
        self.printed = 0
        self.checked = 0

    async def print_image(self, image: Image.Image, *, tape_mm: int, **options: Any) -> None:
        self.printed += 1

    async def print_images(
        self, images: list[Image.Image], *, tape_mm: int, **options: Any
    ) -> None:
        self.printed += len(images)

    async def check_after_send(self) -> None:
        self.checked += 1
        if self.after_send is not None:
            raise self.after_send


async def _run(printer: _Printer) -> tuple[PrintQueue, Any]:
    queue = PrintQueue([printer])
    await queue.start()
    job_id = await queue.submit(_PRINTER, Image.new("1", (306, 120)), tape_mm=29)
    await queue.wait_for_job(job_id, timeout_s=5)
    return queue, await queue.get(job_id)


@pytest.mark.asyncio
async def test_an_error_the_printer_reports_after_sending_fails_the_job() -> None:
    printer = _Printer(PrinterReportedError(["jammed"]))
    queue, job = await _run(printer)
    try:
        assert printer.printed == 1
        assert printer.checked == 1
        assert job.state == JobState.FAILED
        assert job.error_code == "printer_error"
        assert job.error_detail == {"flags": ["jammed"]}
        # Recoverable: the printer waits until someone fixed it, the job can be retried.
        assert queue.is_paused(_PRINTER)
        assert await queue.retry_job(job.id) is not None
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_a_wrong_roll_reported_after_sending_fails_the_job() -> None:
    printer = _Printer(TapeMismatchError(expected_mm=29, loaded_mm=62))
    queue, job = await _run(printer)
    try:
        assert job.state == JobState.FAILED
        assert job.error_code == "tape_mismatch"
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_a_clean_status_after_sending_completes_the_job() -> None:
    printer = _Printer()
    queue, job = await _run(printer)
    try:
        assert printer.checked == 1
        assert job.state == JobState.COMPLETED
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_an_unreadable_status_after_sending_does_not_fail_a_sent_label(
    caplog: pytest.LogCaptureFixture,
) -> None:
    printer = _Printer(PrinterOfflineError("timeout"))
    with caplog.at_level("WARNING", logger="app.services.print_queue"):
        queue, job = await _run(printer)
    try:
        assert job.state == JobState.COMPLETED
        assert any("could not be read" in r.message for r in caplog.records)
        assert not queue.is_paused(_PRINTER)
    finally:
        await queue.stop()
