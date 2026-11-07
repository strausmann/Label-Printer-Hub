"""Error types of the sheet archive API.

Every error maps to the existing error shape
``HTTPException(status, detail={"error_code", "error_message", "error_detail"})``.
Messages are fixed English text; raw input is never echoed beyond identifiers.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException


class SheetApiError(Exception):
    """Base class: a domain error with an HTTP status and a stable error code."""

    status: int = 400
    error_code: str = "sheet_error"
    message: str = "Sheet request failed."

    def __init__(
        self,
        message: str | None = None,
        *,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.message = message if message is not None else type(self).message
        self.detail = detail
        super().__init__(self.message)

    def to_http(self) -> HTTPException:
        return HTTPException(
            status_code=self.status,
            detail={
                "error_code": self.error_code,
                "error_message": self.message,
                "error_detail": self.detail,
            },
        )


class SheetTypeNotFoundError(SheetApiError):
    status = 404
    error_code = "sheet_type_not_found"
    message = "Sheet type not found."


class SheetTypeVersionNotFoundError(SheetApiError):
    status = 404
    error_code = "sheet_type_version_not_found"
    message = "Sheet type version not found."


class SheetTypeArchivedError(SheetApiError):
    status = 409
    error_code = "sheet_type_archived"
    message = "Sheet type is archived."


class TypeExistsError(SheetApiError):
    status = 409
    error_code = "type_exists"
    message = "A sheet type with this key already exists."


class PrefixTakenError(SheetApiError):
    status = 409
    error_code = "prefix_taken"
    message = "This sheet code prefix is already used by another sheet type."


class PrefixLockedError(PrefixTakenError):
    """The prefix cannot change any more because sheets already carry it (OC-5)."""

    def __init__(self) -> None:
        super().__init__(
            "The sheet code prefix cannot change while sheets of this type exist.",
            detail={"reason": "sheets_exist"},
        )


class SheetTypeInUseError(SheetApiError):
    status = 409
    error_code = "type_in_use"
    message = "Sheet type cannot be deleted."

    def __init__(self, reason: str) -> None:
        super().__init__(detail={"reason": reason})


class InvalidGeometryError(SheetApiError):
    status = 422
    error_code = "invalid_geometry"

    def __init__(self, field: str, reason: str) -> None:
        super().__init__(
            f"Invalid geometry: {field}: {reason}.",
            detail={"field": field, "reason": reason},
        )


class InvalidFieldError(InvalidGeometryError):
    """A non-geometry field has a bad value; same code and status as invalid geometry."""

    def __init__(self, field: str, reason: str) -> None:
        super().__init__(field, reason)
        self.message = f"Invalid value for {field}: {reason}."
        self.args = (self.message,)


class SheetNotFoundError(SheetApiError):
    status = 404
    error_code = "sheet_not_found"
    message = "Sheet not found."


class SheetDiscardedError(SheetApiError):
    status = 409
    error_code = "sheet_discarded"
    message = "Sheet is discarded."


class SheetBusyError(SheetApiError):
    status = 409
    error_code = "sheet_busy"
    message = "Sheet is in use by a running job."


class CellsTakenError(SheetApiError):
    status = 409
    error_code = "cells_taken"
    message = "Some cells are not free."

    def __init__(self, cells: list[int]) -> None:
        super().__init__(detail={"cells": cells})


class CellsNotMarkedByHandError(SheetApiError):
    """Only cells marked by hand can be un-marked; a printed cell carries a label (spec 8)."""

    status = 409
    error_code = "cells_not_marked_by_hand"
    message = "Some cells were not marked by hand."

    def __init__(self, cells: list[int]) -> None:
        super().__init__(detail={"cells": cells})


class CellsNotUnconfirmedError(SheetApiError):
    status = 409
    error_code = "cells_not_unconfirmed"
    message = "Some cells are not waiting for confirmation."

    def __init__(self, cells: list[int]) -> None:
        super().__init__(detail={"cells": cells})


class CellOutOfRangeError(SheetApiError):
    status = 422
    error_code = "cell_out_of_range"
    message = "Cell number is outside the sheet."

    def __init__(self, cells: list[int], max_cell: int) -> None:
        super().__init__(detail={"cells": cells, "max": max_cell})


class InsufficientCellsError(SheetApiError):
    """The free cells of the chosen sheets do not hold all items (spec 8)."""

    status = 409
    error_code = "insufficient_cells"
    message = "Not enough free cells for these items."

    def __init__(self, free_cells: list[int], needed: int, shortfall: int) -> None:
        super().__init__(
            detail={"free_cells": free_cells, "needed": needed, "shortfall": shortfall}
        )


class PlanChangedError(SheetApiError):
    """The fresh plan differs from the one the client confirmed (OC-8); nothing was written."""

    status = 409
    error_code = "plan_changed"
    message = "The cell plan changed since the preview."

    def __init__(self, plan: list[dict[str, Any]]) -> None:
        super().__init__(detail={"plan": plan})


class SheetTypeMismatchError(SheetApiError):
    """A placement names a sheet of another type than the request needs."""

    status = 409
    error_code = "sheet_type_mismatch"
    message = "The sheet is of another type than this print needs."

    def __init__(self, expected: str, actual: str) -> None:
        super().__init__(detail={"expected": expected, "actual": actual})


class InvalidPlacementsError(SheetApiError):
    """The placements contradict each other or the item count; ``reason`` names the rule."""

    status = 422
    error_code = "invalid_placements"
    message = "The placements are not valid."

    def __init__(self, reason: str) -> None:
        super().__init__(detail={"reason": reason})


class ImportTooLargeError(SheetApiError):
    status = 413
    error_code = "import_too_large"
    message = "Import document is too large."


class InvalidImportError(SheetApiError):
    status = 422
    error_code = "invalid_import"
    message = "Import document is invalid."

    def __init__(self, errors: list[str]) -> None:
        super().__init__(detail={"errors": errors})


# ---------------------------------------------------------------------------- page printers
# Messages are fixed text: an error never names the IPP URI or repeats the printer's answer
# beyond the IPP status name (spec 18).


class MediaKindMismatchError(SheetApiError):
    """A tape route was called for a page printer (or the other way round)."""

    status = 409
    error_code = "media_kind_mismatch"
    message = "This printer does not print this kind of media."


class PageJobNotRetryableError(SheetApiError):
    """A sheet page cannot be re-sent as is: its cells need the cell-aware path (Plan 3)."""

    status = 409
    error_code = "job_not_retryable"
    message = "This page job cannot be retried."


class TrayUnknownError(SheetApiError):
    status = 422
    error_code = "tray_unknown"
    message = "The printer does not report some of these trays."

    def __init__(self, trays: list[str]) -> None:
        super().__init__(detail={"trays": trays})


class IppUnreachableApiError(SheetApiError):
    """409 when saving a printer (nothing was saved), 502 for the live probe."""

    status = 409
    error_code = "ipp_unreachable"
    message = "The printer could not be reached."

    def __init__(self, status: int = 409) -> None:
        super().__init__()
        self.status = status


class IppPdfUnsupportedError(SheetApiError):
    """OC-18: the hub sends nothing but PDF, so a printer without PDF cannot be saved."""

    status = 409
    error_code = "ipp_pdf_unsupported"
    message = "The printer does not accept PDF documents."


class IppRejectedError(SheetApiError):
    status = 502
    error_code = "ipp_rejected"
    message = "The printer refused the request."

    def __init__(self, ipp_status: str) -> None:
        super().__init__(detail={"ipp_status": ipp_status})


class IppBadResponseApiError(SheetApiError):
    status = 502
    error_code = "ipp_bad_response"
    message = "The printer's answer could not be used."


# ---------------------------------------------------------------------------- calibration


class PrinterNotFoundError(SheetApiError):
    status = 404
    error_code = "printer_not_found"
    message = "Printer not found."


class CalibrationOutOfRangeError(SheetApiError):
    """A calibration value is outside its allowed range or has too many decimals."""

    status = 422
    error_code = "calibration_out_of_range"
    message = "A calibration value is outside the allowed range."

    def __init__(
        self,
        field: str,
        *,
        minimum: float,
        maximum: float,
        reason: str = "out_of_range",
    ) -> None:
        super().__init__(
            f"Calibration value {field} is not acceptable ({reason}).",
            detail={"field": field, "min": minimum, "max": maximum, "reason": reason},
        )


class ReadingsInsufficientError(SheetApiError):
    """Fewer than three readings, or all on one line: no deviation can be fitted."""

    status = 422
    error_code = "readings_insufficient"
    message = "The readings are not enough to fit a calibration."

    def __init__(self, reason: str) -> None:
        super().__init__(detail={"reason": reason})


class CalibrationTypeUnsuitableError(SheetApiError):
    """A calibration page needs crossings: at least two columns and two rows."""

    status = 422
    error_code = "calibration_type_unsuitable"
    message = (
        "This sheet type has no crossings to measure: it needs at least two columns and two rows."
    )

    def __init__(self, cols: int, rows: int) -> None:
        super().__init__(detail={"cols": cols, "rows": rows})


# ---------------------------------------------------------------------------- sheet printing


class SheetPrinterDisabledError(SheetApiError):
    """The printer is switched off; sheet prints are refused at the route (pre-flight C18)."""

    status = 409
    error_code = "printer_disabled"
    message = "This printer is disabled."


class ItemLookupFailedError(SheetApiError):
    """An item's integration lookup failed. It keeps the status and the code of the error the
    lookup raised (pre-flight C10) and names the item; the message is fixed text, because the
    lookup's own text can carry URLs and upstream detail."""

    def __init__(self, *, status: int, code: str, message: str, item_index: int) -> None:
        super().__init__(message, detail={"item_index": item_index})
        self.status = status
        self.error_code = code


class ItemContentMismatchError(SheetApiError):
    """An item lacks what its (mapped) content type needs; nothing is reserved (spec 12.5)."""

    status = 422
    error_code = "content_type_data_mismatch"
    message = "An item lacks the data its content type needs."

    def __init__(self, item_index: int, missing_fields: tuple[str, ...]) -> None:
        super().__init__(detail={"item_index": item_index, "missing_fields": list(missing_fields)})


class PreviewTooLargeError(SheetApiError):
    """The plan has more pages than a preview renders (a load bound, spec 18)."""

    status = 422
    error_code = "preview_too_large"
    message = "The plan has too many pages for a preview."

    def __init__(self, pages: int, maximum: int) -> None:
        super().__init__(detail={"pages": pages, "max": maximum})


class PrinterUnavailableError(SheetApiError):
    """The print queue does not know the printer (for example a page printer added after the
    start); nothing was printed and the reserved cells are free again (pre-flight C24)."""

    status = 409
    error_code = "printer-unavailable"
    message = "Printer is not available to the print queue."
