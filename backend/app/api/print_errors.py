# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Synchronous print errors and their HTTP answer, shared by every route that submits a label.

``POST /api/v1/print`` and the Spoolman/Grocy webhooks call ``PrintService.submit_print_job``;
the errors it raises before anything is queued (preflight, render, lookup) are answered the same
way on all of them.
"""

from __future__ import annotations

from fastapi.responses import JSONResponse

from app.printer_backends.exceptions import (
    PrinterDisabledError,
    QrPayloadTooLongError,
    TapeMismatchError,
)
from app.services.print_error_codes import SYNC_ERROR_MAP, print_error_mapping

SYNC_ERROR_TYPES: tuple[type[Exception], ...] = tuple(SYNC_ERROR_MAP)
"""What a route catches around ``submit_print_job`` to answer with ``print_error_response``."""


# Lookup errors wrap upstream text (URLs, response details): the client gets a fixed message.
_FIXED_MESSAGES: dict[str, str] = {
    "integration_unknown_app": "The requested integration is not available.",
    "integration_lookup_failed": "The integration failed or could not be reached.",
}


def print_error_response(exc: Exception) -> JSONResponse:
    """The JSON answer for an exception of ``SYNC_ERROR_TYPES``."""
    http_status, code = print_error_mapping(exc)
    if isinstance(exc, PrinterDisabledError):
        # Spec Phase 4: abweichendes Body-Format für printer_disabled
        # ({"error": ..., "slug": ...} statt {"error_code": ...})
        return JSONResponse(status_code=http_status, content={"error": code, "slug": exc.slug})
    body: dict[str, object] = {
        "error_code": code,
        "error_message": _FIXED_MESSAGES.get(code, str(exc)),
    }
    if isinstance(exc, TapeMismatchError):
        body["error_detail"] = {"expected_mm": exc.expected_mm, "loaded_mm": exc.loaded_mm}
    if isinstance(exc, QrPayloadTooLongError):
        body["error_detail"] = {"length": exc.length, "max_bytes": exc.max_bytes}
    return JSONResponse(status_code=http_status, content=body)
