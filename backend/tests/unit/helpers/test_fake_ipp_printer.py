"""The scriptable fake IPP printer used by client, runner and browser tests.

Some requests here are hand-assembled bytes (``fixtures/assemble.py``, which does
not import the codec) and some response checks read raw bytes, so the fake is
not only ever checked through the codec it is built on.
"""

from __future__ import annotations

import ast
from pathlib import Path

import httpx
import pytest
from app.printer_backends.ipp.client import IppClient
from app.printer_backends.ipp.codec import Attr, Collection, Resolution, Tag, decode
from app.printer_backends.ipp.errors import IppStatusError, IppTransportError

from tests.helpers.fake_ipp_printer import (
    FailingTransport,
    FakeIppPrinter,
    serve_on_loopback,
)
from tests.unit.printer_backends.ipp.fixtures import assemble as wire

URI = "ipp://printer.example.invalid/ipp/print"
PDF = b"%PDF-1.4\n%%EOF\n"
OP = [Attr("document-format", Tag.MIME, ["application/pdf"])]
APP_DIR = Path(__file__).resolve().parents[3] / "app"


def _http(fake: FakeIppPrinter) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fake), base_url="http://printer.example.invalid:631"
    )


def _client(fake: FakeIppPrinter) -> IppClient:
    return IppClient(URI, transport=httpx.ASGITransport(app=fake))


async def test_hand_built_request_gets_a_well_formed_answer() -> None:
    fake = FakeIppPrinter(markers=[{"name": "black", "level": 80}])
    async with _http(fake) as http:
        response = await http.post(
            "/ipp/print",
            content=wire.gpa_request(),
            headers={"content-type": "application/ipp"},
        )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/ipp"
    raw = response.content
    # version 1.1, successful-ok, request-id 1 echoed (RFC 8010 3.1.1), read as raw bytes
    assert raw[:8] == bytes([0x01, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01])
    assert raw[8] == 0x01  # operation-attributes-tag first
    assert raw[9 : 9 + len(wire.attr(0x47, "attributes-charset", b"utf-8"))] == wire.attr(
        0x47, "attributes-charset", b"utf-8"
    )
    assert wire.attr(0x23, "printer-state", wire.i32(3)) in raw
    assert wire.attr(0x21, "marker-levels", wire.i32(80)) in raw
    assert raw.endswith(wire.END_OF_ATTRIBUTES)
    msg, _ = decode(raw)
    assert set(msg.attrs(Tag.PRINTER)) == {"printer-state", "marker-levels"}
    (op,) = fake.received
    assert op.operation == "Get-Printer-Attributes"
    assert op.attributes["requested-attributes"] == ["printer-state", "marker-levels"]


async def test_hand_built_print_job_is_recorded() -> None:
    fake = FakeIppPrinter()
    async with _http(fake) as http:
        response = await http.post(
            "/ipp/print",
            content=wire.print_job_request() + PDF,
            headers={"content-type": "application/ipp"},
        )
    raw = response.content
    assert raw[:8] == bytes([0x01, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x02])
    assert wire.attr(0x21, "job-id", wire.i32(1)) in raw
    (op,) = fake.received
    assert op.document == PDF
    assert op.attributes["job-name"] == ["Calibration page"]
    (media_col,) = op.job_attributes["media-col"]
    assert isinstance(media_col, Collection)
    assert media_col.members["media-source"] == ["main-tray"]


async def test_full_attribute_set_reflects_the_script() -> None:
    fake = FakeIppPrinter(
        printer_state=5,
        reasons=["media-jam-error", "toner-low-warning"],
        markers=[
            {"name": "black", "color": "#000000", "level": 0, "low_level": 10, "type": "toner"}
        ],
        media_sources=["main-tray", "manual"],
        accepting_jobs=False,
        scaling_supported=False,
        margins_hmm=500,
        resolutions=[600, 1200],
    )
    async with _client(fake) as client:
        attrs = await client.get_printer_attributes(["all"])
    assert attrs["printer-state"] == [5]
    assert attrs["printer-state-reasons"] == ["media-jam-error", "toner-low-warning"]
    assert attrs["printer-is-accepting-jobs"] == [False]
    assert attrs["marker-names"] == ["black"]
    assert attrs["marker-colors"] == ["#000000"]
    assert attrs["marker-levels"] == [0]
    assert attrs["marker-low-levels"] == [10]
    assert attrs["marker-types"] == ["toner"]
    assert attrs["media-source-supported"] == ["main-tray", "manual"]
    assert "none" not in attrs["print-scaling-supported"]
    assert attrs["media-top-margin-supported"] == [500]
    assert attrs["printer-resolution-supported"] == [
        Resolution(600, 600, 3),
        Resolution(1200, 1200, 3),
    ]
    assert attrs["job-creation-attributes-supported"] == [
        "media-col",
        "print-scaling",
        "print-color-mode",
        "copies",
        "sides",
    ]
    assert attrs["media-col-supported"] == ["media-size", "media-type", "media-source"]
    assert attrs["document-format-supported"] == ["application/pdf"]


