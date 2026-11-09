"""Global FastAPI exception handlers for service-layer errors.

Each handler maps a domain exception to an RFC 7807 ProblemDetail response.
Register all handlers by calling :func:`register_error_handlers` once after
the FastAPI app is created (in ``app/main.py``).

Note
----
``ValueError`` raised by the Phase 5 jobs repository for invalid state
transitions is intentionally *not* handled here — ``ValueError`` is too
broad a catch-all and would swallow unrelated errors. Routes in
``app.api.routes.jobs`` handle it with an explicit try/except.

References:
    docs/superpowers/specs/2026-05-16-phase6a-rest-api-design.md
    app/services/errors.py
    app/printer_backends/exceptions.py
"""

from __future__ import annotations

import re
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.printer_backends.exceptions import (
    PrinterCoverOpenError,
    PrinterOfflineError,
    TapeEmptyError,
    TapeMismatchError,
)
from app.schemas.problem import ProblemDetail
from app.services.errors import AppLookupNotFoundError, IntegrationNotConfiguredError

# Mapping: exception class → (HTTP status code, problem-type slug)
_MAPPING: dict[type[Exception], tuple[int, str]] = {
    PrinterOfflineError: (503, "printer-offline"),
    TapeMismatchError: (409, "tape-mismatch"),
    TapeEmptyError: (409, "tape-empty"),
    PrinterCoverOpenError: (409, "printer-cover-open"),
    AppLookupNotFoundError: (404, "app-lookup-not-found"),
    IntegrationNotConfiguredError: (503, "integration_not_configured"),
}


def register_error_handlers(app: FastAPI) -> None:
    """Register all service-layer exception handlers on *app*.

    Call this once in :func:`app.main.create_app` after the ``FastAPI``
    instance is created so that the handlers are active for all routes.
    """
    for exc_class, (http_status, problem_type) in _MAPPING.items():
        app.add_exception_handler(
            exc_class,
            _make_handler(http_status, problem_type),
        )
    app.add_exception_handler(RequestValidationError, _validation_handler)


SHEET_PREFIXES = ("/api/v1/sheet-types", "/api/v1/sheets", "/api/v1/sheet-cells")
_SHEET_PRINT_PATH = re.compile(r"^/api/v1/print/[^/]+/sheet(/preview)?$")
"""Sheet print and its preview (pre-flight C19). Their bodies carry label text and purposes, so
a validation error must not repeat them. The tape routes under ``/api/v1/print`` are not matched."""


def is_sheet_path(path: str) -> bool:
    """Whether the sheet error envelope (field paths, no input) applies to ``path``."""
    return path.startswith(SHEET_PREFIXES) or _SHEET_PRINT_PATH.match(path) is not None


WEBHOOK_PREFIX = "/api/v1/webhook/"
"""Webhook bodies are the integrations' own: a rejected value is not repeated (run-12 R12-1)."""


def answers_with_envelope(path: str) -> bool:
    """Whether a validation error on ``path`` is answered with the error envelope (field paths,
    no input). The one predicate for the answer (``_validation_handler``) and for the OpenAPI
    document (``app.main._declare_sheet_error_envelope``), so they cannot drift apart."""
    return is_sheet_path(path) or path.startswith(WEBHOOK_PREFIX)


ADMIN_PRINTERS_PREFIX = "/api/v1/admin/printers"
"""Admin printer payloads carry IPP URIs: their 422 keeps FastAPI's shape without the input."""

# JSON schema of the sheet API error envelope (also used for the 422 documented in OpenAPI).
SHEET_ERROR_SCHEMA_NAME = "SheetApiErrorResponse"
SHEET_ERROR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["detail"],
    "properties": {
        "detail": {
            "type": "object",
            "required": ["error_code", "error_message"],
            "properties": {
                "error_code": {"type": "string"},
                "error_message": {"type": "string"},
                "error_detail": {
                    "anyOf": [
                        {"type": "object", "additionalProperties": True},
                        {"type": "null"},
                    ]
                },
            },
        }
    },
}


async def _validation_handler(request: Request, exc: Exception) -> JSONResponse:
    """Request validation errors of the sheet type and sheet APIs name field paths and nothing else.

    FastAPI's default body repeats the offending input; for these routes the shape is the
    API error shape instead. Other routes keep the default.
    """
    if not isinstance(exc, RequestValidationError):
        raise TypeError("validation handler registered for another exception type")
    if request.url.path.startswith(ADMIN_PRINTERS_PREFIX):
        # Same list shape as FastAPI's default, minus ``input`` and ``ctx``: a rejected IPP
        # URI (user info, a host) is not repeated in the error (spec 18).
        errors = [
            {"type": err["type"], "loc": list(err["loc"]), "msg": err["msg"]}
            for err in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": errors})
    if not answers_with_envelope(request.url.path):
        return await request_validation_exception_handler(request, exc)
    paths: list[str] = []
    for err in exc.errors():
        loc = [str(part) for part in err["loc"] if part != "body"]
        if err["type"] == "extra_forbidden" and loc:
            loc[-1] = "<unknown field>"  # a name the client chose is not echoed
        path = ".".join(loc) or "<request>"
        if path not in paths:
            paths.append(path)
    return JSONResponse(
        status_code=422,
        content={
            "detail": {
                "error_code": "invalid_request",
                "error_message": "Request validation failed.",
                "error_detail": {"errors": paths[:20]},
            }
        },
    )


def _make_handler(
    http_status: int,
    problem_type: str,
) -> Callable[[Request, Exception], Coroutine[Any, Any, JSONResponse]]:
    """Return an async exception-handler coroutine for the given mapping.

    Using a factory (closure) ensures each handler captures its own
    ``http_status`` and ``problem_type`` values rather than sharing a
    mutable reference from the loop body in :func:`register_error_handlers`.
    """

    async def handler(_request: Request, exc: Exception) -> JSONResponse:
        problem = ProblemDetail(
            type=problem_type,
            title=problem_type.replace("-", " ").replace("_", " ").title(),
            status=http_status,
            detail=str(exc),
        )
        return JSONResponse(
            status_code=http_status,
            content=problem.model_dump(exclude_none=True),
        )

    return handler
