# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""#277: failures before anything is sent carry ``PrinterError.nothing_sent``.

The tape-run queue reads the flag: a flagged group did not print (its real error code), an
unflagged one may have (``outcome_unknown``).
"""

from __future__ import annotations

import dataclasses
from unittest.mock import AsyncMock

import pytest
from app.models.tape import TapeSpec
from app.printer_backends.brother_ql_backend import BrotherQLBackend
from app.printer_backends.exceptions import PrintFailedError
from app.printer_backends.mock_backend import MockPrinterBackend
from app.printer_backends.ptouch_backend import PTouchBackend
from app.printer_backends.snmp_helper import PreflightStatus
from app.printer_models.pt import PTP750WDriver
from app.printer_models.ql import QL820NWBDriver
from app.services.status_block import MediaType
from app.services.tape_registry import TapeRegistry
from PIL import Image

pytestmark = pytest.mark.anyio


def _img() -> Image.Image:
    return Image.new("1", (40, 20), color=1)


def _width(spec: TapeSpec, width_mm: int) -> TapeSpec:
    return dataclasses.replace(spec, width_mm=width_mm)


async def test_a_ql_label_width_without_a_mapping_is_refused_before_sending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = AsyncMock()
    monkeypatch.setattr("app.printer_backends.brother_ql_backend._helpers_send", sent)
    backend = BrotherQLBackend(host="192.0.2.11")
    spec = TapeRegistry.lookup_ql(62, MediaType.CONTINUOUS_LENGTH_TAPE)
    unmapped = _width(spec, 63)

    with pytest.raises(PrintFailedError) as err:
        await backend.print_images([_img(), _img()], unmapped)

    assert err.value.nothing_sent is True
    sent.assert_not_called()


async def test_a_ptouch_tape_without_a_tape_class_is_refused_before_sending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    multi = AsyncMock()
    monkeypatch.setattr("app.printer_backends.ptouch_backend._ptouch_print_multi", multi)
    backend = PTouchBackend(host="192.0.2.10")
    backend.preflight_check = AsyncMock(  # type: ignore[method-assign]
        return_value=PreflightStatus(hr_printer_status="idle", loaded_tape_mm=5)
    )
    spec = TapeRegistry.lookup_pt(12, MediaType.LAMINATED)
    no_class = _width(spec, 5)

    with pytest.raises(PrintFailedError) as err:
        await backend.print_images([_img()], no_class)

    assert err.value.nothing_sent is True
    multi.assert_not_called()


@pytest.mark.parametrize("driver", [PTP750WDriver, QL820NWBDriver])
async def test_the_queue_adapters_flag_a_tape_spec_lookup_failure(driver: type) -> None:
    backend = MockPrinterBackend()
    printer = driver(backend=backend).make_queue_printer(TapeRegistry())

    with pytest.raises(PrintFailedError) as err:
        await printer.print_images([_img()], tape_mm=12, media_type=MediaType.HEAT_SHRINK_3_1)

    assert err.value.nothing_sent is True
    assert backend.printed_images == []


async def test_a_send_failure_is_not_flagged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Counter-check: a write error while sending stays unflagged (outcome unknown)."""
    import ptouch

    def broken(*_a: object, **_kw: object) -> None:
        raise ptouch.PrinterWriteError("pipe broke")

    monkeypatch.setattr("app.printer_backends.ptouch_backend._ptouch_print_multi", broken)
    backend = PTouchBackend(host="192.0.2.10")
    backend.preflight_check = AsyncMock(  # type: ignore[method-assign]
        return_value=PreflightStatus(hr_printer_status="idle", loaded_tape_mm=12)
    )

    with pytest.raises(PrintFailedError) as err:
        await backend.print_images([_img()], TapeRegistry.lookup_pt(12, MediaType.LAMINATED))

    assert err.value.nothing_sent is False
