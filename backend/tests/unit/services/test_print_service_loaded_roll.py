# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""#389: every tape job records the roll that was loaded, from a fresh status read.

The test label, a single label, a batch and a deferred job each read the status once and store
``loaded_roll`` (width, media text, kind, colour); a die-cut roll is refused before rendering.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from app.printer_backends.exceptions import MediaTypeMismatchError, PrinterOfflineError
from app.printer_backends.snmp_helper import PreflightStatus
from app.schemas.content_type import ContentType
from app.schemas.print_request import PrintRequest, RawLabelData
from app.services.layout_engine import LayoutEngine
from app.services.print_service import PrintService
from app.services.test_label import TapeTestText
from app.services.test_label import test_label_band as band_of

_PRINTER = UUID("bbbbbbbb-0000-0000-0000-000000000389")


def _service(
    *, width_mm: int = 29, media_raw: str | None = "29mm", colour: str | None = "white"
) -> tuple[PrintService, MagicMock, AsyncMock, list[tuple[Any, ...]]]:
    backend = AsyncMock()
    backend.preflight_check = AsyncMock(
        return_value=PreflightStatus(
            hr_printer_status="idle", loaded_tape_mm=width_mm, error_flags=[], media_raw=media_raw
        )
    )
    queue = MagicMock()
    queue.submit_with_id = AsyncMock()
    queue.enqueue_batch = AsyncMock()
    store = MagicMock()
    store.save_queued = AsyncMock()
    asked: list[tuple[Any, ...]] = []

    async def roll_colour(printer_id: UUID, width: int | None, raw: str | None) -> str | None:
        asked.append((printer_id, width, raw))
        return colour

    svc = PrintService(
        printer_id=_PRINTER,
        backend=backend,
        queue=queue,
        store=store,
        engine=LayoutEngine(),
        roll_colour=roll_colour,
    )
    return svc, store, backend, asked


def _request() -> PrintRequest:
    return PrintRequest(
        content_type=ContentType.TEXT_TWO_LINES,
        data=RawLabelData(title="Box", primary_id="A1"),
    )


def _text(width_mm: int) -> TapeTestText:
    return TapeTestText(
        printer="QL", width_mm=width_mm, printed_at="2026-11-17 09:30", version="t", qr_payload="x"
    )


_ROLL_29 = {"width_mm": 29, "media_raw": "29mm", "media_kind": "continuous", "colour": "white"}
_ROLL_62 = {"width_mm": 62, "media_raw": "62mm", "media_kind": "continuous", "colour": "white"}


@pytest.mark.asyncio
async def test_the_test_label_records_the_loaded_roll() -> None:
    svc, store, backend, asked = _service()

    await svc.submit_test_label(_text, lambda w: band_of("brother_ql", "QL-820NWB", w))

    payload = store.save_queued.await_args.args[0].payload
    assert payload["tape_mm"] == 29
    assert payload["loaded_roll"] == _ROLL_29
    assert asked == [(_PRINTER, 29, "29mm")]
    backend.preflight_check.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_single_label_records_the_loaded_roll() -> None:
    svc, store, _backend, _asked = _service(width_mm=62, media_raw="62mm")

    await svc.submit_print_job(_request())

    assert store.save_queued.await_args.args[0].payload["loaded_roll"] == _ROLL_62


@pytest.mark.asyncio
async def test_every_label_of_a_batch_records_the_roll_after_one_read() -> None:
    svc, store, backend, _asked = _service(width_mm=62, media_raw="62mm")

    await svc.submit_batch_job([_request(), _request()], half_cut=False)

    payloads = [call.args[0].payload for call in store.save_queued.await_args_list]
    assert len(payloads) == 2
    assert all(p["loaded_roll"] == _ROLL_62 for p in payloads)
    backend.preflight_check.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_roll_without_a_colour_records_none() -> None:
    svc, store, _backend, _asked = _service(width_mm=62, media_raw="62mm", colour=None)

    await svc.submit_print_job(_request())

    assert store.save_queued.await_args.args[0].payload["loaded_roll"]["colour"] is None


@pytest.mark.asyncio
async def test_a_failed_colour_read_never_stops_the_print() -> None:
    svc, store, _backend, _asked = _service(width_mm=62, media_raw="62mm")

    async def broken(*_: Any) -> str | None:
        raise RuntimeError("db gone")

    svc._roll_colour = broken

    await svc.submit_print_job(_request())

    assert store.save_queued.await_args.args[0].payload["loaded_roll"]["colour"] is None


@pytest.mark.asyncio
async def test_a_die_cut_roll_is_refused_before_rendering() -> None:
    svc, store, _backend, _asked = _service(media_raw="29mm x 90mm")
    with pytest.raises(MediaTypeMismatchError):
        await svc.submit_test_label(_text, lambda w: band_of("brother_ql", "QL-820NWB", w))

    svc, store, _backend, _asked = _service(width_mm=62, media_raw="62mm x 100mm")
    with pytest.raises(MediaTypeMismatchError):
        await svc.submit_print_job(_request())
    with pytest.raises(MediaTypeMismatchError):
        await svc.submit_batch_job([_request()], half_cut=False)

    store.save_queued.assert_not_called()


@pytest.mark.asyncio
async def test_an_unreadable_status_refuses_the_test_label() -> None:
    svc, store, backend, _asked = _service()
    backend.preflight_check.side_effect = PrinterOfflineError("timeout")

    with pytest.raises(PrinterOfflineError):
        await svc.submit_test_label(_text, lambda w: band_of("brother_ql", "QL-820NWB", w))

    store.save_queued.assert_not_called()
