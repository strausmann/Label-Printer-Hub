# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""#393 review round 1, the IPP side (QL backend against ``FakeIppPrinter``).

- C1: an accepted IPP test job that does not complete is never sent again over TCP 9100.
- I2: a timed-out IPP job is cancelled; when the cancel fails the labels may still print.
- I3: a job the printer forgot after it was seen is left to the label counter.
- M3: the upload timeout grows with the labels.
- M4: an agent that refuses the counter is not asked for it again.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from app.models.tape import TapeSpec
from app.printer_backends import tape_confirmation
from app.printer_backends.brother_ql_backend import BrotherQLBackend
from app.printer_backends.exceptions import (
    ConfirmationUnknownError,
    LabelsNotConfirmedError,
)
from app.printer_backends.post_send import check_after_send
from app.printer_backends.snmp_helper import PreflightStatus
from app.printer_backends.tape_confirmation import (
    ConfirmationRecord,
    TapeIppTransport,
    confirm_timeout_s,
)
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
    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, counter: int | None = 100) -> None:
        self.counter = counter
        self.raw_sent: list[bytes] = []
        self.asked_counter: list[bool] = []

        async def fake_preflight(host: str, **kw: Any) -> PreflightStatus:
            self.asked_counter.append(kw.get("ask_counter", True))
            return PreflightStatus(
                hr_printer_status="idle",
                loaded_tape_mm=29,
                error_flags=[],
                media_raw="29mm",
                marker_count=self.counter,
            )

        def fake_send(data: bytes, identifier: str, **_: Any) -> dict[str, str]:
            self.raw_sent.append(data)
            return {"outcome": "sent"}

        monkeypatch.setattr(
            "app.printer_backends.brother_ql_backend.query_preflight", fake_preflight
        )
        monkeypatch.setattr("app.printer_backends.brother_ql_backend._helpers_send", fake_send)


class _Sink:
    def __init__(self) -> None:
        self.records: list[ConfirmationRecord] = []

    async def __call__(self, record: ConfirmationRecord) -> None:
        self.records.append(record)


def _backend(transport: httpx.AsyncBaseTransport) -> BrotherQLBackend:
    return BrotherQLBackend(host="192.0.2.30", ipp_transport=transport)


def _ops(fake: FakeIppPrinter) -> list[str]:
    return [op.operation for op in fake.received]


async def _confirm(backend: BrotherQLBackend, timeout_s: float = 2.0) -> None:
    await check_after_send(backend, settle_s=0, poll_s=0.001, timeout_s=timeout_s)


# ---------------------------------------------------------------------------- C1


@pytest.mark.parametrize(
    ("script", "timeout_s"), [([8], 2.0), ([5], 0.05)], ids=["aborted", "timeout"]
)
async def test_an_ipp_test_job_that_does_not_complete_is_never_sent_over_9100(
    monkeypatch: pytest.MonkeyPatch, script: list[int], timeout_s: float
) -> None:
    snmp = _Snmp(monkeypatch)
    fake = FakeIppPrinter(formats=RASTER, job_script=script, impressions_script=[0])
    backend = _backend(httpx.ASGITransport(app=fake))  # type: ignore[arg-type]
    sink = _Sink()
    backend.send_state.sink = sink

    await backend.print_image(_image(), _spec(), detect_confirmation=True)
    with pytest.raises(LabelsNotConfirmedError) as err:
        await _confirm(backend, timeout_s=timeout_s)

    assert (err.value.printed, err.value.expected) == (0, 1)
    assert snmp.raw_sent == []
    assert [(r.confirm_transport, r.label_counter) for r in sink.records] == [("raw", False)]


# ---------------------------------------------------------------------------- I2


async def test_a_timed_out_ipp_job_is_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    _Snmp(monkeypatch)
    fake = FakeIppPrinter(formats=RASTER, job_script=[5], impressions_script=[0])
    backend = _backend(httpx.ASGITransport(app=fake))  # type: ignore[arg-type]
    await backend.print_image(_image(), _spec())

    with pytest.raises(LabelsNotConfirmedError):
        await _confirm(backend, timeout_s=0.05)

    cancel = [op for op in fake.received if op.operation == "Cancel-Job"]
    assert [op.attributes["job-id"] for op in cancel] == [[1]]


async def test_a_timed_out_job_whose_cancel_fails_may_still_print(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _Snmp(monkeypatch)
    fake = FakeIppPrinter(formats=RASTER, job_script=[5], impressions_script=[0])
    transport = FailingTransport(httpx.ASGITransport(app=fake), "Cancel-Job", httpx.ReadError)  # type: ignore[arg-type]
    backend = _backend(transport)
    await backend.print_image(_image(), _spec())

    with pytest.raises(ConfirmationUnknownError) as err:
        await _confirm(backend, timeout_s=0.05)

    assert "may still print" in str(err.value)


# ---------------------------------------------------------------------------- I3


class _Forgetting(httpx.AsyncBaseTransport):
    """The printer drops the job from its table after the first Get-Job-Attributes."""

    def __init__(self, fake: FakeIppPrinter) -> None:
        self.fake = fake
        self.inner = httpx.ASGITransport(app=fake)  # type: ignore[arg-type]

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self.inner.handle_async_request(request)
        if _ops(self.fake).count("Get-Job-Attributes") >= 1:
            self.fake.forget_jobs()
        return response


async def test_a_job_the_printer_forgot_is_left_to_the_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snmp = _Snmp(monkeypatch)
    fake = FakeIppPrinter(formats=RASTER, job_script=[5])
    backend = _backend(_Forgetting(fake))
    await backend.print_image(_image(), _spec())
    snmp.counter = 101  # the label came out

    await _confirm(backend, timeout_s=5.0)

    assert _ops(fake).count("Get-Job-Attributes") == 2  # seen once, then not found: no more polls


async def test_a_forgotten_job_without_a_counter_counts_as_printed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _Snmp(monkeypatch, counter=None)
    fake = FakeIppPrinter(formats=RASTER, job_script=[5])
    backend = _backend(_Forgetting(fake))
    await backend.print_image(_image(), _spec())
    with caplog.at_level("WARNING", logger="app.printer_backends.post_send"):
        await _confirm(backend, timeout_s=5.0)
    assert any("counted as printed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------- M3


async def test_the_upload_timeout_grows_with_the_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[float] = []

    class _Client:
        def __init__(self, uri: str, **kw: Any) -> None:
            seen.append(kw["upload_timeout_s"])

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        async def print_job(self, *_a: Any) -> Any:
            class _Accepted:
                job_id = 1

            return _Accepted()

    monkeypatch.setattr(tape_confirmation, "IppClient", _Client)
    ipp = TapeIppTransport("192.0.2.40")
    await ipp.submit(b"x", labels=1)
    await ipp.submit(b"x", labels=10)
    assert seen == [30.0, confirm_timeout_s(10)]


# ---------------------------------------------------------------------------- M4


async def test_an_agent_that_refused_the_counter_is_not_asked_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snmp = _Snmp(monkeypatch, counter=None)
    backend = BrotherQLBackend(host="192.0.2.30")

    async def refusing(host: str, **kw: Any) -> PreflightStatus:
        snmp.asked_counter.append(kw.get("ask_counter", True))
        return PreflightStatus(
            hr_printer_status="idle",
            loaded_tape_mm=29,
            media_raw="29mm",
            counter_refused=kw.get("ask_counter", True),
        )

    monkeypatch.setattr("app.printer_backends.brother_ql_backend.query_preflight", refusing)
    await backend.read_status()
    await backend.read_status()
    assert snmp.asked_counter == [True, False]
