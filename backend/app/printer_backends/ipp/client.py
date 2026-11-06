"""The hub's own IPP client over httpx (spec 11.2): five operations plus Validate-Job.

One ``httpx.AsyncClient`` per ``IppClient``. The printer is a device the admin
configured, but its answers are still untrusted input, so every exchange is
bounded:

* **Size.** The response body is read as raw bytes while streaming and the read
  is aborted once it exceeds ``MAX_RESPONSE_BYTES`` (1 MB); a declared
  ``Content-Length`` above the cap is refused before reading. The hub asks for
  ``Accept-Encoding: identity`` and refuses any encoded body, so no decompression
  can blow the cap up.
* **Time.** Each request is bounded as a whole by its timeout (queries
  ``query_timeout_s``, Print-Job ``upload_timeout_s``; the caller derives both
  from the printer's ``queue_timeout_s``, OC-41). The same value is httpx's read,
  write and pool timeout; the connect phase gets ``CONNECT_SHARE`` of it (at most
  ``MAX_CONNECT_TIMEOUT_S``), so a connect timeout is reported as unreachable
  before the overall deadline fires. httpx applies the connect timeout twice for
  ``ipps``/``https`` (TCP connect including DNS, then the TLS handshake), so the
  share is below one half: both phases together stay under the deadline. The
  remaining limit is deliberate: a connect that is slow in both phases *and* then
  stalls on writing can still hit the deadline before any request byte left, and
  is then reported as ``IppTransportError`` ("may have reached the printer") —
  the safe side for the queue, which then treats the cells as unconfirmed.
* **Connections** are not kept alive between requests. An idle pooled connection
  that the printer closes just as the next request is written would fail as
  ``IppTransportError`` and turn a harmless race (pre-flight read, then
  Print-Job) into an interrupted job. One TCP (and TLS) setup per request on a
  local network is cheap at the hub's polling rate.
* **Redirects** are never followed (``follow_redirects=False``): a 3xx is a bad
  response, so a printer cannot send the hub to another host. Proxy settings
  from the environment are ignored (``trust_env=False``): the printer is on the
  local network.
* **TLS** verification is on unless the admin switched it off for the printer
  (OC-17).

Errors are typed (``errors.py``). Whether bytes may have reached the printer is
the distinction the queue needs: ``IppUnreachableError`` means no,
``IppTransportError`` means maybe.

Logging: DEBUG only, operation and IPP status; never the URI (logs name the
printer by slug, which the caller knows), never attribute values or the
document.

The response's request-id is not compared with the request's: one request per
HTTP exchange already pairs them, and some devices are known to get the echo
wrong.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Self
from urllib.parse import urlsplit

import httpx

from app.printer_backends.ipp.codec import (
    OPERATIONS,
    STATUS_NAMES,
    Attr,
    Group,
    Message,
    Tag,
    Value,
    decode,
    encode,
)
from app.printer_backends.ipp.errors import (
    IppBadResponseError,
    IppBusyError,
    IppNotFoundError,
    IppResponseTooLargeError,
    IppStatusError,
    IppTransportError,
    IppUnreachableError,
)

logger = logging.getLogger(__name__)

MAX_RESPONSE_BYTES = 1_048_576
"""Response body cap (spec 11.2): streamed, aborted beyond."""

GET_JOBS_LIMIT = 100
"""``limit`` sent with Get-Jobs, and the most jobs ``get_jobs`` returns.

Keeps a long job history far below the codec's group cap (``MAX_GROUPS``), so a
busy printer cannot turn a job count into a decode error.
"""

CONNECT_SHARE = 0.45
"""Share of a request's timeout for each connect phase (TCP, TLS); 2 x 0.45 < 1."""
MAX_CONNECT_TIMEOUT_S = 5.0
IPP_VERSION = (1, 1)
"""IPP/1.1 is understood by every IPP printer; nothing the hub sends needs 2.0."""

USER_NAME = "label-printer-hub"
MAX_REASONS = 32
MAX_REASON_LENGTH = 120
MAX_JOB_URI_LENGTH = 1023
JOB_ATTRIBUTES = ("job-id", "job-state", "job-state-reasons", "job-impressions-completed")

