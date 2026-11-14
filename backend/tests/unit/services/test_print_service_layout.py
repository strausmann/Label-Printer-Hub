# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""PrintService resolves orientation and preset per job and from the stored default (#258)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from app.printer_backends.exceptions import ConflictingOrientationError, UnsupportedTapeError
from app.printer_backends.snmp_helper import PreflightStatus
from app.schemas.content_type import ContentType
from app.schemas.label_layout import LabelOrientation, LayoutDefault, QlLayoutPreset
from app.schemas.print_request import PrintOptions, PrintRequest, RawLabelData
from app.services.layout_engine import LayoutEngine
from app.services.print_queue import PrintQueue
from app.services.print_service import PrintService

_PRINTER_ID = UUID("bbbbbbbb-0000-0000-0000-000000000258")

_DATA = RawLabelData(
    primary_id="ST00019",
    title="DOCKER1",
    secondary=("Dell OptiPlex 3070 Micro", "S/N 72104Z2"),
    qr_payload="https://example.invalid/hardware/19",
)


def _service(
    tape_mm: int, defaults: dict[int, LayoutDefault] | None = None
) -> tuple[PrintService, MagicMock, MagicMock]:
    backend = AsyncMock()
    backend.preflight_check = AsyncMock(
        return_value=PreflightStatus(
            hr_printer_status="idle", loaded_tape_mm=tape_mm, error_flags=[]
        )
    )
    queue = MagicMock()
    queue.submit_with_id = AsyncMock()
    queue.enqueue_batch = AsyncMock()
    store = MagicMock()
    store.save_queued = AsyncMock()
    svc = PrintService(
        printer_id=_PRINTER_ID,
        backend=backend,
        queue=queue,
        store=store,
        engine=LayoutEngine(),
        layout_defaults=defaults,
    )
    return svc, queue, store


def _request(**options: object) -> PrintRequest:
    return PrintRequest(
        content_type=ContentType.QR_THREE_LINES,
        data=_DATA,
        options=PrintOptions(**options),  # type: ignore[arg-type]
    )


async def test_62mm_job_is_across_compact_and_the_flag_reaches_the_queue() -> None:
    svc, queue, store = _service(62)
    await svc.submit_print_job(_request())
    args = queue.submit_with_id.await_args
    image = args.args[2]
    assert image.size == (696, 198)  # compact reference size
    assert args.kwargs["orientation"] == "across"
    stored = store.save_queued.await_args.args[0].payload["options"]
    assert (stored["orientation"], stored["layout_preset"]) == ("across", "compact")


async def test_stored_default_applies_when_the_request_has_none() -> None:
    svc, queue, _ = _service(
        62, {62: LayoutDefault(orientation=LabelOrientation.ACROSS, preset=QlLayoutPreset.STANDARD)}
    )
    await svc.submit_print_job(_request())
    assert queue.submit_with_id.await_args.args[2].size == (696, 307)  # standard reference


async def test_stored_along_default_renders_a_landscape_band() -> None:
    svc, queue, _ = _service(62, {62: LayoutDefault(orientation=LabelOrientation.ALONG)})
    await svc.submit_print_job(_request())
    args = queue.submit_with_id.await_args
    assert args.args[2].height == 696
    assert args.kwargs["orientation"] == "along"


async def test_request_overrides_the_stored_default() -> None:
    svc, queue, _ = _service(62, {62: LayoutDefault(orientation=LabelOrientation.ALONG)})
    await svc.submit_print_job(
        _request(orientation=LabelOrientation.ACROSS, layout_preset=QlLayoutPreset.SMALL_QR)
    )
    args = queue.submit_with_id.await_args
    assert args.args[2].size == (696, 234)  # small QR reference size
    assert args.kwargs["orientation"] == "across"


async def test_updated_defaults_apply_to_the_next_job() -> None:
    svc, queue, _ = _service(62)
    svc.set_layout_defaults({62: LayoutDefault(preset=QlLayoutPreset.STANDARD)})
    await svc.submit_print_job(_request())
    assert queue.submit_with_id.await_args.args[2].size == (696, 307)


async def test_other_widths_print_along_and_refuse_across() -> None:
    svc, queue, store = _service(12)
    await svc.submit_print_job(_request())
    assert queue.submit_with_id.await_args.kwargs["orientation"] == "along"

    svc, queue, store = _service(12)
    with pytest.raises(UnsupportedTapeError):
        await svc.submit_print_job(_request(orientation=LabelOrientation.ACROSS))
    queue.submit_with_id.assert_not_awaited()
    store.save_queued.assert_not_awaited()


async def test_batch_items_without_orientation_follow_the_named_one() -> None:
    svc, queue, _ = _service(62)
    await svc.submit_batch_job(
        [_request(), _request(orientation=LabelOrientation.ALONG)], half_cut=False
    )
    kwargs = queue.enqueue_batch.await_args.kwargs
    assert kwargs["options"]["orientation"] == "along"
    assert [im.height for im in kwargs["images"]] == [696, 696]


async def test_batch_with_conflicting_explicit_orientations_is_refused() -> None:
    """Review M3: an item asking for along was silently printed across."""
    svc, queue, store = _service(62)
    with pytest.raises(ConflictingOrientationError) as excinfo:
        await svc.submit_batch_job(
            [
                _request(orientation=LabelOrientation.ACROSS),
                _request(orientation=LabelOrientation.ALONG),
            ],
            half_cut=False,
        )
    assert excinfo.value.orientations == ("across", "along")
    queue.enqueue_batch.assert_not_awaited()
    store.save_queued.assert_not_awaited()


async def test_recovery_rerenders_with_the_stored_orientation_and_preset() -> None:
    printer = MagicMock(id=uuid4())
    queue = PrintQueue(
        printers=[printer], engine=LayoutEngine(), store=MagicMock(), on_state_change=AsyncMock()
    )
    payload = {
        "label_data": {"source_app": "manual", **_DATA.model_dump(mode="json")},
        "content_type": "qr_three_lines",
        "rendered_tape_mm": 62,
        "tape_mm": 62,
        "options": {"orientation": "across", "layout_preset": "standard"},
    }
    assert queue._rerender_from_db_payload(payload).size == (696, 307)
    payload["options"] = {"orientation": "along"}
    assert queue._rerender_from_db_payload(payload).height == 696
