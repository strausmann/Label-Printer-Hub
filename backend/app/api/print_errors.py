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
from collections.abc import Mapping
from typing import Any, Literal

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app.printer_backends.exceptions import PrinterDisabledError
from app.schemas.problem import ProblemDetail
from app.services.print_error_codes import (
    KNOWN_PRINT_ERROR_TYPES,
    SYNC_ERROR_MAP,
    describe_print_error,
)

_log = logging.getLogger(__name__)

SYNC_ERROR_TYPES: tuple[type[Exception], ...] = KNOWN_PRINT_ERROR_TYPES
"""What a route catches around ``submit_print_job`` to answer with ``print_error_response``."""


def _log_refusal(request: Request, code: str, cause: str | None = None) -> None:
    """One line, no traceback; the path without its query string (a token can ride there)."""
    if cause:
        _log.warning("refused %s %s: %s (%s)", request.method, request.url.path, code, cause)
    else:
        _log.warning("refused %s %s: %s", request.method, request.url.path, code)


def _envelope(exc: Exception, request: Request) -> tuple[int, dict[str, object]]:
    known = describe_print_error(exc)
    _log_refusal(request, known.code, known.log_detail)
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
    _log_refusal(request, final_code, known.log_detail)
    return ProblemDetail(
        type=final_code.replace("_", "-"),
        title=known.message,
        status=status if status is not None else known.status,
        extensions=dict(known.detail) if known.detail is not None else {},
    )


def problem_response(problem: ProblemDetail) -> JSONResponse:
    """A problem as the top-level body, as the global handlers answer."""
    return JSONResponse(status_code=problem.status, content=problem.model_dump(exclude_none=True))


_SHAPE_TEXT = {
    "envelope": "Body: `{error_code, error_message, error_detail?}`; a disabled printer answers "
    '`{"error": "printer_disabled", "slug"}`.',
    "wrapped": "Body: `{detail: {error_code, error_message, error_detail?}}`.",
    "problem": "Body: a problem under `detail` (`type` is the code, `title` the message, "
    "structured values in `extensions`).",
}


def print_error_responses(
    shape: Literal["envelope", "wrapped", "problem"],
    *,
    extra: Mapping[int, str] | None = None,
    overrides: Mapping[str, tuple[int, str]] | None = None,
) -> dict[int | str, dict[str, Any]]:
    """OpenAPI ``responses=`` for the known printer and render errors of a route (#378).

    One description per status, listing every code of the shared table that answers with it, in
    the route's body shape (``problem`` spells the codes with ``-``). ``extra`` adds the route's
    own refusals to a status; ``overrides`` answers a code with another status and code
    (R-378-1: the test print answers an unreachable printer and an SNMP failure with 409
    ``printer_offline``).
    """
    codes: dict[int, list[str]] = {}
    for status, code in SYNC_ERROR_MAP.values():
        status, code = (overrides or {}).get(code, (status, code))
        spelled = code.replace("_", "-") if shape == "problem" else code
        if spelled not in codes.setdefault(status, []):
            codes[status].append(spelled)
    for status in extra or {}:
        codes.setdefault(status, [])
    responses: dict[int | str, dict[str, Any]] = {}
    for status in sorted(codes):
        parts = [(extra or {}).get(status, "")]
        if codes[status]:
            listed = ", ".join(f"`{c}`" for c in codes[status])
            parts.append(f"Known printer or render errors: {listed}. {_SHAPE_TEXT[shape]}")
        responses[status] = {"description": " ".join(p for p in parts if p)}
    if 422 in responses:
        # A documented 422 replaces FastAPI's own entry, schema included: keep the schema of the
        # validation error the route still answers (a webhook's is replaced by the envelope in
        # ``app.main._declare_sheet_error_envelope``).
        responses[422]["content"] = {
            "application/json": {"schema": {"$ref": "#/components/schemas/HTTPValidationError"}}
        }
    return responses
