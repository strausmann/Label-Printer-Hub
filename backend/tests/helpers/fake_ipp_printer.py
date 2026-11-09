"""A scriptable IPP printer for tests (and, through ``serve_on_loopback``, browser tests).

Test-only: production code never imports this module (a guard test in
``tests/unit/helpers/test_fake_ipp_printer.py`` walks ``app/`` for imports of
``tests``). The explicit hook for end-to-end runs is ``serve_on_loopback``.

``FakeIppPrinter`` is an ASGI app speaking IPP over HTTP with the hub's codec. It
answers only from its own scripted values and never re-encodes what it received:
decoded text is lossy for invalid UTF-8 and foreign languages (see the codec
docstring), so echoing it would make the fake fail where a printer would not.
Everything received is recorded in ``received`` as decoded attributes plus the
document bytes.

Because the fake shares the codec with the client, an encoder/decoder bug that is
symmetric would pass here unnoticed; hand-assembled byte fixtures in the tests and
the interoperability spike (Task 3) cover that.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass, field
from typing import Any

import httpx
import uvicorn
from app.printer_backends.ipp.codec import (
    OPERATIONS,
    Attr,
    Collection,
    Group,
    Message,
    Resolution,
    Tag,
    Value,
    decode,
    encode,
)
from app.printer_backends.ipp.errors import IppDecodeError

FAKE_URI = "ipp://printer.example.invalid/ipp/print"
_OPERATION_NAMES = {code: name for name, code in OPERATIONS.items()}
_ALL_GROUPS = {"all", "printer-description", "job-template"}
_NOT_COMPLETED = {3, 4, 5, 6}
_COMPLETED = {7, 8, 9}
_REQUEST_CAP = 64 * 1024 * 1024

ASGIScope = MutableMapping[str, Any]
ASGIReceive = Callable[[], Awaitable[MutableMapping[str, Any]]]
ASGISend = Callable[[MutableMapping[str, Any]], Awaitable[None]]


@dataclass
class ReceivedOp:
    """One request as the fake decoded it."""

    operation: str  # "Print-Job", ... or "0x0010" for an operation the fake does not know
    request_id: int
    attributes: dict[str, list[Value]]  # operation group
    job_attributes: dict[str, list[Value]]  # job group
    document: bytes


@dataclass
class _Job:
    job_id: int
    step: int = 0
    final: int | None = None  # 7 after Cancel-Job
    stopping: int = 0  # polls left that report processing-to-stop-point after Cancel-Job
    name: str | None = None  # job-name as received
    user: str | None = None  # requesting-user-name as received (reported as originating user)


def _echoable(value: object) -> str | None:
    """Text the fake may report back: short and cleanly decoded (it never echoes lossy text)."""
    if isinstance(value, str) and len(value) <= 255 and "\ufffd" not in value:
        return value
    return None


def _media_size(x: int, y: int) -> Collection:
    return Collection({"x-dimension": [x], "y-dimension": [y]})


@dataclass
class FakeIppPrinter:
    """Scriptable IPP printer. Change fields between calls to change its answers."""

    printer_state: int = 3
    reasons: list[str] = field(default_factory=lambda: ["none"])
    markers: list[dict[str, Any]] = field(default_factory=list)
    """Each marker: ``name`` and optional ``color``, ``level``, ``low_level``, ``type``."""
    media_sources: list[str] = field(default_factory=list)
    formats: list[str] = field(default_factory=lambda: ["application/pdf"])
    job_creation_attributes: list[str] = field(
        default_factory=lambda: [
            "media-col",
            "print-scaling",
            "print-color-mode",
            "copies",
            "sides",
        ]
    )
    media_col_members: list[str] = field(
        default_factory=lambda: ["media-size", "media-type", "media-source"]
    )
    accepting_jobs: bool = True
    scaling_supported: bool = True
    margins_hmm: int = 423
    media_default: str | None = None
    """``media-default`` (a media keyword such as ``iso_a4_210x297mm``); ``None``: not reported."""
    resolutions: list[int] = field(default_factory=lambda: [600])
    job_script: list[int] = field(default_factory=lambda: [3, 5, 9])
    """Job states returned by successive Get-Job-Attributes; the last one sticks."""
    impressions_script: list[int] | None = None
    """``job-impressions-completed`` per step like ``job_script``.

    ``None``: 1 in state 9, else 0."""
    cancel_steps: int = 0
    """Cancel-Job is asynchronous on real printers (spike S2): after it, this many polls report
    ``processing`` with ``processing-to-stop-point`` before ``canceled``."""
    print_status: int = 0
    """Status answered to Print-Job and Validate-Job (0 = accept; a successful-ok-* status such
    as 0x0001 accepts the job and answers that status)."""
    busy: bool = False
    """Answer ``server-error-busy`` to Print-Job and Validate-Job."""
    fail_get_job_with: int | None = None
    ignore_limit: bool = False
    """Return every job from Get-Jobs regardless of ``limit`` (a non-conforming printer)."""
    received: list[ReceivedOp] = field(default_factory=list)
    _jobs: dict[int, _Job] = field(default_factory=dict, repr=False)
    _next_job_id: int = field(default=1, repr=False)

    # ------------------------------------------------------------------ script

    def reuse_job_id_for_foreign_job(
        self, job_id: int, *, name: str = "Someone else's document", user: str = "other-client"
    ) -> None:
        """The printer rebooted and gave ``job_id`` to another client's job (ids are reused)."""
        self._jobs.clear()
        self._jobs[job_id] = _Job(job_id, name=name, user=user)
        self._next_job_id = max(self._next_job_id, job_id + 1)

    def forget_jobs(self) -> None:
        """The printer rebooted: it no longer knows any job (ids are not reused)."""
        self._jobs.clear()

    def advance(self) -> None:
        """Move every job one step along ``job_script`` without a query."""
        for job in self._jobs.values():
            job.step += 1

    # ------------------------------------------------------------------ ASGI

    async def __call__(self, scope: ASGIScope, receive: ASGIReceive, send: ASGISend) -> None:
        if scope["type"] == "lifespan":  # pragma: no cover - uvicorn runs with lifespan off
            return
        if scope["type"] != "http":  # pragma: no cover - only HTTP is served
            return
        if scope["method"] != "POST":
            await self._reply(send, 405, b"", "text/plain")
            return
        body = bytearray()
        while True:
            event = await receive()
            body += event.get("body", b"")
            if len(body) > _REQUEST_CAP:  # pragma: no cover - tests send small bodies
                await self._reply(send, 413, b"", "text/plain")
                return
            if not event.get("more_body", False):
                break
        await self._reply(send, 200, self.handle(bytes(body)), "application/ipp")

    @staticmethod
    async def _reply(send: ASGISend, status: int, body: bytes, content_type: str) -> None:
        headers = [(b"content-type", content_type.encode()), (b"content-length", b"%d" % len(body))]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    # ------------------------------------------------------------------ IPP

    def handle(self, body: bytes) -> bytes:
        """Answer one IPP request (bytes in, bytes out)."""
        try:
            request, document = decode(body)
        except IppDecodeError:
            return self._response(0x0400, 0)
        ops = request.attrs(Tag.OPERATION)
        name = _OPERATION_NAMES.get(request.code, f"0x{request.code:04x}")
        self.received.append(
            ReceivedOp(name, request.request_id, ops, request.attrs(Tag.JOB), document)
        )
        handler = {
            "Get-Printer-Attributes": self._get_printer_attributes,
            "Print-Job": self._print_job,
            "Validate-Job": self._validate_job,
            "Get-Job-Attributes": self._get_job,
            "Get-Jobs": self._get_jobs,
            "Cancel-Job": self._cancel_job,
        }.get(name)
        if handler is None:
            return self._response(0x0501, request.request_id)
        status, groups = handler(ops)
        return self._response(status, request.request_id, groups)

    @staticmethod
    def _response(status: int, request_id: int, groups: list[Group] | None = None) -> bytes:
        head = Group(
            Tag.OPERATION,
            [
                Attr("attributes-charset", Tag.CHARSET, ["utf-8"]),
                Attr("attributes-natural-language", Tag.LANGUAGE, ["en"]),
            ],
        )
        return encode(Message((1, 1), status, request_id, [head, *(groups or [])]))

    def _printer_attributes(self) -> list[Attr]:
        scaling: list[Value] = ["auto", "fit", "fill"]
        if self.scaling_supported:
            scaling.append("none")
        attrs = [
            Attr("printer-uri-supported", Tag.URI, [FAKE_URI]),
            Attr("printer-make-and-model", Tag.TEXT, ["Fake IPP Printer"]),
            Attr("ipp-versions-supported", Tag.KEYWORD, ["1.1", "2.0"]),
            Attr("printer-state", Tag.ENUM, [self.printer_state]),
            Attr("printer-state-reasons", Tag.KEYWORD, list(self.reasons) or ["none"]),
            Attr("printer-is-accepting-jobs", Tag.BOOLEAN, [self.accepting_jobs]),
            Attr("queued-job-count", Tag.INTEGER, [self._count(_NOT_COMPLETED)]),
            Attr("document-format-supported", Tag.MIME, list(self.formats)),
            Attr(
                "job-creation-attributes-supported", Tag.KEYWORD, list(self.job_creation_attributes)
            ),
            Attr("media-col-supported", Tag.KEYWORD, list(self.media_col_members)),
            Attr("media-supported", Tag.KEYWORD, ["iso_a4_210x297mm", "na_letter_8.5x11in"]),
            Attr("media-default", Tag.KEYWORD, [self.media_default] if self.media_default else []),
            Attr(
                "media-size-supported",
                Tag.BEG_COLLECTION,
                [_media_size(21000, 29700), _media_size(21590, 27940)],
            ),
            Attr("media-type-supported", Tag.KEYWORD, ["stationery", "labels"]),
            Attr("media-source-supported", Tag.KEYWORD, list(self.media_sources)),
            Attr(
                "printer-resolution-supported",
                Tag.RESOLUTION,
                [Resolution(r, r, 3) for r in self.resolutions],
            ),
            Attr("print-scaling-supported", Tag.KEYWORD, scaling),
            Attr("print-color-mode-supported", Tag.KEYWORD, ["monochrome"]),
            Attr("sides-supported", Tag.KEYWORD, ["one-sided"]),
            *(
                Attr(f"media-{side}-margin-supported", Tag.INTEGER, [self.margins_hmm])
                for side in ("top", "bottom", "left", "right")
            ),
        ]
        for attr_name, key, tag in (
            ("marker-names", "name", Tag.NAME),
            ("marker-colors", "color", Tag.NAME),
            ("marker-levels", "level", Tag.INTEGER),
            ("marker-low-levels", "low_level", Tag.INTEGER),
            ("marker-types", "type", Tag.KEYWORD),
        ):
            values = [m[key] for m in self.markers if key in m]
            attrs.append(Attr(attr_name, tag, values))
        return [a for a in attrs if a.values]  # an empty 1setOf is not sendable

    def _get_printer_attributes(self, ops: dict[str, list[Value]]) -> tuple[int, list[Group]]:
        requested = {v for v in ops.get("requested-attributes", ["all"]) if isinstance(v, str)}
        attrs = self._printer_attributes()
        if not requested & _ALL_GROUPS:
            attrs = [a for a in attrs if a.name in requested]
        return 0, [Group(Tag.PRINTER, attrs)]

    def _submission_status(self, ops: dict[str, list[Value]]) -> int:
        if self.busy:
            return 0x0507
        if not self.accepting_jobs:
            return 0x0506
        if self.print_status:
            return self.print_status
        fmt = next(iter(ops.get("document-format", [])), "application/octet-stream")
        return 0 if fmt in self.formats else 0x040A

    def _print_job(self, ops: dict[str, list[Value]]) -> tuple[int, list[Group]]:
        status = self._submission_status(ops)
        if status > 0x00FF:
            return status, []
        name = next(iter(ops.get("job-name", [])), None)
        user = next(iter(ops.get("requesting-user-name", [])), None)
        job = _Job(
            self._next_job_id,
            name=_echoable(name),
            user=_echoable(user),
        )
        self._next_job_id += 1
        self._jobs[job.job_id] = job
        return status, [Group(Tag.JOB, self._job_attrs(job, include_uri=True))]

    def _validate_job(self, ops: dict[str, list[Value]]) -> tuple[int, list[Group]]:
        return self._submission_status(ops), []

    def _state(self, job: _Job) -> int:
        if job.final is not None:
            return 5 if job.stopping > 0 else job.final
        script = self.job_script or [3]
        return script[min(job.step, len(script) - 1)]

    def _job_attrs(self, job: _Job, *, include_uri: bool = False) -> list[Attr]:
        state = self._state(job)
        reasons = {
            3: "none",
            4: "job-hold-until-specified",
            5: "job-printing",
            6: "printer-stopped",
            7: "job-canceled-by-user",
            8: "aborted-by-system",
            9: "job-completed-successfully",
        }.get(state, "none")
        if job.final is not None and job.stopping > 0:
            reasons = "processing-to-stop-point"
        if self.impressions_script:
            impressions = self.impressions_script[min(job.step, len(self.impressions_script) - 1)]
        else:
            impressions = 1 if state == 9 else 0
        attrs = [
            Attr("job-id", Tag.INTEGER, [job.job_id]),
            Attr("job-state", Tag.ENUM, [state]),
            Attr("job-state-reasons", Tag.KEYWORD, [reasons]),
            Attr("job-impressions-completed", Tag.INTEGER, [impressions]),
        ]
        if job.name is not None:
            attrs.append(Attr("job-name", Tag.NAME, [job.name]))
        if job.user is not None:
            attrs.append(Attr("job-originating-user-name", Tag.NAME, [job.user]))
        if include_uri:
            attrs.insert(1, Attr("job-uri", Tag.URI, [f"{FAKE_URI}/jobs/{job.job_id}"]))
        return attrs

    def _job(self, ops: dict[str, list[Value]]) -> _Job | None:
        job_id = next(iter(ops.get("job-id", [])), None)
        return self._jobs.get(job_id) if isinstance(job_id, int) else None

    def _get_job(self, ops: dict[str, list[Value]]) -> tuple[int, list[Group]]:
        if self.fail_get_job_with is not None:
            return self.fail_get_job_with, []
        job = self._job(ops)
        if job is None:
            return 0x0406, []
        attrs = self._job_attrs(job)
        if job.final is not None and job.stopping > 0:
            job.stopping -= 1
        else:
            job.step += 1
        return 0, [Group(Tag.JOB, attrs)]

    def _count(self, states: set[int]) -> int:
        return sum(1 for job in self._jobs.values() if self._state(job) in states)

    def _get_jobs(self, ops: dict[str, list[Value]]) -> tuple[int, list[Group]]:
        which = next(iter(ops.get("which-jobs", [])), "not-completed")
        wanted = _COMPLETED if which == "completed" else _NOT_COMPLETED
        jobs = [j for j in self._jobs.values() if self._state(j) in wanted]
        limit = next(iter(ops.get("limit", [])), None)
        if isinstance(limit, int) and limit > 0 and not self.ignore_limit:
            jobs = jobs[:limit]
        return 0, [Group(Tag.JOB, self._job_attrs(j)) for j in jobs]

    def _cancel_job(self, ops: dict[str, list[Value]]) -> tuple[int, list[Group]]:
        job = self._job(ops)
        if job is None:
            return 0x0406, []
        if self._state(job) in _COMPLETED:
            return 0x0404, []  # client-error-not-possible
        job.final = 7
        job.stopping = self.cancel_steps
        return 0, []


