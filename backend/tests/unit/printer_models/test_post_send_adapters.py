# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""#389: the QL and PT queue printers read the status after sending, single jobs and runs alike."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from app.printer_backends.exceptions import PrinterReportedError
from app.printer_backends.mock_backend import MockPrinterBackend
from app.printer_backends.post_send import POST_SEND_SETTLE_S
from app.printer_backends.snmp_helper import PreflightStatus
from app.printer_models.pt import PTP750WDriver
from app.printer_models.ql import QL820NWBDriver
from app.services.tape_registry import TapeRegistry

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("driver", [QL820NWBDriver, PTP750WDriver])
@pytest.mark.parametrize("method", ["check_after_send", "check_status"])
async def test_an_error_bit_after_sending_raises(driver: type, method: str) -> None:
    backend = MockPrinterBackend()
    backend.read_status = AsyncMock(  # type: ignore[method-assign]
        return_value=PreflightStatus(
            hr_printer_status="other", loaded_tape_mm=29, error_flags=["jammed"]
        )
    )
    printer = driver(backend=backend).make_queue_printer(TapeRegistry())
    printer.post_send_settle_s = 0

    with pytest.raises(PrinterReportedError) as err:
        await getattr(printer, method)()

    assert err.value.flags == ["jammed"]
    backend.read_status.assert_awaited_once()


@pytest.mark.parametrize("driver", [QL820NWBDriver, PTP750WDriver])
async def test_a_real_printer_is_given_time_before_the_status_is_read(
    driver: type, monkeypatch: pytest.MonkeyPatch
) -> None:
    waited: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waited.append(seconds)

    monkeypatch.setattr("app.printer_backends.post_send.asyncio.sleep", fake_sleep)
    # Without the mock's own ``post_send_settle_s`` the backend looks like a real printer.
    monkeypatch.delattr(MockPrinterBackend, "post_send_settle_s")
    printer = driver(backend=MockPrinterBackend()).make_queue_printer(TapeRegistry())

    await printer.check_after_send()

    assert waited == [POST_SEND_SETTLE_S]


@pytest.mark.parametrize("driver", [QL820NWBDriver, PTP750WDriver])
async def test_the_mock_backend_is_not_waited_for(
    driver: type, monkeypatch: pytest.MonkeyPatch
) -> None:
    waited: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waited.append(seconds)

    monkeypatch.setattr("app.printer_backends.post_send.asyncio.sleep", fake_sleep)
    printer = driver(backend=MockPrinterBackend()).make_queue_printer(TapeRegistry())

    await printer.check_after_send()

    assert waited == []


@pytest.mark.parametrize(("driver", "tape_mm"), [(QL820NWBDriver, 62), (PTP750WDriver, 24)])
async def test_the_test_print_flag_reaches_the_backend(driver: type, tape_mm: int) -> None:
    """#393: ``detect_confirmation`` (the test print) is handed to the backend's send, never an
    ordinary print's."""
    backend = MockPrinterBackend(loaded_tape_mm=tape_mm)
    seen: list[bool] = []
    real = backend.print_image

    async def spy(*args: object, detect_confirmation: bool = False, **kw: object) -> None:
        seen.append(detect_confirmation)
        await real(*args, **kw)  # type: ignore[arg-type]

    backend.print_image = spy  # type: ignore[method-assign]
    printer = driver(backend=backend).make_queue_printer(TapeRegistry())
    from PIL import Image

    image = Image.new("1", (120, 40), color=1)
    await printer.print_image(image, tape_mm=tape_mm, detect_confirmation=True)
    await printer.print_image(image, tape_mm=tape_mm)
    assert seen == [True, False]


async def test_the_mock_counts_its_labels() -> None:
    """#393: the mock's fake label counter rises by the labels it prints, so the check after
    sending confirms them at once."""
    from PIL import Image

    backend = MockPrinterBackend(loaded_tape_mm=62)
    printer = QL820NWBDriver(backend=backend).make_queue_printer(TapeRegistry())
    images = [Image.new("1", (120, 40), color=1)] * 3
    await printer.print_images(images, tape_mm=62)
    assert backend.labels_sent == 3
    assert backend.last_send_status is not None
    assert backend.last_send_status.marker_count == 0
    assert backend.label_counter == 3
    await printer.check_status()
