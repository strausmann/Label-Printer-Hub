# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""#393: a tape printer that takes Brother raster bytes over IPP gets them that way and reports the
job state; the test print finds out what works and stores it.

The printer is ``FakeIppPrinter`` behind ``httpx.ASGITransport`` (as in the IPP client tests); the
SNMP preflight and the TCP 9100 send are faked as in the media check tests.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from app.models.tape import TapeSpec
from app.printer_backends.brother_ql_backend import BrotherQLBackend
from app.printer_backends.exceptions import (
    ConfirmationUnknownError,
    LabelsNotConfirmedError,
    PrinterReportedError,
    PrintFailedError,
)
from app.printer_backends.post_send import check_after_send
from app.printer_backends.snmp_helper import PreflightStatus
from app.printer_backends.tape_confirmation import ConfirmationRecord
from app.services.status_block import MediaType
from app.services.tape_registry import TapeRegistry
from PIL import Image

from tests.helpers.fake_ipp_printer import FailingTransport, FakeIppPrinter

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("real_ql_media_check")]

RASTER = ["application/octet-stream", "image/urf"]


def _spec() -> TapeSpec:
    return TapeRegistry.lookup_ql(29, MediaType.CONTINUOUS_LENGTH_TAPE)


def _image() -> Image.Image:
    return Image.new("1", (306, 120), color=1)


