# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""#389: the QL backend checks the loaded roll right before it sends, and reads the send result.

A job drawn for one roll and sent after a roll change (queued behind a pause, a retry of an old
job) is refused before anything reaches the printer, like the PT backend already does.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.models.tape import TapeSpec
from app.printer_backends.brother_ql_backend import BrotherQLBackend
from app.printer_backends.exceptions import (
    MediaTypeMismatchError,
    PrinterOfflineError,
    PrintFailedError,
    TapeMismatchError,
)
from app.printer_backends.snmp_helper import PreflightStatus, SnmpQueryError
from app.services.status_block import MediaType
from app.services.tape_registry import TapeRegistry
from PIL import Image

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("real_ql_media_check")]


def _spec(width_mm: int) -> TapeSpec:
    return TapeRegistry.lookup_ql(width_mm, MediaType.CONTINUOUS_LENGTH_TAPE)


def _image() -> Image.Image:
    return Image.new("1", (306, 120), color=1)


class _Printer:
    """Fakes for the SNMP preflight and ``helpers.send``; counts both."""

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, *, loaded_mm: int | None, media_raw: str | None
    ) -> None:
        self.preflights = 0
        self.sent: list[int] = []
        self.send_result: Any = {"outcome": "sent"}

        async def fake_preflight(host: str, **_: Any) -> PreflightStatus:
            self.preflights += 1
            return PreflightStatus(
                hr_printer_status="idle",
                loaded_tape_mm=loaded_mm,
                error_flags=[],
                media_raw=media_raw,
            )

        def fake_send(data: bytes, identifier: str, **_: Any) -> Any:
            self.sent.append(len(data))
            return self.send_result

        monkeypatch.setattr(
            "app.printer_backends.brother_ql_backend.query_preflight", fake_preflight
        )
        monkeypatch.setattr("app.printer_backends.brother_ql_backend._helpers_send", fake_send)


async def test_a_label_drawn_for_62_mm_is_refused_on_a_29_mm_roll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    printer = _Printer(monkeypatch, loaded_mm=29, media_raw="29mm")

    with pytest.raises(TapeMismatchError) as err:
        await BrotherQLBackend(host="192.0.2.11").print_image(_image(), _spec(62))

    assert (err.value.expected_mm, err.value.loaded_mm) == (62, 29)
    assert err.value.nothing_sent is True
    assert printer.sent == []


async def test_a_matching_roll_is_sent_after_one_check(monkeypatch: pytest.MonkeyPatch) -> None:
    printer = _Printer(monkeypatch, loaded_mm=29, media_raw="29mm")

    await BrotherQLBackend(host="192.0.2.11").print_image(_image(), _spec(29))

    assert printer.preflights == 1
    assert len(printer.sent) == 1


async def test_a_die_cut_roll_is_refused_before_sending(monkeypatch: pytest.MonkeyPatch) -> None:
    printer = _Printer(monkeypatch, loaded_mm=29, media_raw="29mm x 90mm")

    with pytest.raises(MediaTypeMismatchError) as err:
        await BrotherQLBackend(host="192.0.2.11").print_image(_image(), _spec(29))

    assert err.value.loaded_kind == "die_cut"
    assert err.value.media_raw == "29mm x 90mm"
    assert err.value.nothing_sent is True
    assert printer.sent == []


async def test_an_unreadable_status_refuses_instead_of_guessing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[bytes] = []

    async def fails(host: str, **_: Any) -> PreflightStatus:
        raise SnmpQueryError("timeout")

    monkeypatch.setattr("app.printer_backends.brother_ql_backend.query_preflight", fails)
    monkeypatch.setattr(
        "app.printer_backends.brother_ql_backend._helpers_send",
        lambda data, *a, **k: sent.append(data),
    )

    with pytest.raises(PrinterOfflineError) as err:
        await BrotherQLBackend(host="192.0.2.11").print_image(_image(), _spec(29))

    assert err.value.nothing_sent is True
    assert sent == []


async def test_a_batch_is_checked_once_not_per_label(monkeypatch: pytest.MonkeyPatch) -> None:
    printer = _Printer(monkeypatch, loaded_mm=29, media_raw="29mm")

    await BrotherQLBackend(host="192.0.2.11").print_images(
        [_image(), _image(), _image()], _spec(29)
    )

    assert printer.preflights == 1
    assert len(printer.sent) == 3


async def test_a_batch_on_the_wrong_roll_sends_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    printer = _Printer(monkeypatch, loaded_mm=62, media_raw="62mm")

    with pytest.raises(TapeMismatchError) as err:
        await BrotherQLBackend(host="192.0.2.11").print_images([_image(), _image()], _spec(29))

    assert err.value.nothing_sent is True
    assert printer.sent == []


async def test_an_error_outcome_of_the_send_fails_the_print(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    printer = _Printer(monkeypatch, loaded_mm=29, media_raw="29mm")
    printer.send_result = {"outcome": "error", "printer_state": {"errors": ["Wrong roll type"]}}

    with pytest.raises(PrintFailedError) as err:
        await BrotherQLBackend(host="192.0.2.11").print_image(_image(), _spec(29))

    assert err.value.nothing_sent is False