async def test_defaults() -> None:
    fake = FakeIppPrinter()
    async with _client(fake) as client:
        attrs = await client.get_printer_attributes(["all"])
    assert attrs["printer-state"] == [3]
    assert attrs["printer-state-reasons"] == ["none"]
    assert attrs["printer-is-accepting-jobs"] == [True]
    assert "none" in attrs["print-scaling-supported"]
    assert attrs["media-left-margin-supported"] == [423]
    assert attrs["printer-resolution-supported"] == [Resolution(600, 600, 3)]
    assert "marker-names" not in attrs
    assert "media-source-supported" not in attrs


async def test_empty_lists_are_omitted_not_sent_empty() -> None:
    fake = FakeIppPrinter(job_creation_attributes=[], media_col_members=[], formats=[])
    async with _client(fake) as client:
        attrs = await client.get_printer_attributes(["all"])
    assert "job-creation-attributes-supported" not in attrs
    assert "media-col-supported" not in attrs
    assert "document-format-supported" not in attrs


async def test_requested_attribute_groups_mean_everything() -> None:
    fake = FakeIppPrinter()
    async with _client(fake) as client:
        described = await client.get_printer_attributes(["printer-description"])
        narrow = await client.get_printer_attributes(["printer-state", "no-such-attribute"])
    assert "printer-make-and-model" in described
    assert set(narrow) == {"printer-state"}


async def test_not_accepting_jobs_refuses_print_job() -> None:
    fake = FakeIppPrinter(accepting_jobs=False)
    async with _client(fake) as client:
        with pytest.raises(IppStatusError) as err:
            await client.print_job(PDF, [], OP)
    assert err.value.name == "server-error-not-accepting-jobs"


async def test_unsupported_document_format_is_refused() -> None:
    fake = FakeIppPrinter(formats=["image/urf"])
    async with _client(fake) as client:
        with pytest.raises(IppStatusError) as err:
            await client.print_job(PDF, [], OP)
    assert err.value.name == "client-error-document-format-not-supported"


async def test_advance_moves_every_job_one_step() -> None:
    fake = FakeIppPrinter(job_script=[3, 5, 9])
    async with _client(fake) as client:
        job = await client.print_job(PDF, [], OP)
        fake.advance()
        fake.advance()
        assert (await client.get_job(job.job_id)).state == 9
        fake.advance()  # past the end stays at the last state
        assert (await client.get_job(job.job_id)).state == 9


async def test_impressions_follow_the_state() -> None:
    fake = FakeIppPrinter(job_script=[5, 9])
    async with _client(fake) as client:
        job = await client.print_job(PDF, [], OP)
        processing = await client.get_job(job.job_id)
        done = await client.get_job(job.job_id)
    assert (processing.state, processing.impressions_completed) == (5, 0)
    assert (done.state, done.impressions_completed) == (9, 1)


async def test_fail_get_job_with() -> None:
    fake = FakeIppPrinter(fail_get_job_with=0x0502)
    async with _client(fake) as client:
        job = await client.print_job(PDF, [], OP)
        with pytest.raises(IppStatusError) as err:
            await client.get_job(job.job_id)
        fake.fail_get_job_with = None
        assert (await client.get_job(job.job_id)).state == 3
    assert err.value.name == "server-error-service-unavailable"


async def test_forget_jobs_and_get_jobs() -> None:
    fake = FakeIppPrinter(job_script=[3, 9])
    async with _client(fake) as client:
        first = await client.print_job(PDF, [], OP)
        await client.print_job(PDF, [], OP)
        await client.get_job(first.job_id)
        await client.get_job(first.job_id)  # first is now completed
        pending = await client.get_jobs()
        completed = await client.get_jobs("completed")
        fake.forget_jobs()
        after_reboot = await client.get_jobs()
        third = await client.print_job(PDF, [], OP)
    assert [j.job_id for j in pending] == [2]
    assert [j.job_id for j in completed] == [1]
    assert after_reboot == []
    assert third.job_id == 3  # ids are not reused after a reboot


