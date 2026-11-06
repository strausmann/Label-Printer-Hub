from __future__ import annotations

from app.sheets.errors import (
    CellOutOfRangeError,
    CellsTakenError,
    InvalidGeometryError,
    SheetTypeNotFoundError,
)


def test_to_http_shape() -> None:
    http = CellsTakenError([3, 5]).to_http()
    assert http.status_code == 409
    detail_a: object = http.detail
    assert detail_a == {
        "error_code": "cells_taken",
        "error_message": "Some cells are not free.",
        "error_detail": {"cells": [3, 5]},
    }


def test_default_message_and_no_detail() -> None:
    http = SheetTypeNotFoundError().to_http()
    assert http.status_code == 404
    detail: dict[str, object] = http.detail  # type: ignore[assignment]
    assert detail["error_code"] == "sheet_type_not_found"
    assert detail["error_detail"] is None


def test_invalid_geometry_and_out_of_range() -> None:
    err = InvalidGeometryError("cols", "must be at least 1")
    assert err.status == 422
    assert err.detail == {"field": "cols", "reason": "must be at least 1"}
    oor = CellOutOfRangeError([49], 48)
    assert (oor.status, oor.detail) == (422, {"cells": [49], "max": 48})