_SCHEMES = {"ipp": "http", "ipps": "https", "http": "http", "https": "https"}
_DEFAULT_IPP_PORT = 631
_OWNED_OPERATION_ATTRIBUTES = {"attributes-charset", "attributes-natural-language", "printer-uri"}
_SUCCESS_MAX = 0x00FF
_SUBSTITUTED_STATUSES = frozenset({0x0001, 0x0002})
_NOT_FOUND = 0x0406
_BUSY = 0x0507

# ---------------------------------------------------------------------------- URIs


def validate_ipp_uri(uri: str) -> None:
    """Raise ``ValueError`` (fixed message per rule) unless ``uri`` is a usable IPP URI."""
    if any(ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in uri):
        raise ValueError("IPP URI must not contain spaces or control characters")
    try:
        parts = urlsplit(uri)
        parts.hostname  # noqa: B018 - parses (and validates) a bracketed IPv6 host
    except ValueError:
        raise ValueError("IPP URI is malformed") from None
    if parts.scheme not in _SCHEMES:
        raise ValueError("IPP URI scheme must be ipp, ipps, http or https")
    if "@" in parts.netloc:
        raise ValueError("IPP URI must not contain user info")
    if "#" in uri:
        raise ValueError("IPP URI must not contain a fragment")
    if not parts.hostname:
        raise ValueError("IPP URI must name a host")
    try:
        port = parts.port
    except ValueError:
        raise ValueError("IPP URI has an invalid port") from None
    if port == 0:
        raise ValueError("IPP URI has an invalid port")


def to_http_url(uri: str) -> str:
    """HTTP(S) URL the IPP request is posted to; ``ipp``/``ipps`` default to port 631."""
    validate_ipp_uri(uri)
    parts = urlsplit(uri)
    scheme = parts.scheme
    netloc = parts.netloc
    if scheme in ("ipp", "ipps") and parts.port is None:
        netloc = f"{netloc}:{_DEFAULT_IPP_PORT}"
    path = parts.path or "/"
    query = f"?{parts.query}" if parts.query else ""
    return f"{_SCHEMES[scheme]}://{netloc}{path}{query}"


# ---------------------------------------------------------------------------- results


@dataclass(frozen=True)
class PrintAccepted:
    """Print-Job was accepted. ``job_uri`` is stored, never requested.

    ``substituted``: the printer answered ``successful-ok-ignored-or-substituted-attributes``
    or ``successful-ok-conflicting-attributes`` — it took the job but did not honour every
    job attribute as sent (spike S2), so the page may not match the request.
    """

    job_id: int
    job_uri: str | None
    substituted: bool = False


@dataclass(frozen=True)
class JobInfo:
    """One job as the printer reports it: ``job-state``, ``job-state-reasons`` (bounded) and
    ``job-impressions-completed`` (``None`` when absent or out-of-band), RFC 8011."""

    job_id: int
    state: int
    reasons: list[str]
    impressions_completed: int | None


def _int(values: list[Value] | None) -> int | None:
    if values and isinstance(values[0], int) and not isinstance(values[0], bool):
        return values[0]
    return None


def _reasons(values: list[Value] | None) -> list[str]:
    out = [v[:MAX_REASON_LENGTH] for v in values or [] if isinstance(v, str)]
    return out[:MAX_REASONS]


def _first_wins(group: Group) -> dict[str, list[Value]]:
    out: dict[str, list[Value]] = {}
    for attr in group.attrs:
        out.setdefault(attr.name, attr.values)
    return out


def _job_info(attrs: dict[str, list[Value]]) -> JobInfo | None:
    job_id = _int(attrs.get("job-id"))
    state = _int(attrs.get("job-state"))
    if job_id is None or state is None:
        return None
    return JobInfo(
        job_id=job_id,
        state=state,
        reasons=_reasons(attrs.get("job-state-reasons")),
        impressions_completed=_int(attrs.get("job-impressions-completed")),
    )


def _status_name(status: int) -> str:
    return STATUS_NAMES.get(status, f"unknown-status-0x{status:04x}")


