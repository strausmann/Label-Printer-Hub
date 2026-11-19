# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Security audit run 26, R26-2: the confirmation wait grows with the length of the labels, and
a printer that still reports ``printing`` gets more time, within a hard bound."""

from __future__ import annotations

import dataclasses
from typing import Any

import httpx
import pytest
from app.printer_backends import post_send
from app.printer_backends.brother_ql_backend import BrotherQLBackend
from app.printer_backends.exceptions import LabelsNotConfirmedError, TapeLabelTooLongError
from app.printer_backends.ptouch_backend import PTouchBackend
from app.printer_backends.snmp_helper import PreflightStatus
from app.printer_backends.tape_confirmation import (
    CONFIRM_BASE_S,
    CONFIRM_PER_LABEL_S,
    CONFIRM_PRINTING_FACTOR,
    TAPE_MIN_SPEED_MM_S,
    TapeIppTransport,
    TapeSendState,
    confirm_timeout_s,
    label_length_mm,
)
from app.services.status_block import MediaType
from app.services.tape_registry import TapeRegistry
from PIL import Image

from tests.helpers.fake_ipp_printer import FakeIppPrinter

pytestmark = pytest.mark.anyio


def test_the_wait_grows_with_the_label_length() -> None:
    assert confirm_timeout_s(1) == CONFIRM_BASE_S + CONFIRM_PER_LABEL_S
    assert confirm_timeout_s(1, length_mm=1600.0) == pytest.approx(
        CONFIRM_BASE_S + CONFIRM_PER_LABEL_S + 1600.0 / TAPE_MIN_SPEED_MM_S
    )


def test_a_label_length_is_its_long_side_at_the_printer_resolution() -> None:
    assert label_length_mm(Image.new("1", (11340, 76)), 180) == pytest.approx(1600.2, abs=0.1)
    assert label_length_mm(Image.new("1", (696, 300)), 300) == pytest.approx(58.9, abs=0.1)


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _Backend:
    """One label of *length_mm* over 9100; every status read takes ten seconds and returns the
    next of *reads* (count, printer state); the last one sticks."""

    def __init__(self, clock: _Clock, length_mm: float, reads: list[tuple[int, str]]) -> None:
        self.clock = clock
        self.reads = reads
        self.count = 0
        self.last_send_status = PreflightStatus(
            hr_printer_status="idle", loaded_tape_mm=12, marker_count=10
        )
        self.send_state = TapeSendState("192.0.2.80", TapeIppTransport("192.0.2.80"))
        self.send_state.labels_sent = 1
        self.send_state.length_mm = length_mm

    @property
    def flags_before_send(self) -> frozenset[str]:
        return frozenset()

    async def read_status(self) -> PreflightStatus:
        count, state = self.reads[min(self.count, len(self.reads) - 1)]
        self.count += 1
        self.clock.now += 10.0
        return PreflightStatus(hr_printer_status=state, loaded_tape_mm=12, marker_count=count)  # type: ignore[arg-type]


async def test_a_long_label_is_confirmed_when_it_comes_out_after_the_short_label_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 1.6 m of tape: the counter rises only after 60 s, well past 15 s + 8 s.
    clock = _Clock()
    monkeypatch.setattr(post_send, "_now", clock)
    backend = _Backend(clock, 1600.0, [(10, "printing")] * 6 + [(11, "idle")])
    await post_send.check_after_send(backend, settle_s=0, poll_s=0)
    assert backend.count == 7


async def test_a_printer_that_still_prints_gets_more_time_within_a_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A short label whose printer reports printing past the budget (23 s) and finishes at 40 s.
    clock = _Clock()
    monkeypatch.setattr(post_send, "_now", clock)
    backend = _Backend(clock, 0.0, [(10, "printing")] * 4 + [(11, "idle")])
    await post_send.check_after_send(backend, settle_s=0, poll_s=0)
    assert backend.count == 5


async def test_a_printer_that_prints_for_ever_still_ends_at_the_hard_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock()
    monkeypatch.setattr(post_send, "_now", clock)
    backend = _Backend(clock, 0.0, [(10, "printing")])
    start = clock.now
    with pytest.raises(LabelsNotConfirmedError):
        await post_send.check_after_send(backend, settle_s=0, poll_s=0)
    assert clock.now - start <= confirm_timeout_s(1) * CONFIRM_PRINTING_FACTOR + 10.0


async def test_the_ipp_wait_keeps_waiting_while_the_job_is_processing() -> None:
    fake = FakeIppPrinter(formats=["application/octet-stream"], job_script=[5] * 40 + [9])
    ipp = TapeIppTransport("192.0.2.81", transport=httpx.ASGITransport(app=fake))  # type: ignore[arg-type]
    job = await ipp.submit(b"x", 1)
    outcome = await ipp.wait([(job, 1)], timeout_s=0.0, hard_timeout_s=5.0, poll_s=0.0)
    assert outcome.completed


async def test_the_ipp_wait_stops_at_the_hard_bound() -> None:
    fake = FakeIppPrinter(formats=["application/octet-stream"], job_script=[5])
    ipp = TapeIppTransport("192.0.2.82", transport=httpx.ASGITransport(app=fake))  # type: ignore[arg-type]
    job = await ipp.submit(b"x", 1)
    outcome = await ipp.wait([(job, 1)], timeout_s=0.0, hard_timeout_s=0.05, poll_s=0.0)
    assert not outcome.completed and outcome.pending == job


async def test_a_pt_backend_records_the_length_it_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    async def preflight(host: str, **_: Any) -> PreflightStatus:
        return PreflightStatus(hr_printer_status="idle", loaded_tape_mm=12, media_raw="12mm")

    monkeypatch.setattr("app.printer_backends.ptouch_backend.query_preflight", preflight)
    monkeypatch.setattr("app.printer_backends.ptouch_backend._ptouch_print", lambda *a, **k: None)
    backend = PTouchBackend(host="192.0.2.83", ipp_transport=_refusing())
    await backend.print_image(
        Image.new("1", (1134, 76), 1), TapeRegistry.lookup_pt(12, MediaType.LAMINATED)
    )
    assert backend.send_state.length_mm == pytest.approx(160.0, abs=0.1)


async def test_a_ql_backend_records_the_length_it_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    async def preflight(host: str, **_: Any) -> PreflightStatus:
        return PreflightStatus(hr_printer_status="idle", loaded_tape_mm=29, media_raw="29mm")

    monkeypatch.setattr("app.printer_backends.brother_ql_backend.query_preflight", preflight)
    monkeypatch.setattr(
        "app.printer_backends.brother_ql_backend._helpers_send", lambda *a, **k: {"outcome": "sent"}
    )
    backend = BrotherQLBackend(host="192.0.2.84", ipp_transport=_refusing())
    # 29 mm along: the 306 px band, 1181 px long at 300 dpi = 100 mm of tape.
    await backend.print_image(
        Image.new("1", (1181, 306), 1), TapeRegistry.lookup_ql(29, MediaType.CONTINUOUS_LENGTH_TAPE)
    )
    assert backend.send_state.length_mm == pytest.approx(100.0, abs=0.5)


def _refusing() -> httpx.MockTransport:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    return httpx.MockTransport(refuse)


# ---------------------------------------------------------------------------- max_length_mm


async def test_a_pt_label_longer_than_the_tape_allows_is_refused_before_sending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[object] = []

    async def preflight(host: str, **_: Any) -> PreflightStatus:
        return PreflightStatus(hr_printer_status="idle", loaded_tape_mm=12, media_raw="12mm")

    monkeypatch.setattr("app.printer_backends.ptouch_backend.query_preflight", preflight)
    monkeypatch.setattr(
        "app.printer_backends.ptouch_backend._ptouch_print", lambda *a, **k: sent.append(a)
    )
    spec = TapeRegistry.lookup_pt(12, MediaType.LAMINATED)
    backend = PTouchBackend(host="192.0.2.85", ipp_transport=_refusing())
    too_long = Image.new("1", (round((spec.max_length_mm + 10) / 25.4 * 180), 76), 1)
    with pytest.raises(TapeLabelTooLongError) as err:
        await backend.print_image(too_long, spec)
    assert err.value.nothing_sent
    assert err.value.max_mm == spec.max_length_mm and err.value.length_mm > spec.max_length_mm
    assert sent == []
    fits = Image.new("1", (round((spec.max_length_mm - 10) / 25.4 * 180), 76), 1)
    await backend.print_image(fits, spec)
    assert len(sent) == 1


async def test_a_pt_batch_with_one_label_too_long_sends_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[object] = []

    async def preflight(host: str, **_: Any) -> PreflightStatus:
        return PreflightStatus(hr_printer_status="idle", loaded_tape_mm=12, media_raw="12mm")

    monkeypatch.setattr("app.printer_backends.ptouch_backend.query_preflight", preflight)
    monkeypatch.setattr(
        "app.printer_backends.ptouch_backend._ptouch_print_multi", lambda *a, **k: sent.append(a)
    )
    spec = TapeRegistry.lookup_pt(12, MediaType.LAMINATED)
    backend = PTouchBackend(host="192.0.2.86", ipp_transport=_refusing())
    too_long = Image.new("1", (round((spec.max_length_mm + 10) / 25.4 * 180), 76), 1)
    with pytest.raises(TapeLabelTooLongError):
        await backend.print_images([Image.new("1", (300, 76), 1), too_long], spec)
    assert sent == []


async def test_a_ql_label_longer_than_the_tape_allows_is_refused_before_sending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[object] = []
    monkeypatch.setattr(
        "app.printer_backends.brother_ql_backend._helpers_send",
        lambda *a, **k: sent.append(a) or {"outcome": "sent"},
    )
    spec = dataclasses.replace(
        TapeRegistry.lookup_ql(29, MediaType.CONTINUOUS_LENGTH_TAPE), max_length_mm=50
    )
    backend = BrotherQLBackend(host="192.0.2.87", ipp_transport=_refusing())
    with pytest.raises(TapeLabelTooLongError) as err:
        await backend.print_image(Image.new("1", (1181, 306), 1), spec)  # 100 mm
    assert err.value.nothing_sent and (err.value.length_mm, err.value.max_mm) == (100, 50)
    with pytest.raises(TapeLabelTooLongError):
        await backend.print_images(
            [Image.new("1", (300, 306), 1)] * 2 + [Image.new("1", (1181, 306), 1)], spec
        )
    assert sent == []


def test_a_label_too_long_maps_to_its_own_code() -> None:
    from app.services.print_error_codes import describe_print_error
    from app.services.print_queue import _printer_error_to_record

    exc = TapeLabelTooLongError(length_mm=1601, max_mm=1000)
    known = describe_print_error(exc)
    assert (known.status, known.code) == (422, "tape_label_too_long")
    assert known.detail == {"length_mm": 1601, "max_mm": 1000}
    assert _printer_error_to_record(exc)[0] == "tape_label_too_long"
    assert _printer_error_to_record(exc)[2] == {"length_mm": 1601, "max_mm": 1000}


async def test_a_negative_impression_count_is_clamped_at_the_source() -> None:
    # Run 26, hardening note 7: a printer that reports -5 impressions printed nothing.
    fake = FakeIppPrinter(
        formats=["application/octet-stream"], job_script=[8], impressions_script=[-5]
    )
    ipp = TapeIppTransport("192.0.2.88", transport=httpx.ASGITransport(app=fake))  # type: ignore[arg-type]
    job = await ipp.submit(b"x", 1)
    outcome = await ipp.wait([(job, 1)], timeout_s=1.0, poll_s=0.0)
    assert (outcome.completed, outcome.printed) == (False, 0)


async def test_a_negative_impression_count_after_a_cancel_is_clamped_too() -> None:
    fake = FakeIppPrinter(
        formats=["application/octet-stream"], job_script=[5], impressions_after_cancel=-3
    )
    ipp = TapeIppTransport("192.0.2.89", transport=httpx.ASGITransport(app=fake))  # type: ignore[arg-type]
    job = await ipp.submit(b"x", 1)
    outcome = await ipp.cancel(job, poll_s=0.0)
    assert (outcome.result, outcome.impressions) == ("cancelled", 0)


def test_the_tape_length_code_is_not_the_sheet_text_code() -> None:
    # Review round 3, R3-1: `label_too_long` is a sheet text over its limit (264-12).
    from app.services.print_error_codes import describe_print_error
    from app.sheets.errors import TextTooLongError

    tape = describe_print_error(TapeLabelTooLongError(length_mm=1601, max_mm=1000)).code
    assert tape != TextTooLongError.error_code


async def test_a_360_dpi_model_measures_its_labels_at_360_dpi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Review round 3: the resolution comes from the model's entry, not a fixed 180 dpi.
    async def preflight(host: str, **_: Any) -> PreflightStatus:
        return PreflightStatus(hr_printer_status="idle", loaded_tape_mm=12, media_raw="12mm")

    monkeypatch.setattr("app.printer_backends.ptouch_backend.query_preflight", preflight)
    monkeypatch.setattr("app.printer_backends.ptouch_backend._ptouch_print", lambda *a, **k: None)
    spec = TapeRegistry.lookup_pt(12, MediaType.LAMINATED)
    backend = PTouchBackend(host="192.0.2.90", model_id="PT-P900W", ipp_transport=_refusing())
    # 700 mm at 360 dpi: 1400 mm if it were measured at 180 dpi, over the 1000 mm of TZe tape.
    await backend.print_image(Image.new("1", (round(700 / 25.4 * 360), 152), 1), spec)
    assert backend.send_state.length_mm == pytest.approx(700.0, abs=0.5)
