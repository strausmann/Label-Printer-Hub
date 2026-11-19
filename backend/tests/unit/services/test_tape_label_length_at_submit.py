# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Audit run 27: a tape label longer than the tape allows is refused when it is submitted
(422 ``tape_label_too_long`` on the printing routes), not only when the worker sends it; a batch
is refused as a whole, and one that still fails in the worker does not pause the printer."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from app.printer_backends.exceptions import TapeLabelTooLongError, refused_before_sending
from app.printer_backends.ptouch_backend import PTouchBackend
from app.printer_backends.snmp_helper import PreflightStatus
from app.printer_models.pt import PTP750WDriver
from app.schemas.content_type import ContentType
from app.schemas.print_request import PrintRequest, RawLabelData
from app.services.job_lifecycle import JobState
from app.services.layout_engine import LayoutEngine
from app.services.print_queue import PrintQueue
from app.services.print_service import PrintService
from app.services.tape_registry import TapeRegistry
from PIL import Image

from tests.unit.services.test_print_queue_tape_runs import TapeRoll, _run, _until

pytestmark = pytest.mark.anyio

_PRINTER = UUID("bbbbbbbb-0000-4000-8000-000000000027")
_TOO_LONG = TapeLabelTooLongError(length_mm=1601, max_mm=1000)


def _service(check: Any) -> tuple[PrintService, MagicMock, MagicMock]:
    backend = AsyncMock()
    backend.preflight_check = AsyncMock(
        return_value=PreflightStatus(
            hr_printer_status="idle", loaded_tape_mm=12, error_flags=[], media_raw="12mm"
        )
    )
    queue = MagicMock()
    queue.submit_with_id = AsyncMock()
    queue.enqueue_batch = AsyncMock()
    queue.check_label_lengths = check
    store = MagicMock()
    store.save_queued = AsyncMock()
    svc = PrintService(
        printer_id=_PRINTER, backend=backend, queue=queue, store=store, engine=LayoutEngine()
    )
    return svc, queue, store


def _request() -> PrintRequest:
    return PrintRequest(
        content_type=ContentType.TEXT_ONE_LINE,
        data=RawLabelData(title="Box", primary_id="A1"),
    )


async def test_a_single_label_too_long_is_refused_before_it_is_stored() -> None:
    svc, queue, store = _service(MagicMock(side_effect=_TOO_LONG))
    with pytest.raises(TapeLabelTooLongError):
        await svc.submit_print_job(_request())
    store.save_queued.assert_not_called()
    queue.submit_with_id.assert_not_called()
    ((args, kwargs),) = queue.check_label_lengths.call_args_list
    assert args[0] == _PRINTER and len(args[1]) == 1 and kwargs["tape_mm"] == 12


async def test_a_batch_with_one_label_too_long_is_refused_as_a_whole() -> None:
    svc, queue, store = _service(MagicMock(side_effect=_TOO_LONG))
    with pytest.raises(TapeLabelTooLongError):
        await svc.submit_batch_job([_request(), _request(), _request()], half_cut=True)
    store.save_queued.assert_not_called()
    queue.enqueue_batch.assert_not_called()
    ((args, _kwargs),) = queue.check_label_lengths.call_args_list
    assert len(args[1]) == 3  # every label of the batch, checked in one go


async def test_a_label_that_fits_goes_on_to_the_queue() -> None:
    svc, queue, _store = _service(MagicMock(return_value=None))
    await svc.submit_print_job(_request())
    queue.submit_with_id.assert_awaited_once()


def test_the_queue_measures_with_the_printer_s_own_backend() -> None:
    backend = PTouchBackend(host="192.0.2.91")
    printer = PTP750WDriver(backend=backend).make_queue_printer(TapeRegistry(), printer_id=uuid4())
    queue = PrintQueue([printer])
    max_mm = TapeRegistry.lookup_pt(12, printer._default_media_type).max_length_mm  # type: ignore[attr-defined]
    fits = Image.new("1", (round((max_mm - 10) / 25.4 * 180), 76), 1)
    too_long = Image.new("1", (round((max_mm + 10) / 25.4 * 180), 76), 1)
    queue.check_label_lengths(printer.id, [fits], tape_mm=12)
    with pytest.raises(TapeLabelTooLongError) as err:
        queue.check_label_lengths(printer.id, [fits, too_long], tape_mm=12)
    assert err.value.max_mm == max_mm
    queue.check_label_lengths(uuid4(), [too_long], tape_mm=12)  # an unknown printer: no check


class _TooLongRoll(TapeRoll):
    async def print_images(
        self, images: list[Image.Image], *, tape_mm: int, **options: Any
    ) -> None:
        raise refused_before_sending(TapeLabelTooLongError(length_mm=1601, max_mm=1000))


async def test_a_batch_refused_in_the_worker_for_its_length_does_not_pause_the_printer() -> None:
    printer = _TooLongRoll()
    queue, _run_id, ids, _ = await _run(printer, 3)
    try:
        await _until(lambda: all(queue._jobs[str(j)].state == JobState.FAILED for j in ids))
        assert {queue._jobs[str(j)].error_code for j in ids} == {"tape_label_too_long"}
        assert not queue.is_paused(printer.id)
    finally:
        await queue.stop(timeout_s=2.0)


async def test_a_deferred_label_too_long_fails_its_job_before_it_is_queued() -> None:
    """Review round 4, M1: the Grocy label webhook answers before the label is drawn, so it
    cannot answer 422; its completion checks the length and fails the job with the code, a
    fixed sentence and the lengths, and nothing is queued."""
    import asyncio

    svc, queue, store = _service(MagicMock(side_effect=_TOO_LONG))
    store.set_queued_payload = AsyncMock(return_value=True)
    store.mark_failed_code = AsyncMock(return_value=True)
    await svc.accept_deferred_job(
        RawLabelData(title="Box", primary_id="A1", qr_payload="https://e.invalid"),
        content_type=ContentType.QR_TWO_LINES,
        source_app="grocy",
        api_key_id=None,
        source_ip=None,
    )
    await asyncio.gather(*list(svc._deferred))
    queue.submit_with_id.assert_not_called()
    store.set_queued_payload.assert_not_called()
    (_job, code, message, detail), _ = store.mark_failed_code.call_args
    assert code == "tape_label_too_long"
    assert message == "The label is longer than the loaded tape allows."
    assert detail == {"length_mm": 1601, "max_mm": 1000}
