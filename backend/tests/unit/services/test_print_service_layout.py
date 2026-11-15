# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""PrintService resolves orientation and preset per job and from the stored default (#258)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from app.printer_backends.exceptions import (
    ConflictingOrientationError,
    SpoolLabelOnlyTapeError,
    UnsupportedTapeError,
)
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


# ---------------------------------------------------------------------------
# #346: the swatch label ignores every orientation; a batch turns it for the backend
# ---------------------------------------------------------------------------


class _QueuePrinter:
    """Queue printer over ``MockPrinterBackend``, forwarding ``orientation`` as the QL model."""

    def __init__(self, backend: object) -> None:
        self.id = _PRINTER_ID
        self.backend = backend

    async def print_image(self, image: object, *, tape_mm: int, **options: object) -> None:
        from types import SimpleNamespace

        raw = options.get("orientation")
        await self.backend.print_image(  # type: ignore[attr-defined]
            image,
            SimpleNamespace(width_mm=tape_mm),
            orientation=LabelOrientation(str(raw)) if raw else None,
        )

    async def print_images(self, images: list[object], *, tape_mm: int, **options: object) -> None:
        for image in images:
            await self.print_image(image, tape_mm=tape_mm, **options)


async def _live(
    defaults: dict[int, LayoutDefault] | None = None, tape_mm: int = 62
) -> tuple[PrintService, object, object, PrintQueue]:
    from app.printer_backends.mock_backend import MockPrinterBackend
    from app.services.job_store import MemoryJobStore

    backend = MockPrinterBackend(loaded_tape_mm=tape_mm)
    store = MemoryJobStore()
    queue = PrintQueue([_QueuePrinter(backend)], store=store, engine=LayoutEngine())  # type: ignore[list-item]
    await queue.start()
    svc = PrintService(
        printer_id=_PRINTER_ID,
        backend=backend,
        queue=queue,
        store=store,
        engine=LayoutEngine(),
        layout_defaults=defaults,
    )
    return svc, backend, store, queue


async def _printed(backend: object, count: int) -> None:
    import asyncio

    for _ in range(500):
        if len(backend.printed_images) >= count:  # type: ignore[attr-defined]
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the queue did not print")


def _swatch_request(**options: object) -> PrintRequest:
    from tests.helpers.spool_swatch import SAMPLE_URL, every_row

    return PrintRequest(
        content_type=ContentType.SPOOL_SWATCH,
        data=RawLabelData(qr_payload=SAMPLE_URL, swatch=every_row()),
        options=PrintOptions(**options),  # type: ignore[arg-type]
    )


def _across() -> object:
    from app.services.spool_swatch import render_tape_swatch

    from tests.helpers.spool_swatch import SAMPLE_URL, every_row

    return render_tape_swatch(every_row(), SAMPLE_URL)


async def test_single_swatch_job_is_across() -> None:
    from PIL import Image

    svc, backend, store, queue = await _live(
        {62: LayoutDefault(orientation=LabelOrientation.ALONG)}
    )
    try:
        job_id = await svc.submit_print_job(_swatch_request(orientation=LabelOrientation.ALONG))
        await _printed(backend, 1)
        row = await store.get(job_id)  # type: ignore[attr-defined]
        assert row.payload["options"]["orientation"] == "across"
        assert backend.printed_orientations[-1] is LabelOrientation.ACROSS  # type: ignore[attr-defined]
        printed: Image.Image = backend.printed_images[-1]  # type: ignore[attr-defined]
        assert printed.tobytes() == _across().tobytes()  # type: ignore[attr-defined]
    finally:
        await queue.stop()


