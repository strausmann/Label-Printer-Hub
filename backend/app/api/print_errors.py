# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Known printer and render errors and their HTTP answer, shared by every printing route (#378).

One table (``app.services.print_error_codes``), four body shapes (R-378-2), each kept as its
route answered it before:

- (a) envelope ``{error_code, error_message, error_detail?}``: ``POST /api/v1/print``, the
  render routes and the Spoolman/Grocy webhooks (:func:`print_error_response`);
- (b) ``{"error": "printer_disabled", "slug"}`` for a disabled printer on the same routes;
- (c) the envelope under ``detail``: the batch route (:func:`print_error_http`);
- (d) an RFC 7807 problem (:func:`print_error_problem`), under ``detail`` on the test print and
  top-level from the global handlers (:func:`problem_response`).

Every renderer logs one ``WARNING`` line without a traceback: a refused print is expected, not a
server fault.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app.printer_backends.exceptions import PrinterDisabledError
from app.schemas.problem import ProblemDetail
from app.services.print_error_codes import KNOWN_PRINT_ERROR_TYPES, describe_print_error

_log = logging.getLogger(__name__)

SYNC_ERROR_TYPES: tuple[type[Exception], ...] = KNOWN_PRINT_ERROR_TYPES
"""What a route catches around ``submit_print_job`` to answer with ``print_error_response``."""


def _log_refusal(request: Request, code: str) -> None:
    _log.warning("refused %s %s: %s", request.method, request.url.path, code)


def _envelope(exc: Exception, request: Request) -> tuple[int, dict[str, object]]:
    known = describe_print_error(exc)
    _log_refusal(request, known.code)
    body: dict[str, object] = {"error_code": known.code, "error_message": known.message}
    if known.detail is not None:
        body["error_detail"] = known.detail
    return known.status, body


def print_error_response(exc: Exception, request: Request) -> JSONResponse:
    """The top-level answer (shapes a and b) for an exception of ``KNOWN_PRINT_ERROR_TYPES``."""
    if isinstance(exc, PrinterDisabledError):
        known = describe_print_error(exc)
        _log_refusal(request, known.code)
        # Spec Phase 4: a disabled printer has its own body
        # ({"error": ..., "slug": ...} instead of {"error_code": ...}).
        return JSONResponse(
            status_code=known.status, content={"error": known.code, "slug": exc.slug}
        )
    status, body = _envelope(exc, request)
    return JSONResponse(status_code=status, content=body)


def print_error_http(exc: Exception, request: Request) -> HTTPException:
    """The envelope under ``detail`` (shape c), raised by the caller."""
    status, body = _envelope(exc, request)
    return HTTPException(status, detail=body)


def print_error_problem(
    exc: Exception,
    request: Request,
    *,
    status: int | None = None,
    code: str | None = None,
) -> ProblemDetail:
    """The problem (shape d): ``type`` is the code with ``-``, ``title`` the message.

    ``status`` and ``code`` override the table for a route that answers differently (R-378-1).
    """
    known = describe_print_error(exc)
    final_code = code if code is not None else known.code
    _log_refusal(request, final_code)
    return ProblemDetail(
        type=final_code.replace("_", "-"),
        title=known.message,
        status=status if status is not None else known.status,
        extensions=dict(known.detail) if known.detail is not None else {},
    )


def problem_response(problem: ProblemDetail) -> JSONResponse:
    """A problem as the top-level body, as the global handlers answer."""
    return JSONResponse(status_code=problem.status, content=problem.model_dump(exclude_none=True))
