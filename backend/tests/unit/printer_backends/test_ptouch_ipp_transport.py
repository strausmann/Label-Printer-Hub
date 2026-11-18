# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""#393: the PT-P750W takes the ptouch raster bytes as an IPP Print-Job too.

``ptouch`` only writes to a connection; a capturing connection collects the bytes it would send
over TCP 9100, and those go out as the document.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from app.models.tape import TapeSpec
from app.printer_backends.ptouch_backend import PTouchBackend, _ptouch_render
from app.printer_backends.snmp_helper import PreflightStatus
from app.services.status_block import MediaType
from app.services.tape_registry import TapeRegistry
from PIL import Image

from tests.helpers.fake_ipp_printer import FakeIppPrinter

pytestmark = pytest.mark.anyio


def _spec() -> TapeSpec:
    return TapeRegistry.lookup_pt(12, MediaType.LAMINATED)


def _image() -> Image.Image:
    return Image.new("1", (200, 76), color=1)


@pytest.fixture
def raw_sends(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    sent: list[str] = []

    async def fake_preflight(host: str, **_: Any) -> PreflightStatus:
        return PreflightStatus(
            hr_printer_status="idle", loaded_tape_mm=12, error_flags=[], marker_count=190
        )

    def fake_print(*_a: Any, **_kw: Any) -> None:
        sent.append("print")

    def fake_print_multi(*_a: Any, **_kw: Any) -> None:
        sent.append("print_multi")

    monkeypatch.setattr("app.printer_backends.ptouch_backend.query_preflight", fake_preflight)
    monkeypatch.setattr("app.printer_backends.ptouch_backend._ptouch_print", fake_print)
    monkeypatch.setattr("app.printer_backends.ptouch_backend._ptouch_print_multi", fake_print_multi)
    return sent


def _backend(fake: FakeIppPrinter) -> PTouchBackend:
    return PTouchBackend(host="192.0.2.31", ipp_transport=httpx.ASGITransport(app=fake))


def test_the_captured_bytes_are_ptouchs_raster_stream() -> None:
    data = _ptouch_render(
        [_image()],
        12,
        model_id="PT-P750W",
        auto_cut=True,
        high_resolution=False,
        half_cut=False,
        multi=False,
    )
    # Invalidate (zero bytes) + ESC @ initialise, then the page, ending in print-and-feed.
    assert data.startswith(b"\x00" * 10)
    assert b"\x1b@" in data
    assert data.endswith(b"\x1a")


async def test_a_pt_printer_with_ipp_gets_one_print_job_and_no_9100_send(
    raw_sends: list[str],
) -> None:
    fake = FakeIppPrinter(formats=["application/octet-stream", "image/urf"])
    backend = _backend(fake)

    await backend.print_image(_image(), _spec())

    assert [op.operation for op in fake.received] == ["Get-Printer-Attributes", "Print-Job"]
    job = fake.received[-1]
    assert job.attributes["document-format"] == ["application/octet-stream"]
    assert b"\x1b@" in job.document
    assert raw_sends == []
    assert backend.send_state.labels_sent == 1


async def test_a_pt_batch_over_ipp_is_one_job(raw_sends: list[str]) -> None:
    fake = FakeIppPrinter(formats=["application/octet-stream"])
    backend = _backend(fake)
    await backend.print_images([_image(), _image()], _spec())
    assert [op.operation for op in fake.received].count("Print-Job") == 1
    assert raw_sends == []
    assert backend.send_state.labels_sent == 2


async def test_a_pt_printer_without_ipp_keeps_9100(raw_sends: list[str]) -> None:
    fake = FakeIppPrinter(formats=["application/pdf"])
    backend = _backend(fake)
    await backend.print_image(_image(), _spec())
    await backend.print_images([_image(), _image()], _spec())
    assert raw_sends == ["print", "print_multi"]
    assert backend.send_state.labels_sent == 2