class FailingTransport(httpx.AsyncBaseTransport):
    """Wraps a transport; the named operation reaches the printer, then the connection dies.

    An ASGI app cannot drop a connection after reading the body, so this models it:
    the request (including the document) is read and handed to ``inner`` (the fake
    records it, as a real printer may have received it), its answer is discarded,
    and ``exc`` is raised instead.
    """

    def __init__(
        self, inner: httpx.AsyncBaseTransport, fail_on: str, exc: type[httpx.RequestError]
    ) -> None:
        self.inner = inner
        self.fail_on = fail_on
        self.exc = exc
        self.failed_documents: list[bytes] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        response = await self.inner.handle_async_request(request)
        try:
            msg, document = decode(body)
        except IppDecodeError:  # pragma: no cover - the client sends well-formed requests
            return response
        if _OPERATION_NAMES.get(msg.code) != self.fail_on:
            return response
        await response.aread()
        await response.aclose()
        self.failed_documents.append(document)
        raise self.exc("connection lost after the request was sent", request=request)

    async def aclose(self) -> None:
        await self.inner.aclose()


async def serve_on_loopback(fake: FakeIppPrinter) -> tuple[str, Callable[[], Awaitable[None]]]:
    """Serve ``fake`` with uvicorn on ``127.0.0.1:<free port>``.

    Returns the ``ipp://`` URI and an async stop function. Startup waits at most
    five seconds.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    config = uvicorn.Config(fake, lifespan="off", log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(5):
            while not server.started:
                if task.done():
                    task.result()  # surfaces the startup error
                await asyncio.sleep(0.01)
    except BaseException:
        server.should_exit = True
        with contextlib.suppress(BaseException):
            await asyncio.wait_for(task, 5)
        sock.close()
        raise

    async def stop() -> None:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, 5)
        finally:
            sock.close()

    return f"ipp://127.0.0.1:{port}/ipp/print", stop


_UNSENT = (httpx.ConnectError, httpx.ConnectTimeout)


class FlakyTransport(httpx.AsyncBaseTransport):
    """Wraps a transport; the next calls of an operation fail with the scripted exceptions.

    ``plan`` maps an operation name to the exceptions its next calls raise, one per call,
    then the operation works again. A connect error is raised **before** the request reaches
    ``inner`` (nothing was sent, as with a printer that is switched off); any other error is
    raised after ``inner`` has seen the request (as ``FailingTransport`` does).
    """

    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        plan: dict[str, list[type[httpx.RequestError]]],
    ) -> None:
        self.inner = inner
        self.plan = {op: list(excs) for op, excs in plan.items()}
        self.failures: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        try:
            msg, _ = decode(body)
            name = _OPERATION_NAMES.get(msg.code, "")
        except IppDecodeError:  # pragma: no cover - the client sends well-formed requests
            name = ""
        pending = self.plan.get(name)
        if not pending:
            return await self.inner.handle_async_request(request)
        exc = pending.pop(0)
        self.failures.append(name)
        if issubclass(exc, _UNSENT):
            raise exc("printer not reachable", request=request)
        response = await self.inner.handle_async_request(request)
        await response.aread()
        await response.aclose()
        raise exc("connection lost after the request was sent", request=request)

    async def aclose(self) -> None:
        await self.inner.aclose()