class _Snmp:
    """The SNMP preflight (a counter that rises by ``per_send`` with each 9100 or IPP send) and
    the 9100 send, faked."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, counter: int | None = 100) -> None:
        self.counter = counter
        self.raw_sent: list[bytes] = []
        self.count_raw = False  # a 9100 send moves the counter at once

        async def fake_preflight(host: str, **_: Any) -> PreflightStatus:
            return PreflightStatus(
                hr_printer_status="idle",
                loaded_tape_mm=29,
                error_flags=[],
                media_raw="29mm",
                marker_count=self.counter,
            )

        def fake_send(data: bytes, identifier: str, **_: Any) -> dict[str, str]:
            self.raw_sent.append(data)
            if self.count_raw:
                self.printed(1)
            return {"outcome": "sent"}

        monkeypatch.setattr(
            "app.printer_backends.brother_ql_backend.query_preflight", fake_preflight
        )
        monkeypatch.setattr("app.printer_backends.brother_ql_backend._helpers_send", fake_send)

    def printed(self, labels: int) -> None:
        if self.counter is not None:
            self.counter += labels


def _backend(fake: FakeIppPrinter | None = None, **kw: Any) -> BrotherQLBackend:
    transport = kw.pop("transport", None) or httpx.ASGITransport(app=fake)  # type: ignore[arg-type]
    return BrotherQLBackend(host="192.0.2.30", ipp_transport=transport, **kw)


def _ops(fake: FakeIppPrinter) -> list[str]:
    return [op.operation for op in fake.received]


def _unreachable() -> httpx.MockTransport:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    return httpx.MockTransport(refuse)


async def _confirm(backend: BrotherQLBackend, timeout_s: float = 2.0) -> None:
    await check_after_send(backend, settle_s=0, poll_s=0.001, timeout_s=timeout_s)


# ---------------------------------------------------------------------------- transport choice


async def test_a_printer_that_lists_octet_stream_gets_the_raster_bytes_over_ipp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snmp = _Snmp(monkeypatch)
    fake = FakeIppPrinter(formats=RASTER)
    backend = _backend(fake)

    await backend.print_image(_image(), _spec())

    assert _ops(fake) == ["Get-Printer-Attributes", "Print-Job"]
    assert snmp.raw_sent == []
    job = fake.received[-1]
    assert job.attributes["document-format"] == ["application/octet-stream"]
    assert str(job.attributes["job-name"][0]).startswith("labelyard-tape-")
    # The same bytes the 9100 path sends, unchanged.
    plain = _backend(FakeIppPrinter(formats=["application/pdf"]))
    await plain.print_image(_image(), _spec())
    assert job.document == snmp.raw_sent[-1]


async def test_a_printer_without_octet_stream_gets_tcp_9100(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snmp = _Snmp(monkeypatch)
    fake = FakeIppPrinter(formats=["application/pdf"])

    await _backend(fake).print_image(_image(), _spec())

    assert _ops(fake) == ["Get-Printer-Attributes"]
    assert len(snmp.raw_sent) == 1


async def test_a_printer_that_cannot_follow_or_cancel_a_job_gets_tcp_9100(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Without Get-Job-Attributes (0x0009) and Cancel-Job (0x0008) IPP cannot confirm anything.
    snmp = _Snmp(monkeypatch)
    fake = FakeIppPrinter(formats=RASTER, operations=[0x0002, 0x000B])

    await _backend(fake).print_image(_image(), _spec())

    assert _ops(fake) == ["Get-Printer-Attributes"]
    assert len(snmp.raw_sent) == 1


async def test_a_printer_that_lists_the_job_operations_gets_ipp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snmp = _Snmp(monkeypatch)
    fake = FakeIppPrinter(formats=RASTER, operations=[0x0002, 0x0008, 0x0009, 0x000B])

    await _backend(fake).print_image(_image(), _spec())

    assert _ops(fake) == ["Get-Printer-Attributes", "Print-Job"]
    assert snmp.raw_sent == []


async def test_a_probe_that_fails_falls_back_to_9100_and_is_cached(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    snmp = _Snmp(monkeypatch)
    calls: list[str] = []

    def refuse(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        raise httpx.ConnectError("refused", request=request)

    backend = _backend(transport=httpx.MockTransport(refuse))
    with caplog.at_level("INFO", logger="app.printer_backends.tape_confirmation"):
        await backend.print_image(_image(), _spec())
        await backend.print_image(_image(), _spec())

    assert len(snmp.raw_sent) == 2
    assert calls == ["POST"]  # probed once per backend instance
    assert sum("no usable IPP" in r.message for r in caplog.records) == 1


async def test_the_probe_runs_once_per_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    _Snmp(monkeypatch)
    fake = FakeIppPrinter(formats=RASTER)
    backend = _backend(fake)
    await backend.print_image(_image(), _spec())
    await backend.print_image(_image(), _spec())
    assert _ops(fake).count("Get-Printer-Attributes") == 1


async def test_a_batch_over_ipp_is_one_job(monkeypatch: pytest.MonkeyPatch) -> None:
    snmp = _Snmp(monkeypatch)
    fake = FakeIppPrinter(formats=RASTER)
    await _backend(fake).print_images([_image(), _image(), _image()], _spec())
    assert _ops(fake) == ["Get-Printer-Attributes", "Print-Job"]
    assert snmp.raw_sent == []


async def test_an_interrupted_ipp_upload_fails_the_send(monkeypatch: pytest.MonkeyPatch) -> None:
    _Snmp(monkeypatch)
    fake = FakeIppPrinter(formats=RASTER)
    transport = FailingTransport(httpx.ASGITransport(app=fake), "Print-Job", httpx.ReadError)
    with pytest.raises(PrintFailedError):
        await _backend(transport=transport).print_image(_image(), _spec())


async def test_a_print_job_the_printer_refuses_goes_out_over_9100(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snmp = _Snmp(monkeypatch)
    fake = FakeIppPrinter(formats=RASTER, print_status=0x0400)  # client-error-bad-request
    await _backend(fake).print_image(_image(), _spec())
    assert len(snmp.raw_sent) == 1


# ---------------------------------------------------------------------------- job state


async def test_job_states_5_then_9_confirm_the_label(monkeypatch: pytest.MonkeyPatch) -> None:
    snmp = _Snmp(monkeypatch)
    fake = FakeIppPrinter(formats=RASTER, job_script=[5, 5, 9])
    backend = _backend(fake)
    await backend.print_image(_image(), _spec())
    snmp.printed(1)

    await _confirm(backend)

    assert _ops(fake).count("Get-Job-Attributes") == 3


async def test_an_aborted_job_fails_with_the_impressions_it_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _Snmp(monkeypatch)
    fake = FakeIppPrinter(formats=RASTER, job_script=[5, 8], impressions_script=[1, 3])
    backend = _backend(fake)
    await backend.print_images([_image()] * 5, _spec())

    with pytest.raises(LabelsNotConfirmedError) as err:
        await _confirm(backend)

    assert (err.value.printed, err.value.expected) == (3, 5)


async def test_a_job_that_never_finishes_fails_at_the_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _Snmp(monkeypatch)
    fake = FakeIppPrinter(formats=RASTER, job_script=[5], impressions_script=[0])
    backend = _backend(fake)
    await backend.print_image(_image(), _spec())

    with pytest.raises(LabelsNotConfirmedError) as err:
        await _confirm(backend, timeout_s=0.05)

    assert (err.value.printed, err.value.expected) == (0, 1)


def _cancel_fails(fake: FakeIppPrinter) -> httpx.AsyncBaseTransport:
    return FailingTransport(httpx.ASGITransport(app=fake), "Cancel-Job", httpx.ReadError)  # type: ignore[arg-type]


async def test_a_failed_cancel_with_every_label_counted_is_printed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The job never reports a final state and cannot be cancelled, but the counter rose by exactly
    # the labels sent: nothing is left that may still print.
    snmp = _Snmp(monkeypatch)
    fake = FakeIppPrinter(formats=RASTER, job_script=[5], impressions_script=[0])
    backend = _backend(transport=_cancel_fails(fake))
    await backend.print_image(_image(), _spec())
    snmp.printed(1)

    await _confirm(backend, timeout_s=0.05)

    assert "Cancel-Job" in _ops(fake)


async def test_a_failed_cancel_without_every_label_counted_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _Snmp(monkeypatch)  # the counter never moves
    fake = FakeIppPrinter(formats=RASTER, job_script=[5], impressions_script=[0])
    backend = _backend(transport=_cancel_fails(fake))
    await backend.print_image(_image(), _spec())

    with pytest.raises(ConfirmationUnknownError):
        await _confirm(backend, timeout_s=0.05)


async def test_ipp_wins_over_a_counter_that_disagrees(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _Snmp(monkeypatch)  # the counter never moves
    fake = FakeIppPrinter(formats=RASTER, job_script=[9])
    backend = _backend(fake)
    await backend.print_image(_image(), _spec())
    with caplog.at_level("WARNING", logger="app.printer_backends.post_send"):
        await _confirm(backend)
    assert any("label counter rose by 0" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------- stored record

_AT = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)


async def test_a_stored_raw_is_never_overridden_by_the_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snmp = _Snmp(monkeypatch)
    fake = FakeIppPrinter(formats=RASTER)
    backend = _backend(fake)
    backend.send_state.record = ConfirmationRecord("raw", True, _AT)

    await backend.print_image(_image(), _spec())

    assert _ops(fake) == []
    assert len(snmp.raw_sent) == 1


async def test_a_stored_ipp_is_used_without_a_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    snmp = _Snmp(monkeypatch)
    fake = FakeIppPrinter(formats=RASTER)
    backend = _backend(fake)
    backend.send_state.record = ConfirmationRecord("ipp", True, _AT)

    await backend.print_image(_image(), _spec())

    assert _ops(fake) == ["Print-Job"]
    assert snmp.raw_sent == []


class _Sink:
    def __init__(self) -> None:
        self.records: list[ConfirmationRecord] = []

    async def __call__(self, record: ConfirmationRecord) -> None:
        self.records.append(record)


async def test_a_test_print_with_working_ipp_stores_ipp_and_the_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snmp = _Snmp(monkeypatch)
    fake = FakeIppPrinter(formats=RASTER, job_script=[5, 9])
    backend = _backend(fake)
    backend.send_state.record = ConfirmationRecord("ipp", False, _AT)  # a test print re-decides
    sink = _Sink()
    backend.send_state.sink = sink

    await backend.print_image(_image(), _spec(), detect_confirmation=True)
    snmp.printed(1)
    await _confirm(backend)

    assert "Print-Job" in _ops(fake)
    assert [(r.confirm_transport, r.label_counter) for r in sink.records] == [("ipp", True)]
    assert backend.send_state.record == sink.records[0]


async def test_a_test_print_whose_ipp_is_refused_stores_raw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snmp = _Snmp(monkeypatch)
    backend = _backend(transport=_unreachable())
    sink = _Sink()
    backend.send_state.sink = sink

    await backend.print_image(_image(), _spec(), detect_confirmation=True)
    snmp.printed(1)
    await _confirm(backend)

    assert len(snmp.raw_sent) == 1
    assert [(r.confirm_transport, r.label_counter) for r in sink.records] == [("raw", True)]


async def test_a_test_print_without_a_counter_stores_no_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _Snmp(monkeypatch, counter=None)
    backend = _backend(transport=_unreachable())
    sink = _Sink()
    backend.send_state.sink = sink

    await backend.print_image(_image(), _spec(), detect_confirmation=True)
    await _confirm(backend)

    assert [(r.confirm_transport, r.label_counter) for r in sink.records] == [("raw", False)]
    assert sink.records[0].channel == "none"


async def test_an_ordinary_print_stores_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    snmp = _Snmp(monkeypatch)
    backend = _backend(transport=_unreachable())
    sink = _Sink()
    backend.send_state.sink = sink
    await backend.print_image(_image(), _spec())
    snmp.printed(1)
    await _confirm(backend)
    assert sink.records == []


def test_a_record_reads_back_from_its_json() -> None:
    record = ConfirmationRecord("ipp", True, _AT)
    assert ConfirmationRecord.from_json(record.to_json()) == record
    assert ConfirmationRecord.from_json(None) is None
    assert ConfirmationRecord.from_json({"confirm_transport": "usb"}) is None
    assert ConfirmationRecord("raw", True, _AT).channel == "label_counter"


def test_a_record_keeps_whether_its_ipp_job_did_not_complete() -> None:
    record = ConfirmationRecord("raw", True, _AT, ipp_incomplete=True)
    assert ConfirmationRecord.from_json(record.to_json()) == record
    # A record stored before the field existed reads back as "IPP was not taken".
    legacy = {"confirm_transport": "raw", "label_counter": True, "confirmed_at": _AT.isoformat()}
    assert ConfirmationRecord.from_json(legacy) == ConfirmationRecord("raw", True, _AT)
    assert ConfirmationRecord.from_json({**legacy, "ipp_incomplete": "yes"}) is None


async def test_a_test_print_after_a_refused_ipp_tries_ipp_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # One transient failure (the printer was waking up) must not pin the printer to 9100.
    snmp = _Snmp(monkeypatch)
    fake = FakeIppPrinter(formats=RASTER, job_script=[9])
    backend = _backend(fake)
    backend.send_state.record = ConfirmationRecord("raw", True, _AT)
    sink = _Sink()
    backend.send_state.sink = sink

    await backend.print_image(_image(), _spec(), detect_confirmation=True)
    snmp.printed(1)
    await _confirm(backend)

    assert "Print-Job" in _ops(fake)
    assert snmp.raw_sent == []
    assert [(r.confirm_transport, r.ipp_incomplete) for r in sink.records] == [("ipp", False)]


async def test_a_test_print_whose_ipp_job_did_not_complete_stores_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snmp = _Snmp(monkeypatch)
    fake = FakeIppPrinter(formats=RASTER, job_script=[8], impressions_script=[1])
    backend = _backend(fake)
    sink = _Sink()
    backend.send_state.sink = sink

    await backend.print_image(_image(), _spec(), detect_confirmation=True)
    snmp.printed(1)
    await _confirm(backend)

    assert [(r.confirm_transport, r.label_counter, r.ipp_incomplete) for r in sink.records] == [
        ("raw", True, True)
    ]


async def test_a_test_print_whose_ipp_is_refused_does_not_mark_it_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snmp = _Snmp(monkeypatch)
    backend = _backend(transport=_unreachable())
    sink = _Sink()
    backend.send_state.sink = sink

    await backend.print_image(_image(), _spec(), detect_confirmation=True)
    snmp.printed(1)
    await _confirm(backend)

    assert [r.ipp_incomplete for r in sink.records] == [False]


async def test_a_test_print_aborted_by_a_printer_fault_does_not_pin_9100(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Final review N1: the printer aborted the IPP job because it jammed. That is the printer's
    # fault, not a broken IPP channel: once the jam is cleared, the next test print tries IPP.
    snmp = _Snmp(monkeypatch)
    flags: list[str] = []

    async def preflight(host: str, **_: Any) -> PreflightStatus:
        return PreflightStatus(
            hr_printer_status="idle",
            loaded_tape_mm=29,
            error_flags=list(flags),
            media_raw="29mm",
            marker_count=snmp.counter,
        )

    monkeypatch.setattr("app.printer_backends.brother_ql_backend.query_preflight", preflight)
    fake = FakeIppPrinter(formats=RASTER, job_script=[8], impressions_script=[0])
    backend = _backend(fake)
    sink = _Sink()
    backend.send_state.sink = sink

    await backend.print_image(_image(), _spec(), detect_confirmation=True)
    flags.append("jammed")
    with pytest.raises(PrinterReportedError):
        await _confirm(backend)
    assert [(r.confirm_transport, r.ipp_incomplete) for r in sink.records] == [("raw", False)]

    flags.clear()
    before = len(_ops(fake))
    await backend.print_image(_image(), _spec(), detect_confirmation=True)
    assert "Print-Job" in _ops(fake)[before:]
    assert snmp.raw_sent == []