# ---------------------------------------------------------------------------- client


class IppClient:
    """IPP operations against one printer. Not safe for concurrent use by design of
    the queue (one request at a time per printer); request ids increment per client.
    """

    def __init__(
        self,
        uri: str,
        *,
        tls_verify: bool = True,
        query_timeout_s: float = 5.0,
        upload_timeout_s: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._uri = uri
        self._url = to_http_url(uri)
        self._query_timeout_s = query_timeout_s
        self._upload_timeout_s = upload_timeout_s
        self._request_id = 0
        self._http = httpx.AsyncClient(
            transport=transport,
            verify=tls_verify,
            follow_redirects=False,
            trust_env=False,
            limits=httpx.Limits(max_keepalive_connections=0),
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------ operations

    async def get_printer_attributes(self, requested: Sequence[str]) -> dict[str, list[Value]]:
        ops = self._target()
        ops.append(Attr("requested-attributes", Tag.KEYWORD, list(requested)))
        msg = await self._call("Get-Printer-Attributes", ops)
        return msg.attrs(Tag.PRINTER)

    async def print_job(
        self, pdf: bytes, job_attrs: list[Attr], op_attrs: list[Attr]
    ) -> PrintAccepted:
        ops = self._target()
        ops += self._job_operation_attributes(op_attrs)
        msg = await self._call(
            "Print-Job", ops, job_attrs, document=pdf, timeout_s=self._upload_timeout_s
        )
        attrs = msg.attrs(Tag.JOB)
        job_id = _int(attrs.get("job-id"))
        if job_id is None:
            raise IppBadResponseError("print_job_without_job_id")
        uri = next((v for v in attrs.get("job-uri", []) if isinstance(v, str)), None)
        if uri is not None and len(uri) > MAX_JOB_URI_LENGTH:
            uri = None
        return PrintAccepted(
            job_id=job_id, job_uri=uri, substituted=msg.code in _SUBSTITUTED_STATUSES
        )

    async def validate_job(self, job_attrs: list[Attr]) -> None:
        ops = self._target()
        ops += self._job_operation_attributes([])
        await self._call("Validate-Job", ops, job_attrs)

    async def get_job(self, job_id: int) -> JobInfo:
        ops = self._target(job_id)
        ops.append(Attr("requesting-user-name", Tag.NAME, [USER_NAME]))
        ops.append(Attr("requested-attributes", Tag.KEYWORD, list(JOB_ATTRIBUTES)))
        msg = await self._call("Get-Job-Attributes", ops)
        info = _job_info(msg.attrs(Tag.JOB))
        if info is None:
            raise IppBadResponseError("job_without_id_or_state")
        return info

    async def get_jobs(
        self, which: Literal["not-completed", "completed"] = "not-completed"
    ) -> list[JobInfo]:
        ops = self._target()
        ops += [
            Attr("requesting-user-name", Tag.NAME, [USER_NAME]),
            Attr("limit", Tag.INTEGER, [GET_JOBS_LIMIT]),
            Attr("which-jobs", Tag.KEYWORD, [which]),
            Attr("requested-attributes", Tag.KEYWORD, list(JOB_ATTRIBUTES)),
        ]
        msg = await self._call("Get-Jobs", ops)
        jobs: list[JobInfo] = []
        for group in msg.groups:
            if group.tag != Tag.JOB:
                continue
            info = _job_info(_first_wins(group))
            if info is not None:
                jobs.append(info)
            if len(jobs) == GET_JOBS_LIMIT:
                break
        return jobs

    async def cancel_job(self, job_id: int) -> None:
        ops = self._target(job_id)
        ops.append(Attr("requesting-user-name", Tag.NAME, [USER_NAME]))
        await self._call("Cancel-Job", ops)

    # ------------------------------------------------------------------ internals

    def _target(self, job_id: int | None = None) -> list[Attr]:
        """The operation attributes every request starts with (RFC 8011 4.1.4, 4.1.5)."""
        ops = [
            Attr("attributes-charset", Tag.CHARSET, ["utf-8"]),
            Attr("attributes-natural-language", Tag.LANGUAGE, ["en"]),
            Attr("printer-uri", Tag.URI, [self._uri]),
        ]
        if job_id is not None:
            ops.append(Attr("job-id", Tag.INTEGER, [job_id]))
        return ops

    @staticmethod
    def _job_operation_attributes(op_attrs: list[Attr]) -> list[Attr]:
        """Caller's operation attributes after the ones the client owns.

        ``requesting-user-name`` and ``document-format`` are added when missing;
        a caller cannot replace the charset, language or target.
        """
        given = [a for a in op_attrs if a.name not in _OWNED_OPERATION_ATTRIBUTES]
        names = {a.name for a in given}
        out: list[Attr] = []
        if "requesting-user-name" not in names:
            out.append(Attr("requesting-user-name", Tag.NAME, [USER_NAME]))
        out += given
        if "document-format" not in names:
            out.append(Attr("document-format", Tag.MIME, ["application/pdf"]))
        return out

    def _next_request_id(self) -> int:
        self._request_id = self._request_id % 0x7FFFFFFF + 1
        return self._request_id

    def _timeout(self, timeout_s: float) -> httpx.Timeout:
        connect = min(timeout_s * CONNECT_SHARE, MAX_CONNECT_TIMEOUT_S)
        return httpx.Timeout(timeout_s, connect=connect)

    async def _call(
        self,
        operation: str,
        ops: list[Attr],
        job_attrs: list[Attr] | None = None,
        *,
        document: bytes = b"",
        timeout_s: float | None = None,
    ) -> Message:
        groups = [Group(Tag.OPERATION, ops)]
        if job_attrs:
            groups.append(Group(Tag.JOB, list(job_attrs)))
        request = Message(IPP_VERSION, OPERATIONS[operation], self._next_request_id(), groups)
        body = encode(request, document)
        limit = self._query_timeout_s if timeout_s is None else timeout_s
        try:
            async with asyncio.timeout(limit):
                raw = await self._exchange(body, self._timeout(limit))
        except TimeoutError:
            raise IppTransportError(f"{operation}: no complete answer within {limit} s") from None
        response, _ = decode(raw)
        status = response.code
        logger.debug("ipp %s -> %s", operation, _status_name(status))
        if not 0 <= status <= _SUCCESS_MAX:
            name = _status_name(status)
            if status == _NOT_FOUND:
                raise IppNotFoundError(status, name)
            if status == _BUSY:
                raise IppBusyError(status, name)
            raise IppStatusError(status, name)
        return response

    async def _exchange(self, body: bytes, timeout: httpx.Timeout) -> bytes:
        headers = {"content-type": "application/ipp", "accept-encoding": "identity"}
        try:
            async with self._http.stream(
                "POST", self._url, content=body, headers=headers, timeout=timeout
            ) as response:
                self._check_response(response)
                return await self._read_capped(response)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise IppUnreachableError(f"printer not reachable ({type(exc).__name__})") from exc
        except httpx.TransportError as exc:
            raise IppTransportError(f"exchange failed ({type(exc).__name__})") from exc
        except httpx.DecodingError as exc:  # pragma: no cover - identity bodies only
            raise IppBadResponseError("content_encoding") from exc

    @staticmethod
    def _check_response(response: httpx.Response) -> None:
        if response.status_code != 200:
            raise IppBadResponseError(f"http_status_{response.status_code}")
        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type != "application/ipp":
            raise IppBadResponseError("content_type")
        encoding = response.headers.get("content-encoding", "identity").strip().lower()
        if encoding not in ("", "identity"):
            raise IppBadResponseError("content_encoding")
        declared = response.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > MAX_RESPONSE_BYTES:
            raise IppResponseTooLargeError(f"declared {declared} bytes")

    @staticmethod
    async def _read_capped(response: httpx.Response) -> bytes:
        buffer = bytearray()
        async for chunk in response.aiter_raw():
            buffer += chunk
            if len(buffer) > MAX_RESPONSE_BYTES:
                raise IppResponseTooLargeError(f"over {MAX_RESPONSE_BYTES} bytes")
        return bytes(buffer)
