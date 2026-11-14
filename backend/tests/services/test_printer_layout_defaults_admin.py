# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stored QL layout default per printer and tape width via the admin API (#258)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.api.routes.admin_printers_api import _row_to_read
from app.models.printer import Printer
from app.schemas.label_layout import LabelOrientation, LayoutDefault, QlLayoutPreset
from app.schemas.printer_admin import PrinterCreatePayload, PrinterUpdatePayload
from app.services.printer_admin_service import (
    _apply_update_patch,
    _payload_to_row,
    _printer_to_row_dict,
    _row_to_audit_view,
)
from pydantic import ValidationError

_QL = {
    "name": "QL",
    "slug": "ql-1",
    "model": "QL-820NWB",
    "backend": "brother_ql",
    "connection": {"host": "192.0.2.11", "port": 9100},
}


def test_update_payload_accepts_a_62mm_default() -> None:
    patch = PrinterUpdatePayload.model_validate(
        {"layout_defaults": {"62": {"orientation": "across", "preset": "standard"}}}
    )
    assert patch.layout_defaults == {
        62: LayoutDefault(orientation=LabelOrientation.ACROSS, preset=QlLayoutPreset.STANDARD)
    }


@pytest.mark.parametrize(
    "value",
    [
        {"12": {"orientation": "across"}},
        {"29": {"preset": "compact"}},
        {"62": {"orientation": "sideways"}},
        {"62": {"preset": "huge"}},
        {"62": {"orientation": "across", "extra": 1}},
        {"0": {"orientation": "along"}},
        {"63": {"orientation": "along"}},
        {"100000": {"orientation": "along"}},
        {str(w): {"orientation": "along"} for w in range(1, 18)},  # 17 widths
    ],
)
def test_update_payload_rejects_invalid_defaults(value: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PrinterUpdatePayload.model_validate({"layout_defaults": value})


def test_sixteen_widths_up_to_62mm_are_accepted() -> None:
    value = {str(w): {"orientation": "along"} for w in range(47, 62)}
    value["62"] = {"orientation": "across", "preset": "compact"}
    patch = PrinterUpdatePayload.model_validate({"layout_defaults": value})
    assert patch.layout_defaults is not None and len(patch.layout_defaults) == 16


def test_create_and_update_store_json_with_string_keys() -> None:
    payload = PrinterCreatePayload.model_validate(
        {**_QL, "layout_defaults": {"62": {"orientation": "along"}}}
    )
    row = _payload_to_row(payload, uuid4(), datetime.now(UTC))
    assert row["layout_defaults"] == {"62": {"orientation": "along", "preset": None}}

    changes = _apply_update_patch(
        row,
        PrinterUpdatePayload.model_validate({"layout_defaults": {"62": {"preset": "small_qr"}}}),
    )
    assert changes == {"layout_defaults": {"62": {"orientation": None, "preset": "small_qr"}}}
    assert _apply_update_patch(row, PrinterUpdatePayload()) == {}


def test_create_without_defaults_stores_an_empty_object() -> None:
    row = _payload_to_row(PrinterCreatePayload.model_validate(_QL), uuid4(), datetime.now(UTC))
    assert row["layout_defaults"] == {}


def test_read_and_audit_show_the_stored_defaults() -> None:
    printer = Printer(
        id=uuid4(),
        name="QL",
        slug="ql",
        model="QL-820NWB",
        backend="brother_ql",
        connection={"host": "192.0.2.11"},
        layout_defaults={"62": {"orientation": "across", "preset": "compact"}},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    read = _row_to_read(printer)
    assert read.layout_defaults == {
        "62": LayoutDefault(orientation=LabelOrientation.ACROSS, preset=QlLayoutPreset.COMPACT)
    }
    view = _row_to_audit_view(_printer_to_row_dict(printer))
    assert view["layout_defaults"] == {"62": {"orientation": "across", "preset": "compact"}}
