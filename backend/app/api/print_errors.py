"""Synchronous print errors and their HTTP answer, shared by every route that submits a label.

``POST /api/v1/print`` and the Spoolman/Grocy webhooks call ``PrintService.submit_print_job``;
the errors it raises before anything is queued (preflight, render, lookup) are answered the same
way on all of them.
"""

from __future__ import annotations

from fastapi.responses import JSONResponse

from app.printer_backends.exceptions import (
    ContentTypeDataMismatchError,
    NoTapeLoadedError,
    PrinterCoverOpenError,
    PrinterDisabledError,
    PrinterOfflineError,
    QrPayloadTooLongError,
    TapeEmptyError,
    TapeMismatchError,
    UnsupportedTapeError,
)
from app.services.lookup_service import LookupFailedError, UnknownAppError

_SYNC_ERROR_MAP: dict[type[Exception], tuple[int, str]] = {
    UnknownAppError: (422, "integration_unknown_app"),
    LookupFailedError: (502, "integration_lookup_failed"),
    PrinterDisabledError: (409, "printer_disabled"),
    TapeMismatchError: (409, "tape_mismatch"),
    TapeEmptyError: (409, "tape_empty"),
    NoTapeLoadedError: (409, "no_tape_loaded"),
    PrinterCoverOpenError: (409, "printer_cover_open"),
    PrinterOfflineError: (503, "printer_offline"),
    UnsupportedTapeError: (409, "unsupported_tape"),
    ContentTypeDataMismatchError: (422, "content_type_data_mismatch"),
    QrPayloadTooLongError: (422, "qr_payload_too_long"),
}

SYNC_ERROR_TYPES: tuple[type[Exception], ...] = tuple(_SYNC_ERROR_MAP)
"""What a route catches around ``submit_print_job`` to answer with ``print_error_response``."""


# Lookup errors wrap upstream text (URLs, response details): the client gets a fixed message.
_FIXED_MESSAGES: dict[str, str] = {
    "integration_unknown_app": "The requested integration is not available.",
    "integration_lookup_failed": "The integration failed or could not be reached.",
}


def _mapping_for(exc: Exception) -> tuple[int, str]:
    """Map by the nearest mapped base class: a subclass must never fall through (KeyError)."""
    for cls in type(exc).__mro__:
        if cls in _SYNC_ERROR_MAP:
            return _SYNC_ERROR_MAP[cls]
    return 500, "internal_error"  # unreachable for caught types; never raise from here


def print_error_response(exc: Exception) -> JSONResponse:
    """The JSON answer for an exception of ``SYNC_ERROR_TYPES``."""
    http_status, code = _mapping_for(exc)
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
