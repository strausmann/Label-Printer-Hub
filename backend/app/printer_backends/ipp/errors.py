"""Typed errors of the hub's own IPP client.

``IppDecodeError`` carries a stable, machine-readable ``reason`` so callers and
tests can tell which check rejected a message; the human-readable text never
contains printer-supplied bytes beyond lengths and offsets. No error message
contains the printer's URI (logs name the printer by slug only).

The transport errors split on one question the queue has to answer: could any
byte of the request have reached the printer?

* ``IppUnreachableError``: no. The connection was never established (connect
  error, connect timeout, TLS handshake failure, no free connection).
* ``IppTransportError``: maybe. The request had started when it failed (read
  or write timeout, reset, protocol error, the overall deadline).

How a failed **Print-Job** ends (the contract the page-job runner relies on;
"started" = bytes may have reached the printer, cells unconfirmed):

* ``IppUnreachableError`` — nothing was sent: ``failed``, ``started=False``.
* ``IppTransportError`` — the upload had begun: ``failed``/``interrupted``,
  ``started=True``.
* ``IppBusyError`` — the printer answered and refused the job for now:
  ``failed``, ``started=False``.
* ``IppStatusError`` (``client-error-*`` and ``server-error-*`` alike, including
  ``IppNotFoundError``) — the printer answered with a refusal, so it did not
  accept the job: ``failed``, ``started=False``.
* ``IppBadResponseError``, ``IppDecodeError``, ``IppResponseTooLargeError`` — the
  request was sent but the answer is unusable, so whether the printer accepted
  the job is unknown: ``failed``/``interrupted``, ``started=True``.
* ``IppEncodeError`` — raised while building the request, before anything is
  sent: ``failed``, ``started=False``.
"""

from __future__ import annotations


class IppError(Exception):
    """Root of every IPP error raised by ``app.printer_backends.ipp``."""


class IppDecodeError(IppError):
    """Bytes received from a printer are not a well-formed, bounded IPP message."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


class IppEncodeError(IppError, ValueError):
    """A ``Message`` cannot be encoded (value out of range, length over 32767, bad tag)."""


class IppUnreachableError(IppError):
    """The printer could not be reached; nothing of the request was sent."""


class IppTransportError(IppError):
    """The exchange failed after the request had started; bytes may have reached the printer."""


class IppResponseTooLargeError(IppError):
    """The response body exceeded the client's size cap; reading was aborted."""


class IppBadResponseError(IppError):
    """The HTTP answer is not a usable IPP response.

    HTTP status other than 200 (redirects are never followed), a content type
    other than ``application/ipp``, a content encoding, or an IPP response that
    lacks an attribute the operation must return (``job-id``, ``job-state``).
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class IppStatusError(IppError):
    """The printer answered with an IPP status-code that is not successful-ok*."""

    def __init__(self, status: int, name: str) -> None:
        self.status = status
        self.name = name
        super().__init__(f"{name} (0x{status:04x})")


class IppNotFoundError(IppStatusError):
    """``client-error-not-found`` (0x0406): the printer does not know the job (any more)."""


class IppBusyError(IppStatusError):
    """``server-error-busy`` (0x0507): the printer refused the request for now."""
