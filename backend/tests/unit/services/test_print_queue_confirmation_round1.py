# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""#393 review round 1, the queue.

- I1: an aborted IPP job with an unreadable status fails ``labels_not_confirmed`` (single, group).
- I2: a confirmation that may still print ends ``outcome_unknown``.
- I4: a blocking bit with a known printed count splits the group: the printed labels are done,
  the rest fail with the bit's code, the printer pauses, a reprint starts at the first missing one.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.printer_backends.brother_ql_backend import BrotherQLBackend
from app.printer_backends.exceptions import (
    ConfirmationUnknownError,
    SnmpQueryError,
    TapeEmptyError,
)
from app.printer_backends.snmp_helper import PreflightStatus
from app.printer_models.ql import QL820NWBDriver
from app.services.job_lifecycle import JobState
from app.services.print_queue import PrintQueue
from app.services.tape_registry import TapeRegistry
from PIL import Image

from tests.helpers.fake_ipp_printer import FakeIppPrinter
from tests.unit.services.test_print_queue_tape_runs import _run, _states, _stopped, _until

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("real_ql_media_check")]


@pytest.fixture
def real_ql_media_check() -> None:
    """The QL media check runs for real here (no ``printer_backends`` conftest in this folder)."""


def _ql_printer(monkeypatch: pytest.MonkeyPatch, fake: FakeIppPrinter, tape_mm: int) -> Any:
    reads = {"n": 0}

    async def preflight(host: str, **_: Any) -> PreflightStatus:
        reads["n"] += 1
        if reads["n"] > 1:  # the read before sending answers, every read after it fails
            raise SnmpQueryError("timeout")
        return PreflightStatus(
            hr_printer_status="idle",
            loaded_tape_mm=tape_mm,
            error_flags=[],
            media_raw=f"{tape_mm}mm",
            marker_count=100,
        )

    monkeypatch.setattr("app.printer_backends.brother_ql_backend.query_preflight", preflight)
    monkeypatch.setattr("app.printer_backends.brother_ql_backend._helpers_send", lambda *a, **k: {})
    backend = BrotherQLBackend(
        host="192.0.2.50",
        ipp_transport=httpx.ASGITransport(app=fake),  # type: ignore[arg-type]
    )
    printer = QL820NWBDriver(backend=backend).make_queue_printer(TapeRegistry(), printer_id=uuid4())
    printer.post_send_settle_s = 0
    return printer


async def test_an_aborted_ipp_job_with_an_unreadable_status_fails_a_single_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeIppPrinter(formats=["application/octet-stream"], job_script=[8])
    printer = _ql_printer(monkeypatch, fake, 29)
    queue = PrintQueue([printer])
    await queue.start()
    try:
        job_id = await queue.submit(printer.id, Image.new("1", (306, 120)), tape_mm=29)
        await queue.wait_for_job(job_id, timeout_s=5)
        job = await queue.get(job_id)
        assert job.state == JobState.FAILED
        assert job.error_code == "labels_not_confirmed"
    finally:
        await queue.stop()


async def test_an_aborted_ipp_job_with_an_unreadable_status_splits_a_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeIppPrinter(
        formats=["application/octet-stream"], job_script=[8], impressions_script=[1]
    )
    printer = _ql_printer(monkeypatch, fake, 12)
    queue, run_id, ids, _ = await _run(printer, 3)
    try:
        await _until(_stopped(queue, run_id))
        assert await _states(queue, ids) == [JobState.COMPLETED] + [JobState.FAILED] * 2
        assert [(await queue.get(j)).error_code for j in ids[1:]] == ["labels_not_confirmed"] * 2
    finally:
        await queue.stop(timeout_s=2.0)


class _Checked:
    """A tape printer whose check after sending raises *error*."""

    def __init__(self, error: Exception) -> None:
        self.id = uuid4()
        self.error = error
        self.calls: list[int] = []

    async def print_image(self, image: Image.Image, *, tape_mm: int, **options: Any) -> None:
        self.calls.append(1)

    async def print_images(
        self, images: list[Image.Image], *, tape_mm: int, **options: Any
    ) -> None:
        self.calls.append(len(images))

    async def check_after_send(self) -> None:
        if self.error is not None:
            error, self.error = self.error, None  # type: ignore[assignment]
            raise error

    async def check_status(self) -> None:
        await self.check_after_send()


def _with_printed(error: Exception, printed: int) -> Exception:
    error.printed = printed  # type: ignore[attr-defined]
    return error


async def test_a_tape_end_with_a_known_count_splits_the_group_and_pauses() -> None:
    printer = _Checked(_with_printed(TapeEmptyError(), 3))
    queue, run_id, ids, _store = await _run(printer, 5)  # type: ignore[arg-type]
    try:
        await _until(_stopped(queue, run_id))
        assert await _states(queue, ids) == [JobState.COMPLETED] * 3 + [JobState.FAILED] * 2
        assert [(await queue.get(j)).error_code for j in ids[3:]] == ["tape_empty"] * 2
        assert queue.is_paused(printer.id)
        info = queue.run_info(run_id)
        assert info is not None and (info.reprint_from, info.reprint_to) == (4, 4)
        result = await queue.reprint_from(run_id, 4)
        assert len(result.new_job_ids) == 2
    finally:
        await queue.stop(timeout_s=2.0)


async def test_a_confirmation_that_may_still_print_is_outcome_unknown() -> None:
    printer = _Checked(ConfirmationUnknownError())
    queue = PrintQueue([printer])  # type: ignore[list-item]
    await queue.start()
    try:
        job_id = await queue.submit(printer.id, Image.new("1", (306, 120)), tape_mm=29)
        await queue.wait_for_job(job_id, timeout_s=5)
        job = await queue.get(job_id)
        assert job.state == JobState.FAILED
        assert job.error_code == "outcome_unknown"
        assert "may still print" in (job.error_message or "")
    finally:
        await queue.stop()
