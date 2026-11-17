# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""#389: the status check after sending, and the media kind read from the media text."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from app.printer_backends.exceptions import (
    PrinterOfflineError,
    PrinterReportedError,
    TapeEmptyError,
)
from app.printer_backends.post_send import check_after_send
from app.printer_backends.snmp_helper import PreflightStatus, parse_media_kind

pytestmark = pytest.mark.anyio


def _backend(*flags: str) -> AsyncMock:
    backend = AsyncMock()
    backend.preflight_check = AsyncMock(
        return_value=PreflightStatus(
            hr_printer_status="idle", loaded_tape_mm=29, error_flags=list(flags)
        )
    )
    return backend


async def test_an_error_state_after_sending_raises_with_its_flags() -> None:
    backend = _backend("lowPaper", "jammed")

    with pytest.raises(PrinterReportedError) as err:
        await check_after_send(backend, settle_s=0)

    assert err.value.flags == ["jammed"]
    backend.preflight_check.assert_awaited_once()


async def test_warnings_alone_do_not_fail_the_job() -> None:
    await check_after_send(_backend("lowPaper", "lowToner", "overduePreventMaint"), settle_s=0)


async def test_the_backends_own_refusals_pass_through() -> None:
    backend = AsyncMock()
    backend.preflight_check = AsyncMock(side_effect=TapeEmptyError())
    with pytest.raises(TapeEmptyError):
        await check_after_send(backend, settle_s=0)

    backend.preflight_check = AsyncMock(side_effect=PrinterOfflineError("timeout"))
    with pytest.raises(PrinterOfflineError):
        await check_after_send(backend, settle_s=0)


async def test_the_check_waits_before_it_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []

    async def fake_sleep(seconds: float) -> None:
        order.append(f"sleep {seconds}")

    monkeypatch.setattr("app.printer_backends.post_send.asyncio.sleep", fake_sleep)
    backend = _backend()
    backend.preflight_check.side_effect = lambda: (
        order.append("read")
        or PreflightStatus(hr_printer_status="idle", loaded_tape_mm=29, error_flags=[])
    )

    await check_after_send(backend, settle_s=1.5)

    assert order == ["sleep 1.5", "read"]


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("29mm", "continuous"),
        ('12mm(0.47")', "continuous"),
        ("62mm", "continuous"),
        ('62mm / 2.4"', "continuous"),
        ("29mm x 90mm", "die_cut"),
        ("29 x 90 mm", "die_cut"),
        ("62x100mm", "die_cut"),
        ("29mm\u00d790mm", "die_cut"),
        ("", None),
        (None, None),
        ("unknown", None),
    ],
)
def test_media_kind_from_the_media_text(text: str | None, kind: str | None) -> None:
    assert parse_media_kind(text) == kind
    assert (
        PreflightStatus(hr_printer_status="idle", loaded_tape_mm=None, media_raw=text).media_kind
        == kind
    )