async def test_get_jobs_honours_limit() -> None:
    fake = FakeIppPrinter(job_script=[3])
    async with _client(fake) as client:
        for _ in range(5):
            await client.print_job(PDF, [], OP)
    msg_bytes = (
        bytes([0x01, 0x01])
        + wire.u16(0x000A)
        + wire.i32(9)
        + bytes([0x01])
        + wire.attr(0x47, "attributes-charset", b"utf-8")
        + wire.attr(0x48, "attributes-natural-language", b"en")
        + wire.attr(0x45, "printer-uri", wire.URI)
        + wire.attr(0x21, "limit", wire.i32(2))
        + wire.END_OF_ATTRIBUTES
    )
    async with _http(fake) as http:
        response = await http.post("/ipp/print", content=msg_bytes)
    msg, _ = decode(response.content)
    assert sum(1 for g in msg.groups if g.tag == Tag.JOB) == 2


async def test_unsupported_operation_and_bad_requests() -> None:
    fake = FakeIppPrinter()
    unknown_op = (
        bytes([0x01, 0x01])
        + wire.u16(0x0010)
        + wire.i32(4)
        + bytes([0x01])
        + wire.END_OF_ATTRIBUTES
    )
    async with _http(fake) as http:
        unsupported = await http.post("/ipp/print", content=unknown_op)
        garbage = await http.post("/ipp/print", content=b"\x01\x01\x00")
        get = await http.get("/ipp/print")
    assert unsupported.status_code == 200
    assert unsupported.content[2:4] == wire.u16(0x0501)  # server-error-operation-not-supported
    assert unsupported.content[4:8] == wire.i32(4)
    assert garbage.status_code == 200
    assert garbage.content[2:4] == wire.u16(0x0400)  # client-error-bad-request
    assert get.status_code == 405
    assert [op.operation for op in fake.received] == ["0x0010"]


async def test_fake_never_echoes_received_text() -> None:
    # A job-name with invalid UTF-8 and a foreign language must not break the fake:
    # it answers from its own values and only records what it decoded.
    request = (
        bytes([0x01, 0x01])
        + wire.u16(0x0002)
        + wire.i32(3)
        + bytes([0x01])
        + wire.attr(0x47, "attributes-charset", b"utf-8")
        + wire.attr(0x48, "attributes-natural-language", b"en")
        + wire.attr(0x45, "printer-uri", wire.URI)
        + wire.attr(0x36, "job-name", wire.with_language(b"de", b"\xff" * 20000))
        + wire.attr(0x49, "document-format", b"application/pdf")
        + wire.END_OF_ATTRIBUTES
    )
    fake = FakeIppPrinter()
    async with _http(fake) as http:
        response = await http.post("/ipp/print", content=request + PDF)
    assert response.content[2:4] == wire.u16(0x0000)
    (op,) = fake.received
    assert op.attributes["job-name"] == ["�" * 20000]
    assert op.document == PDF


async def test_failing_transport_passes_other_operations() -> None:
    fake = FakeIppPrinter()
    transport = FailingTransport(httpx.ASGITransport(app=fake), "Cancel-Job", httpx.ReadTimeout)
    async with IppClient(URI, transport=transport) as client:
        job = await client.print_job(PDF, [], OP)
        assert transport.failed_documents == []
        with pytest.raises(IppTransportError):
            await client.cancel_job(job.job_id)
    assert transport.failed_documents == [b""]
    assert [op.operation for op in fake.received] == ["Print-Job", "Cancel-Job"]


async def test_serve_on_loopback() -> None:
    fake = FakeIppPrinter(printer_state=4)
    uri, stop = await serve_on_loopback(fake)
    try:
        assert uri.startswith("ipp://127.0.0.1:")
        assert uri.endswith("/ipp/print")
        async with IppClient(uri) as client:
            attrs = await client.get_printer_attributes(["printer-state"])
            job = await client.print_job(PDF, [], OP)
    finally:
        await stop()
    assert attrs["printer-state"] == [4]
    assert job.job_id == 1
    assert fake.received[-1].document == PDF
    with pytest.raises(httpx.ConnectError):
        async with httpx.AsyncClient(trust_env=False) as http:
            await http.get(uri.replace("ipp://", "http://"))


def test_production_code_never_imports_the_test_helpers() -> None:
    offenders: list[str] = []
    for path in APP_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            offenders += [f"{path}: {n}" for n in names if n == "tests" or n.startswith("tests.")]
    assert offenders == []
