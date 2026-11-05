"""IPP client over httpx: URI rules, operations, errors and limits.

Most tests drive ``FakeIppPrinter`` through ``httpx.ASGITransport``. Because the
fake uses the same codec as the client, a bug that the encoder and decoder share
would cancel out there; the ``*_request_bytes`` tests therefore compare what the
client sends with hand-assembled bytes from ``fixtures/assemble.py`` (which does
not import the codec) and feed the client hand-assembled responses.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from app.printer_backends.ipp.client import (
    GET_JOBS_LIMIT,
    MAX_RESPONSE_BYTES,
    IppClient,
    JobInfo,
    PrintAccepted,
    to_http_url,
    validate_ipp_uri,
)
from app.printer_backends.ipp.codec import Attr, Collection, Tag, decode
from app.printer_backends.ipp.errors import (
    IppBadResponseError,
    IppBusyError,
    IppDecodeError,
    IppError,
    IppNotFoundError,
    IppResponseTooLargeError,
    IppStatusError,
    IppTransportError,
    IppUnreachableError,
)

from tests.helpers.fake_ipp_printer import FailingTransport, FakeIppPrinter
from tests.unit.printer_backends.ipp.fixtures import assemble as wire

URI = "ipp://printer.example.invalid/ipp/print"
PDF = b"%PDF-1.4\n% synthetic test document\n%%EOF\n"
OP_ATTRS = [
    Attr("job-name", Tag.NAME, ["Calibration page"]),
    Attr("document-format", Tag.MIME, ["application/pdf"]),
]
JOB_ATTRS = [
    Attr(
        "media-col",
        Tag.BEG_COLLECTION,
        [
            Collection(
                {
                    "media-size": [Collection({"x-dimension": [21000], "y-dimension": [29700]})],
                    "media-type": ["labels"],
                    "media-source": ["main-tray"],
                }
            )
        ],
    ),
    Attr("copies", Tag.INTEGER, [1]),
]


def _client(fake: FakeIppPrinter, **kwargs: Any) -> IppClient:
    return IppClient(URI, transport=httpx.ASGITransport(app=fake), **kwargs)


class _Recorder(httpx.AsyncBaseTransport):
    """Answers every request with the next canned response and records the request."""

    def __init__(self, *responses: httpx.Response | Callable[[httpx.Request], httpx.Response]):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []
        self.bodies: list[bytes] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(await request.aread())
        self.requests.append(request)
        nxt = self.responses.pop(0)
        return nxt(request) if callable(nxt) else nxt


class _Raises(httpx.AsyncBaseTransport):
    def __init__(self, exc: type[httpx.RequestError]) -> None:
        self.exc = exc

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise self.exc("synthetic failure", request=request)


class _Body(httpx.AsyncByteStream):
    """A response body that arrives as a stream, as from a real transport.

    (``httpx.Response(content=...)`` is pre-read and cannot be streamed again.)
    """

    def __init__(self, body: bytes) -> None:
        self.body = body

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self.body


def _ipp(body: bytes, **headers: str) -> httpx.Response:
    return httpx.Response(
        200, headers={"content-type": "application/ipp", **headers}, stream=_Body(body)
    )


def _ok_header(request_id: int) -> bytes:
    return bytes([0x01, 0x01]) + wire.u16(0x0000) + wire.i32(request_id)


def _op_group_response() -> bytes:
    return (
        bytes([0x01])
        + wire.attr(0x47, "attributes-charset", b"utf-8")
        + wire.attr(0x48, "attributes-natural-language", b"en")
    )


def _print_job_response(request_id: int, job_id: int = 7) -> bytes:
    return (
        _ok_header(request_id)
        + _op_group_response()
        + bytes([0x02])
        + wire.attr(0x21, "job-id", wire.i32(job_id))
        + wire.attr(0x45, "job-uri", wire.URI + b"/jobs/" + str(job_id).encode())
        + wire.attr(0x23, "job-state", wire.i32(3))
        + wire.attr(0x44, "job-state-reasons", b"none")
        + wire.END_OF_ATTRIBUTES
    )


# --------------------------------------------------------------------------- URI rules


def test_uri_rules() -> None:
    assert to_http_url(URI) == "http://printer.example.invalid:631/ipp/print"
    assert (
        to_http_url("ipps://printer.example.invalid/ipp/print")
        == "https://printer.example.invalid:631/ipp/print"
    )
    assert (
        to_http_url("ipp://printer.example.invalid:8631/ipp/print")
        == "http://printer.example.invalid:8631/ipp/print"
    )
    assert (
        to_http_url("https://printer.example.invalid/ipp/print")
        == "https://printer.example.invalid/ipp/print"
    )
    assert to_http_url("IPP://printer.example.invalid") == "http://printer.example.invalid:631/"
    assert to_http_url("ipp://[2001:db8::1]/ipp/print") == "http://[2001:db8::1]:631/ipp/print"
    for bad in (
        "ftp://printer.example.invalid/ipp/print",
        "ipp://user:pw@printer.example.invalid/ipp/print",
        "ipp://printer.example.invalid/ipp/print#x",
        "ipp:///ipp/print",
    ):
        with pytest.raises(ValueError):
            validate_ipp_uri(bad)


@pytest.mark.parametrize(
    ("uri", "message"),
    [
        ("ftp://printer.example.invalid/p", "IPP URI scheme must be ipp, ipps, http or https"),
        ("printer.example.invalid/p", "IPP URI scheme must be ipp, ipps, http or https"),
        ("ipp://user:pw@printer.example.invalid/p", "IPP URI must not contain user info"),
        ("ipp://user@printer.example.invalid/p", "IPP URI must not contain user info"),
        ("ipp://printer.example.invalid/p#x", "IPP URI must not contain a fragment"),
        ("ipp://printer.example.invalid/p#", "IPP URI must not contain a fragment"),
        ("ipp:///p", "IPP URI must name a host"),
        ("ipp://:631/p", "IPP URI must name a host"),
        ("ipp://printer.example.invalid:99999/p", "IPP URI has an invalid port"),
        ("ipp://printer.example.invalid:x/p", "IPP URI has an invalid port"),
        ("ipp://printer.example.invalid:0/p", "IPP URI has an invalid port"),
        (
            "ipp://printer.example.invalid/p q",
            "IPP URI must not contain spaces or control characters",
        ),
        (
            "ipp://printer.example.invalid/p\n",
            "IPP URI must not contain spaces or control characters",
        ),
        ("", "IPP URI scheme must be ipp, ipps, http or https"),
    ],
)
def test_validate_ipp_uri_messages(uri: str, message: str) -> None:
    with pytest.raises(ValueError) as err:
        validate_ipp_uri(uri)
    assert str(err.value) == message


def test_client_refuses_bad_uri() -> None:
    with pytest.raises(ValueError):
        IppClient("ftp://printer.example.invalid/p")


def test_error_messages_do_not_contain_the_uri() -> None:
    for message in (
        "IPP URI must not contain user info",
        "IPP URI must name a host",
    ):
        assert "example" not in message


# --------------------------------------------------------------------------- operations


async def test_get_printer_attributes() -> None:
    fake = FakeIppPrinter(printer_state=4, reasons=["toner-low-warning"])
    client = _client(fake)
    attrs = await client.get_printer_attributes(
        ["printer-state", "printer-state-reasons", "document-format-supported"]
    )
    await client.aclose()
    assert attrs["printer-state"] == [4]
    assert attrs["printer-state-reasons"] == ["toner-low-warning"]
    assert attrs["document-format-supported"] == ["application/pdf"]
    assert "printer-make-and-model" not in attrs  # the fake honours requested-attributes
    (op,) = fake.received
    assert op.operation == "Get-Printer-Attributes"
    assert op.attributes["attributes-charset"] == ["utf-8"]
    assert op.attributes["attributes-natural-language"] == ["en"]
    assert op.attributes["printer-uri"] == [URI]


async def test_print_job_sends_document_and_attrs() -> None:
    fake = FakeIppPrinter()
    async with _client(fake) as client:
        accepted = await client.print_job(PDF, JOB_ATTRS, OP_ATTRS)
    assert accepted == PrintAccepted(job_id=1, job_uri=URI + "/jobs/1")
    (op,) = fake.received
    assert op.operation == "Print-Job"
    assert op.document == PDF
    assert op.attributes["requesting-user-name"] == ["label-printer-hub"]
    assert op.attributes["job-name"] == ["Calibration page"]
    assert op.attributes["document-format"] == ["application/pdf"]
    assert op.job_attributes["copies"] == [1]
    (media_col,) = op.job_attributes["media-col"]
    assert isinstance(media_col, Collection)
    assert media_col.members["media-type"] == ["labels"]


async def test_print_job_client_owns_the_target_attributes() -> None:
    fake = FakeIppPrinter()
    hostile = [
        Attr("printer-uri", Tag.URI, ["ipp://other.example.invalid/x"]),
        Attr("attributes-charset", Tag.CHARSET, ["us-ascii"]),
        Attr("requesting-user-name", Tag.NAME, ["label-printer-hub"]),
    ]
    async with _client(fake) as client:
        await client.print_job(PDF, [], hostile)
    (op,) = fake.received
    assert op.attributes["printer-uri"] == [URI]
    assert op.attributes["attributes-charset"] == ["utf-8"]
    assert op.attributes["requesting-user-name"] == ["label-printer-hub"]
    assert op.attributes["document-format"] == ["application/pdf"]  # default added

    rec = _Recorder(_ipp(_print_job_response(1)))
    await IppClient(URI, transport=rec).print_job(PDF, [], hostile)
    sent, _ = decode(rec.bodies[0])
    names = [a.name for a in sent.groups[0].attrs]
    assert names == [
        "attributes-charset",
        "attributes-natural-language",
        "printer-uri",
        "requesting-user-name",
        "document-format",
    ]


async def test_get_job_script_progression() -> None:
    fake = FakeIppPrinter()
    async with _client(fake) as client:
        accepted = await client.print_job(PDF, JOB_ATTRS, OP_ATTRS)
        states = [(await client.get_job(accepted.job_id)).state for _ in range(3)]
        last = await client.get_job(accepted.job_id)
    assert states == [3, 5, 9]
    assert last == JobInfo(
        job_id=1, state=9, reasons=["job-completed-successfully"], impressions_completed=1
    )
    ops = [op.operation for op in fake.received]
    assert ops == ["Print-Job", *["Get-Job-Attributes"] * 4]
    get = fake.received[1]
    assert get.attributes["job-id"] == [1]
    assert get.attributes["printer-uri"] == [URI]
    assert get.attributes["requesting-user-name"] == ["label-printer-hub"]


async def test_request_ids_increment_per_client() -> None:
    fake = FakeIppPrinter()
    async with _client(fake) as client:
        await client.get_printer_attributes(["printer-state"])
        await client.get_printer_attributes(["printer-state"])
    async with _client(fake) as other:
        await other.get_printer_attributes(["printer-state"])
    assert [op.request_id for op in fake.received] == [1, 2, 1]


async def test_status_errors() -> None:
    fake = FakeIppPrinter(print_status=0x040A)
    async with _client(fake) as client:
        with pytest.raises(IppStatusError) as err:
            await client.print_job(PDF, JOB_ATTRS, OP_ATTRS)
    assert err.value.status == 0x040A
    assert err.value.name == "client-error-document-format-not-supported"
    assert not isinstance(err.value, IppBusyError | IppNotFoundError)

    fake = FakeIppPrinter(busy=True)
    async with _client(fake) as client:
        with pytest.raises(IppBusyError) as busy:
            await client.print_job(PDF, JOB_ATTRS, OP_ATTRS)
    assert (busy.value.status, busy.value.name) == (0x0507, "server-error-busy")

    fake = FakeIppPrinter()
    async with _client(fake) as client:
        accepted = await client.print_job(PDF, JOB_ATTRS, OP_ATTRS)
        fake.forget_jobs()
        with pytest.raises(IppNotFoundError) as gone:
            await client.get_job(accepted.job_id)
    assert (gone.value.status, gone.value.name) == (0x0406, "client-error-not-found")


async def test_unregistered_status_gets_a_generated_name() -> None:
    body = bytes([0x01, 0x01]) + wire.u16(0x04FF) + wire.i32(1) + wire.END_OF_ATTRIBUTES
    client = IppClient(URI, transport=_Recorder(_ipp(body)))
    with pytest.raises(IppStatusError) as err:
        await client.get_printer_attributes(["printer-state"])
    assert (err.value.status, err.value.name) == (0x04FF, "unknown-status-0x04ff")


async def test_informational_status_is_an_error() -> None:
    body = bytes([0x01, 0x01]) + wire.u16(0x0100) + wire.i32(1) + wire.END_OF_ATTRIBUTES
    client = IppClient(URI, transport=_Recorder(_ipp(body)))
    with pytest.raises(IppStatusError):
        await client.get_printer_attributes(["printer-state"])


async def test_successful_ok_variants_are_success() -> None:
    body = (
        bytes([0x01, 0x01])
        + wire.u16(0x0001)  # successful-ok-ignored-or-substituted-attributes
        + wire.i32(1)
        + _op_group_response()
        + bytes([0x04])
        + wire.attr(0x23, "printer-state", wire.i32(3))
        + wire.END_OF_ATTRIBUTES
    )
    client = IppClient(URI, transport=_Recorder(_ipp(body)))
    assert (await client.get_printer_attributes(["printer-state"]))["printer-state"] == [3]


async def test_get_jobs_sends_limit_and_narrow_attributes() -> None:
    fake = FakeIppPrinter(job_script=[3])
    async with _client(fake) as client:
        for _ in range(3):
            await client.print_job(PDF, [], OP_ATTRS)
        jobs = await client.get_jobs()
        done = await client.get_jobs("completed")
    assert [j.job_id for j in jobs] == [1, 2, 3]
    assert all(j.state == 3 for j in jobs)
    assert done == []
    get_jobs = fake.received[3]
    assert get_jobs.operation == "Get-Jobs"
    assert get_jobs.attributes["limit"] == [GET_JOBS_LIMIT]
    assert get_jobs.attributes["which-jobs"] == ["not-completed"]
    assert get_jobs.attributes["requested-attributes"] == [
        "job-id",
        "job-state",
        "job-state-reasons",
        "job-impressions-completed",
    ]
    assert fake.received[4].attributes["which-jobs"] == ["completed"]


async def test_get_jobs_never_returns_more_than_the_limit() -> None:
    fake = FakeIppPrinter(job_script=[3], ignore_limit=True)
    async with _client(fake) as client:
        for _ in range(GET_JOBS_LIMIT + 5):
            await client.print_job(PDF, [], OP_ATTRS)
        jobs = await client.get_jobs()
    assert len(jobs) == GET_JOBS_LIMIT


async def test_get_jobs_skips_groups_without_id_or_state() -> None:
    body = (
        _ok_header(1)
        + _op_group_response()
        + bytes([0x02])
        + wire.attr(0x21, "job-id", wire.i32(4))
        + wire.attr(0x23, "job-state", wire.i32(5))
        + wire.attr(0x21, "job-impressions-completed", wire.i32(2))
        + bytes([0x02])
        + wire.attr(0x44, "job-state", b"processing")  # wrong type
        + wire.attr(0x21, "job-id", wire.i32(5))
        + bytes([0x02])
        + wire.attr(0x23, "job-state", wire.i32(3))  # no job-id
        + wire.END_OF_ATTRIBUTES
    )
    client = IppClient(URI, transport=_Recorder(_ipp(body)))
    assert await client.get_jobs() == [
        JobInfo(job_id=4, state=5, reasons=[], impressions_completed=2)
    ]


async def test_cancel_job() -> None:
    fake = FakeIppPrinter()
    async with _client(fake) as client:
        accepted = await client.print_job(PDF, [], OP_ATTRS)
        await client.cancel_job(accepted.job_id)
        info = await client.get_job(accepted.job_id)
        with pytest.raises(IppStatusError) as again:
            await client.cancel_job(accepted.job_id)
    assert info.state == 7
    assert again.value.name == "client-error-not-possible"
    cancel = fake.received[1]
    assert cancel.operation == "Cancel-Job"
    assert cancel.attributes["job-id"] == [1]
    assert cancel.attributes["requesting-user-name"] == ["label-printer-hub"]


async def test_validate_job() -> None:
    fake = FakeIppPrinter()
    async with _client(fake) as client:
        await client.validate_job(JOB_ATTRS)
    (op,) = fake.received
    assert op.operation == "Validate-Job"
    assert op.attributes["document-format"] == ["application/pdf"]
    assert op.job_attributes["copies"] == [1]
    assert op.document == b""

    fake = FakeIppPrinter(print_status=0x040B)
    async with _client(fake) as client:
        with pytest.raises(IppStatusError) as err:
            await client.validate_job(JOB_ATTRS)
    assert err.value.name == "client-error-attributes-or-values-not-supported"


async def test_job_info_reasons_are_bounded() -> None:
    reasons = wire.attr(0x44, "job-state-reasons", b"r" * 200) + b"".join(
        wire.more(0x44, b"x%d" % i) for i in range(1, 100)
    )
    body = (
        _ok_header(1)
        + _op_group_response()
        + bytes([0x02])
        + wire.attr(0x21, "job-id", wire.i32(9))
        + wire.attr(0x23, "job-state", wire.i32(5))
        + reasons
        + wire.attr(0x13, "job-impressions-completed", b"")  # no-value
        + wire.END_OF_ATTRIBUTES
    )
    client = IppClient(URI, transport=_Recorder(_ipp(body)))
    info = await client.get_job(9)
    assert len(info.reasons) == 32
    assert info.reasons[0] == "r" * 120
    assert info.impressions_completed is None


async def test_print_job_without_job_id_is_a_bad_response() -> None:
    body = _ok_header(1) + _op_group_response() + wire.END_OF_ATTRIBUTES
    client = IppClient(URI, transport=_Recorder(_ipp(body)))
    with pytest.raises(IppBadResponseError):
        await client.print_job(PDF, [], OP_ATTRS)


async def test_get_job_without_state_is_a_bad_response() -> None:
    body = (
        _ok_header(1)
        + _op_group_response()
        + bytes([0x02])
        + wire.attr(0x21, "job-id", wire.i32(9))
        + wire.END_OF_ATTRIBUTES
    )
    client = IppClient(URI, transport=_Recorder(_ipp(body)))
    with pytest.raises(IppBadResponseError):
        await client.get_job(9)


async def test_overlong_job_uri_is_dropped() -> None:
    body = (
        _ok_header(1)
        + _op_group_response()
        + bytes([0x02])
        + wire.attr(0x21, "job-id", wire.i32(9))
        + wire.attr(0x45, "job-uri", b"ipp://h/" + b"j" * 2000)
        + wire.END_OF_ATTRIBUTES
    )
    client = IppClient(URI, transport=_Recorder(_ipp(body)))
    assert await client.print_job(PDF, [], OP_ATTRS) == PrintAccepted(job_id=9, job_uri=None)


# --------------------------------------------------------------------------- bytes on the wire


async def test_get_printer_attributes_request_bytes() -> None:
    rec = _Recorder(_ipp(wire.gpa_response()))
    client = IppClient(URI, transport=rec)
    attrs = await client.get_printer_attributes(["printer-state", "marker-levels"])
    assert rec.bodies == [wire.gpa_request()]
    assert attrs["printer-state"] == [3]
    assert attrs["marker-levels"] == [80, -3]
    assert attrs["printer-make-and-model"] == ["Example Laser 1000"]
    (req,) = rec.requests
    assert req.method == "POST"
    assert str(req.url) == "http://printer.example.invalid:631/ipp/print"
    assert req.headers["content-type"] == "application/ipp"
    assert req.headers["accept-encoding"] == "identity"


async def test_print_job_request_bytes() -> None:
    rec = _Recorder(_ipp(wire.gpa_response()), _ipp(_print_job_response(2)))
    client = IppClient(URI, transport=rec)
    await client.get_printer_attributes(["printer-state", "marker-levels"])
    accepted = await client.print_job(PDF, JOB_ATTRS, OP_ATTRS)
    assert rec.bodies[1] == wire.print_job_request() + PDF
    assert accepted == PrintAccepted(job_id=7, job_uri=URI + "/jobs/7")


async def test_get_job_request_bytes() -> None:
    response = (
        _ok_header(1)
        + _op_group_response()
        + bytes([0x02])
        + wire.attr(0x21, "job-id", wire.i32(7))
        + wire.attr(0x23, "job-state", wire.i32(6))
        + wire.attr(0x44, "job-state-reasons", b"media-jam")
        + wire.more(0x44, b"job-printing")
        + wire.attr(0x21, "job-impressions-completed", wire.i32(0))
        + wire.END_OF_ATTRIBUTES
    )
    rec = _Recorder(_ipp(response))
    client = IppClient(URI, transport=rec)
    info = await client.get_job(7)
    expected = (
        bytes([0x01, 0x01])
        + wire.u16(0x0009)  # Get-Job-Attributes
        + wire.i32(1)
        + bytes([0x01])
        + wire.attr(0x47, "attributes-charset", b"utf-8")
        + wire.attr(0x48, "attributes-natural-language", b"en")
        + wire.attr(0x45, "printer-uri", wire.URI)
        + wire.attr(0x21, "job-id", wire.i32(7))
        + wire.attr(0x42, "requesting-user-name", b"label-printer-hub")
        + wire.attr(0x44, "requested-attributes", b"job-id")
        + wire.more(0x44, b"job-state")
        + wire.more(0x44, b"job-state-reasons")
        + wire.more(0x44, b"job-impressions-completed")
        + wire.END_OF_ATTRIBUTES
    )
    assert rec.bodies == [expected]
    assert info == JobInfo(
        job_id=7, state=6, reasons=["media-jam", "job-printing"], impressions_completed=0
    )


async def test_cancel_and_get_jobs_request_bytes() -> None:
    ok = _ok_header(1) + _op_group_response() + wire.END_OF_ATTRIBUTES
    ok2 = _ok_header(2) + _op_group_response() + wire.END_OF_ATTRIBUTES
    rec = _Recorder(_ipp(ok), _ipp(ok2))
    client = IppClient(URI, transport=rec)
    await client.cancel_job(7)
    assert await client.get_jobs("completed") == []
    head = (
        bytes([0x01])
        + wire.attr(0x47, "attributes-charset", b"utf-8")
        + wire.attr(0x48, "attributes-natural-language", b"en")
        + wire.attr(0x45, "printer-uri", wire.URI)
    )
    assert rec.bodies[0] == (
        bytes([0x01, 0x01])
        + wire.u16(0x0008)
        + wire.i32(1)
        + head
        + wire.attr(0x21, "job-id", wire.i32(7))
        + wire.attr(0x42, "requesting-user-name", b"label-printer-hub")
        + wire.END_OF_ATTRIBUTES
    )
    assert rec.bodies[1] == (
        bytes([0x01, 0x01])
        + wire.u16(0x000A)
        + wire.i32(2)
        + head
        + wire.attr(0x42, "requesting-user-name", b"label-printer-hub")
        + wire.attr(0x21, "limit", wire.i32(GET_JOBS_LIMIT))
        + wire.attr(0x44, "which-jobs", b"completed")
        + wire.attr(0x44, "requested-attributes", b"job-id")
        + wire.more(0x44, b"job-state")
        + wire.more(0x44, b"job-state-reasons")
        + wire.more(0x44, b"job-impressions-completed")
        + wire.END_OF_ATTRIBUTES
    )


# --------------------------------------------------------------------------- transport failures


@pytest.mark.parametrize("exc", [httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout])
async def test_connect_error_is_unreachable(exc: type[httpx.RequestError]) -> None:
    client = IppClient(URI, transport=_Raises(exc))
    with pytest.raises(IppUnreachableError) as err:
        await client.print_job(PDF, [], OP_ATTRS)
    assert not isinstance(err.value, IppTransportError)
    assert isinstance(err.value.__cause__, exc)


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.ReadError,
        httpx.WriteError,
        httpx.RemoteProtocolError,
        httpx.LocalProtocolError,
    ],
)
async def test_failure_after_start_is_transport_error(exc: type[httpx.RequestError]) -> None:
    client = IppClient(URI, transport=_Raises(exc))
    with pytest.raises(IppTransportError) as err:
        await client.get_job(1)
    assert not isinstance(err.value, IppUnreachableError)


@pytest.mark.parametrize("exc", [httpx.RemoteProtocolError, httpx.ReadTimeout])
async def test_connection_dies_after_the_document(exc: type[httpx.RequestError]) -> None:
    fake = FakeIppPrinter()
    transport = FailingTransport(httpx.ASGITransport(app=fake), "Print-Job", exc)
    async with IppClient(URI, transport=transport) as client:
        attrs = await client.get_printer_attributes(["printer-state"])  # not the failing op
        with pytest.raises(IppTransportError):
            await client.print_job(PDF, JOB_ATTRS, OP_ATTRS)
    assert attrs["printer-state"] == [3]
    assert transport.failed_documents == [PDF]
    assert [op.operation for op in fake.received] == ["Get-Printer-Attributes", "Print-Job"]


async def test_transport_error_message_has_no_uri() -> None:
    client = IppClient(URI, transport=_Raises(httpx.ConnectError))
    with pytest.raises(IppError) as err:
        await client.get_printer_attributes(["printer-state"])
    assert "example" not in str(err.value)


# --------------------------------------------------------------------------- response limits


class _CountingStream(httpx.AsyncByteStream):
    def __init__(self, total: int, chunk: int) -> None:
        self.total = total
        self.chunk = chunk
        self.yielded = 0
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        sent = 0
        while sent < self.total:
            self.yielded += 1
            sent += self.chunk
            yield b"\x00" * self.chunk

    async def aclose(self) -> None:
        self.closed = True


async def test_response_over_1mb_aborted() -> None:
    assert MAX_RESPONSE_BYTES == 1_048_576
    chunk = 64 * 1024
    stream = _CountingStream(2 * 1024 * 1024, chunk)
    response = httpx.Response(200, headers={"content-type": "application/ipp"}, stream=stream)
    client = IppClient(URI, transport=_Recorder(response))
    with pytest.raises(IppResponseTooLargeError):
        await client.get_printer_attributes(["printer-state"])
    assert stream.yielded == MAX_RESPONSE_BYTES // chunk + 1
    assert stream.closed


async def test_response_exactly_at_the_cap_is_read() -> None:
    body = wire.gpa_response()
    padded = body + b"\x00" * (MAX_RESPONSE_BYTES - len(body))  # trailing data is ignored
    client = IppClient(URI, transport=_Recorder(_ipp(padded)))
    assert (await client.get_printer_attributes(["printer-state"]))["printer-state"] == [3]


async def test_declared_length_over_the_cap_is_refused_before_reading() -> None:
    stream = _CountingStream(2 * 1024 * 1024, 64 * 1024)
    response = httpx.Response(
        200,
        headers={"content-type": "application/ipp", "content-length": str(2 * 1024 * 1024)},
        stream=stream,
    )
    client = IppClient(URI, transport=_Recorder(response))
    with pytest.raises(IppResponseTooLargeError):
        await client.get_printer_attributes(["printer-state"])
    assert stream.yielded == 0


async def test_bad_content_type() -> None:
    html = httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html></html>")
    client = IppClient(URI, transport=_Recorder(html))
    with pytest.raises(IppBadResponseError):
        await client.get_printer_attributes(["printer-state"])


async def test_content_type_parameters_are_accepted() -> None:
    response = _ipp(wire.gpa_response(), **{"content-type": "Application/IPP; charset=utf-8"})
    client = IppClient(URI, transport=_Recorder(response))
    assert (await client.get_printer_attributes(["printer-state"]))["printer-state"] == [3]


@pytest.mark.parametrize("status", [204, 400, 401, 404, 500, 503])
async def test_http_status_other_than_200(status: int) -> None:
    response = httpx.Response(status, headers={"content-type": "application/ipp"})
    client = IppClient(URI, transport=_Recorder(response))
    with pytest.raises(IppBadResponseError):
        await client.get_printer_attributes(["printer-state"])


async def test_redirect_is_not_followed() -> None:
    redirect = httpx.Response(302, headers={"location": "http://elsewhere.example.invalid/x"})
    rec = _Recorder(redirect, _ipp(wire.gpa_response()))
    client = IppClient(URI, transport=rec)
    with pytest.raises(IppBadResponseError):
        await client.get_printer_attributes(["printer-state"])
    assert len(rec.requests) == 1


async def test_compressed_response_is_refused() -> None:
    response = _ipp(b"\x1f\x8b" + b"\x00" * 20, **{"content-encoding": "gzip"})
    client = IppClient(URI, transport=_Recorder(response))
    with pytest.raises(IppBadResponseError):
        await client.get_printer_attributes(["printer-state"])


async def test_malformed_response_is_a_decode_error() -> None:
    client = IppClient(URI, transport=_Recorder(_ipp(b"\x01\x01\x00")))
    with pytest.raises(IppDecodeError):
        await client.get_printer_attributes(["printer-state"])


# --------------------------------------------------------------------------- timeouts, HTTP client


async def test_timeouts_passed() -> None:
    rec = _Recorder(
        _ipp(wire.gpa_response()),
        _ipp(_print_job_response(2)),
        _ipp(_print_job_response(3)),
    )
    client = IppClient(URI, query_timeout_s=2, upload_timeout_s=30, transport=rec)
    await client.get_printer_attributes(["printer-state"])
    await client.print_job(PDF, [], OP_ATTRS)
    await client.get_job(7)
    query, upload, job = (r.extensions["timeout"] for r in rec.requests)
    assert query["read"] == query["write"] == query["pool"] == 2
    assert upload["read"] == upload["write"] == upload["pool"] == 30
    assert job["read"] == 2
    # The connect phase gets a share of the budget, so a connect timeout is reported
    # (as unreachable) before the overall deadline of the request fires.
    assert 0 < query["connect"] < 2
    assert 0 < upload["connect"] <= 5


async def test_whole_request_is_bounded_by_the_timeout() -> None:
    class _Drip(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            for _ in range(100):
                yield b"\x00"
                await asyncio.sleep(0.05)

    response = httpx.Response(200, headers={"content-type": "application/ipp"}, stream=_Drip())
    client = IppClient(URI, query_timeout_s=0.2, transport=_Recorder(response))
    started = time.monotonic()
    with pytest.raises(IppTransportError):
        await client.get_printer_attributes(["printer-state"])
    assert time.monotonic() - started < 1.5


def test_http_client_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, Any]] = []
    real = httpx.AsyncClient

    def spy(**kwargs: Any) -> httpx.AsyncClient:
        seen.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", spy)
    IppClient("ipps://printer.example.invalid/ipp/print")
    IppClient("ipps://printer.example.invalid/ipp/print", tls_verify=False)
    assert [s["verify"] for s in seen] == [True, False]
    assert all(s["follow_redirects"] is False for s in seen)
    assert all(s.get("trust_env") is False for s in seen)


async def test_aclose_closes_the_http_client() -> None:
    client = _client(FakeIppPrinter())
    await client.aclose()
    with pytest.raises(RuntimeError):
        await client.get_printer_attributes(["printer-state"])


async def test_request_body_decodes_as_the_operation() -> None:
    rec = _Recorder(_ipp(wire.gpa_response()))
    client = IppClient(URI, transport=rec)
    await client.get_printer_attributes(["printer-state"])
    msg, document = decode(rec.bodies[0])
    assert msg.code == 0x000B
    assert document == b""
