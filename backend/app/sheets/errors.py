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


class CellOutOfRangeError(SheetApiError):
    status = 422
    error_code = "cell_out_of_range"
    message = "Cell number is outside the sheet."

    def __init__(self, cells: list[int], max_cell: int) -> None:
        super().__init__(detail={"cells": cells, "max": max_cell})
