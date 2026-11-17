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
    backend.preflight_check = AsyncMock(  # type: ignore[method-assign]
        return_value=PreflightStatus(
            hr_printer_status="other", loaded_tape_mm=29, error_flags=["jammed"]
        )
    )
    printer = driver(backend=backend).make_queue_printer(TapeRegistry())
    printer.post_send_settle_s = 0

    with pytest.raises(PrinterReportedError) as err:
        await getattr(printer, method)()

    assert err.value.flags == ["jammed"]
    backend.preflight_check.assert_awaited_once()


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
