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

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.printer_backends.exceptions import (
    PrinterCoverOpenError,
    PrinterOfflineError,
    TapeEmptyError,
    TapeMismatchError,
)
from app.schemas.problem import ProblemDetail
from app.services.errors import AppLookupNotFoundError

# Mapping: exception class → (HTTP status code, problem-type slug)
_MAPPING: dict[type[Exception], tuple[int, str]] = {
    PrinterOfflineError: (503, "printer-offline"),
    TapeMismatchError: (409, "tape-mismatch"),
    TapeEmptyError: (409, "tape-empty"),
    PrinterCoverOpenError: (409, "printer-cover-open"),
    AppLookupNotFoundError: (404, "app-lookup-not-found"),
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
            title=problem_type.replace("-", " ").title(),
            status=http_status,
            detail=str(exc),
        )
        return JSONResponse(
            status_code=http_status,
            content=problem.model_dump(exclude_none=True),
        )

    return handler
