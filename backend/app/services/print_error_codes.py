# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The status, ``error_code`` and message of every known printer and render error.

One table for every printing and rendering route (#378): the routes answer with it through the
renderers of ``app/api/print_errors.py``, and the global handlers catch what a route lets
through. A deferred job (#281, R-281-11) records the same code when its completion fails after
the answer.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.printer_backends.exceptions import (
    ContentTypeDataMismatchError,
    MediaTypeMismatchError,
    NoTapeLoadedError,
    PrinterCoverOpenError,
    PrinterDisabledError,
    PrinterOfflineError,
    PrinterReportedError,
    QrPayloadTooLongError,
    SnmpQueryError,
    SpoolLabelOnlyTapeError,
    TapeEmptyError,
    TapeLabelTooLongError,
    TapeMismatchError,
    UnsupportedTapeError,
)
from app.services.lookup_service import LookupFailedError, UnknownAppError

SYNC_ERROR_MAP: dict[type[Exception], tuple[int, str]] = {
    UnknownAppError: (422, "integration_unknown_app"),
    LookupFailedError: (502, "integration_lookup_failed"),
    PrinterDisabledError: (409, "printer_disabled"),
    TapeMismatchError: (409, "tape_mismatch"),
    MediaTypeMismatchError: (409, "media_type_mismatch"),
    TapeEmptyError: (409, "tape_empty"),
    NoTapeLoadedError: (409, "no_tape_loaded"),
    PrinterCoverOpenError: (409, "printer_cover_open"),
    PrinterReportedError: (409, "printer_error"),
    PrinterOfflineError: (503, "printer_offline"),
    UnsupportedTapeError: (409, "unsupported_tape"),
    ContentTypeDataMismatchError: (422, "content_type_data_mismatch"),
    QrPayloadTooLongError: (422, "qr_payload_too_long"),
    TapeLabelTooLongError: (422, "tape_label_too_long"),
    SnmpQueryError: (503, "snmp_query_failed"),
}

KNOWN_PRINT_ERROR_TYPES: tuple[type[Exception], ...] = tuple(SYNC_ERROR_MAP)
"""What a printing route catches to answer with the shared table (#378)."""

# Lookup errors wrap upstream text (URLs, response details): the client gets a fixed message.
_FIXED_MESSAGES: dict[str, str] = {
    "integration_unknown_app": "The requested integration is not available.",
    "integration_lookup_failed": "The integration failed or could not be reached.",
}

_UNSUPPORTED_WIDTH = "The currently loaded tape width is not supported by the layout engine."
_UNSUPPORTED_ORIENTATION = "The selected orientation is not available for this tape width."
_NO_TAPE = "No tape loaded — insert a Brother TZe or DK cartridge."
_MISSING_FIELDS = "The label data is missing fields required for the selected content type."
_DIE_CUT = "The loaded roll is die-cut labels; the hub prints on continuous tape only."
_PRINTER_ERROR = "The printer reports an error state. Fix it on the printer and try again."
_QR_TOO_LONG = "The QR payload does not fit the fixed QR code of this tape."
# The cause of these two names the printer's address or the SNMP library's error: log only.
_UNREACHABLE: dict[str, str] = {
    "printer_offline": "The printer could not be reached.",
    "snmp_query_failed": "The printer did not answer the status query.",
}


@dataclass(frozen=True)
class KnownPrintError:
    """How a known printer or render error is answered: status, code, text and detail."""

    status: int
    code: str
    message: str
    detail: dict[str, object] | None
    log_detail: str | None = None
    """The cause for the hub's own log only (a printer address, an SNMP error), never sent."""


def print_error_mapping(exc: Exception) -> tuple[int, str]:
    """Map by the nearest mapped base class: a subclass must never fall through (KeyError)."""
    for cls in type(exc).__mro__:
        if cls in SYNC_ERROR_MAP:
            return SYNC_ERROR_MAP[cls]
    return 500, "internal_error"  # unreachable for mapped types; never raise from here


def describe_print_error(exc: Exception) -> KnownPrintError:
    """The answer for ``exc``, mapped by its nearest known base class.

    Fixed sentences for lookup, unsupported-tape and content errors (CWE-209: never
    ``str(exc)``, which can carry upstream URLs or internal names); the structured values go
    to ``detail``.
    """
    status, code = print_error_mapping(exc)
    message: str
    detail: dict[str, object] | None = None
    log_detail: str | None = None
    if isinstance(exc, SpoolLabelOnlyTapeError):
        message = (
            f"Only the spool label prints on {exc.tape_mm} mm tape. Remove the other labels "
            "from the cart or load 62 mm tape."
        )
        detail = {"tape_mm": exc.tape_mm, "content_types": list(exc.content_types)}
    elif isinstance(exc, UnsupportedTapeError):
        message = _UNSUPPORTED_WIDTH if exc.orientation is None else _UNSUPPORTED_ORIENTATION
        detail = {"tape_mm": exc.tape_mm}
    elif isinstance(exc, NoTapeLoadedError):
        message = _NO_TAPE
    elif isinstance(exc, ContentTypeDataMismatchError):
        message = _MISSING_FIELDS
        detail = {"missing_fields": list(exc.missing_fields)}
    elif isinstance(exc, QrPayloadTooLongError):
        message = _QR_TOO_LONG
        detail = {"length": exc.length, "max_bytes": exc.max_bytes}
    elif isinstance(exc, TapeLabelTooLongError):
        message = str(exc)
        detail = {"length_mm": exc.length_mm, "max_mm": exc.max_mm}
    elif isinstance(exc, TapeMismatchError):
        message = str(exc)
        detail = {"expected_mm": exc.expected_mm, "loaded_mm": exc.loaded_mm}
    elif isinstance(exc, PrinterReportedError):
        # The flag names only; the words for them live in the app (#376).
        message = _PRINTER_ERROR
        detail = {"flags": list(exc.flags)}
    elif isinstance(exc, MediaTypeMismatchError):
        message = _DIE_CUT
        detail = {"loaded_kind": exc.loaded_kind, "media_raw": exc.media_raw}
    elif code in _FIXED_MESSAGES:
        message = _FIXED_MESSAGES[code]
    elif code in _UNREACHABLE:
        message = _UNREACHABLE[code]
        log_detail = str(exc) or None
    else:
        # The hardware errors carry only hardware-state descriptions.
        message = str(exc) or code
    return KnownPrintError(
        status=status, code=code, message=message, detail=detail, log_detail=log_detail
    )


def print_error_code(exc: Exception) -> str:
    """The ``error_code`` ``POST /api/v1/print`` answers for ``exc``."""
    return print_error_mapping(exc)[1]