async def test_mixed_batch_with_along_prints_the_swatch_across() -> None:
    from PIL import Image

    svc, backend, _, queue = await _live()
    try:
        await svc.submit_batch_job(
            [_request(orientation=LabelOrientation.ALONG), _swatch_request()], half_cut=False
        )
        await _printed(backend, 2)
        assert backend.printed_orientations == [LabelOrientation.ALONG, LabelOrientation.ALONG]  # type: ignore[attr-defined]
        swatch: Image.Image = backend.printed_images[1]  # type: ignore[attr-defined]
        across = _across()
        assert swatch.tobytes() == across.transpose(Image.Transpose.ROTATE_90).tobytes()  # type: ignore[attr-defined]
        # What the QL backend does for ``along`` restores the across image.
        assert swatch.transpose(Image.Transpose.ROTATE_270).tobytes() == across.tobytes()  # type: ignore[attr-defined]
    finally:
        await queue.stop()


async def test_all_swatch_batch_is_across() -> None:
    svc, backend, store, queue = await _live(
        {62: LayoutDefault(orientation=LabelOrientation.ALONG)}
    )
    try:
        ids = await svc.submit_batch_job([_swatch_request(), _swatch_request()], half_cut=False)
        await _printed(backend, 2)
        assert backend.printed_orientations == [LabelOrientation.ACROSS] * 2  # type: ignore[attr-defined]
        assert backend.printed_images[0].tobytes() == _across().tobytes()  # type: ignore[attr-defined]
        row = await store.get(ids[0])  # type: ignore[attr-defined]
        assert row.payload["options"]["orientation"] == "across"
    finally:
        await queue.stop()


# Other DK widths (maintainer ruling 2026-11-15): 38 and 50 mm print along, 29 and 54 across.


def _native(tape_mm: int) -> object:
    from app.services.spool_swatch import render_tape_swatch

    from tests.helpers.spool_swatch import SAMPLE_URL, every_row

    return render_tape_swatch(every_row(), SAMPLE_URL, tape_mm)


async def test_single_swatch_job_on_38mm_is_along() -> None:
    svc, backend, store, queue = await _live(tape_mm=38)
    try:
        job_id = await svc.submit_print_job(_swatch_request(orientation=LabelOrientation.ACROSS))
        await _printed(backend, 1)
        row = await store.get(job_id)  # type: ignore[attr-defined]
        assert row.payload["options"]["orientation"] == "along"
        assert backend.printed_orientations[-1] is LabelOrientation.ALONG  # type: ignore[attr-defined]
        assert backend.printed_images[-1].tobytes() == _native(38).tobytes()  # type: ignore[attr-defined]
    finally:
        await queue.stop()


async def test_all_swatch_batch_on_38mm_is_not_refused() -> None:
    svc, backend, _, queue = await _live(tape_mm=38)
    try:
        await svc.submit_batch_job([_swatch_request()], half_cut=False)
        await _printed(backend, 1)
    finally:
        await queue.stop()


async def test_mixed_batch_on_38mm_is_refused_for_the_other_label() -> None:
    """Only the spool label has the other DK widths so far (#258): a mixed batch there fails on
    the other item, as before; the turning of a swatch in a mixed batch is covered on 62 mm and
    by ``swatch_for_batch`` for every width."""
    svc, _, _, queue = await _live(tape_mm=38)
    try:
        with pytest.raises(SpoolLabelOnlyTapeError) as exc:
            await svc.submit_batch_job([_request(), _swatch_request()], half_cut=False)
        assert exc.value.tape_mm == 38
        assert exc.value.content_types == ("qr_three_lines",)
    finally:
        await queue.stop()


@pytest.mark.parametrize(
    ("tape_mm", "orientation"), [(29, "across"), (38, "along"), (50, "along"), (54, "across")]
)
async def test_all_swatch_batch_takes_the_tape_direction(tape_mm: int, orientation: str) -> None:
    svc, backend, store, queue = await _live(tape_mm=tape_mm)
    try:
        ids = await svc.submit_batch_job([_swatch_request(), _swatch_request()], half_cut=False)
        await _printed(backend, 2)
        assert backend.printed_orientations == [LabelOrientation(orientation)] * 2  # type: ignore[attr-defined]
        assert backend.printed_images[0].tobytes() == _native(tape_mm).tobytes()  # type: ignore[attr-defined]
        row = await store.get(ids[0])  # type: ignore[attr-defined]
        assert row.payload["options"]["orientation"] == orientation
    finally:
        await queue.stop()
