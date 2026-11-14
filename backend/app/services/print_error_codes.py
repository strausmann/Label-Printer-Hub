# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The status and ``error_code`` of every error ``PrintService`` raises before a label is queued.

``POST /api/v1/print`` and the webhooks answer with them (``app/api/print_errors.py``); a
deferred job (#281, R-281-11) records the same code when its completion fails after the answer.
"""

from __future__ import annotations

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

SYNC_ERROR_MAP: dict[type[Exception], tuple[int, str]] = {
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


def print_error_mapping(exc: Exception) -> tuple[int, str]:
    """Map by the nearest mapped base class: a subclass must never fall through (KeyError)."""
    for cls in type(exc).__mro__:
        if cls in SYNC_ERROR_MAP:
            return SYNC_ERROR_MAP[cls]
    return 500, "internal_error"  # unreachable for mapped types; never raise from here


def print_error_code(exc: Exception) -> str:
    """The ``error_code`` ``POST /api/v1/print`` answers for ``exc``."""
    return print_error_mapping(exc)[1]
