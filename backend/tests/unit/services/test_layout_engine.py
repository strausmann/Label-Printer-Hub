"""Unit tests for LayoutEngine — skeleton + validation + dispatch."""

from __future__ import annotations

import pytest
from app.printer_backends.exceptions import (
    ContentTypeDataMismatchError,
    UnsupportedTapeError,
)
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.schemas.label_data_item import LabelDataItem
from app.services.layout_engine import LayoutEngine


class TestLayoutEngineLookup:
    def test_unsupported_tape_raises(self) -> None:
        eng = LayoutEngine()
        with pytest.raises(UnsupportedTapeError) as exc_info:
            eng.render(
                tape_mm=36,
                content_type=ContentType.QR_ONLY,
                data=LabelData(source_app="manual", qr_payload="x"),
            )
        assert exc_info.value.tape_mm == 36


class TestLayoutEngineValidation:
    def test_qr_only_requires_qr_payload(self) -> None:
        eng = LayoutEngine()
        with pytest.raises(ContentTypeDataMismatchError) as exc_info:
            eng.render(
                tape_mm=12,
                content_type=ContentType.QR_ONLY,
                data=LabelData(source_app="manual"),
            )
        assert "qr_payload" in exc_info.value.missing_fields

    def test_qr_two_lines_requires_all_three(self) -> None:
        eng = LayoutEngine()
        with pytest.raises(ContentTypeDataMismatchError) as exc_info:
            eng.render(
                tape_mm=12,
                content_type=ContentType.QR_TWO_LINES,
                data=LabelData(source_app="manual", primary_id="x"),
            )
        assert set(exc_info.value.missing_fields) >= {"qr_payload", "title"}

    def test_qr_three_lines_requires_secondary(self) -> None:
        eng = LayoutEngine()
        with pytest.raises(ContentTypeDataMismatchError) as exc_info:
            eng.render(
                tape_mm=18,
                content_type=ContentType.QR_THREE_LINES,
                data=LabelData(
                    source_app="grocy",
                    primary_id="X",
                    title="Y",
                    qr_payload="Z",
                    secondary=(),
                ),
            )
        assert "secondary" in exc_info.value.missing_fields

    def test_text_one_line_only_needs_primary_id(self) -> None:
        eng = LayoutEngine()
        with pytest.raises(ContentTypeDataMismatchError) as exc_info:
            eng.render(
                tape_mm=12,
                content_type=ContentType.TEXT_ONE_LINE,
                data=LabelData(source_app="manual"),
            )
        assert exc_info.value.missing_fields == ("primary_id",)

    def test_qr_with_listing_requires_items_and_qr(self) -> None:
        eng = LayoutEngine()
        with pytest.raises(ContentTypeDataMismatchError) as exc_info:
            eng.render(
                tape_mm=12,
                content_type=ContentType.QR_WITH_LISTING,
                data=LabelData(source_app="hangar", primary_id="K02"),
            )
        assert "qr_payload" in exc_info.value.missing_fields
        assert "items" in exc_info.value.missing_fields

    def test_qr_with_listing_with_items_passes_validation_but_render_not_implemented(self) -> None:
        eng = LayoutEngine()
        with pytest.raises(NotImplementedError):
            eng.render(
                tape_mm=12,
                content_type=ContentType.QR_WITH_LISTING,
                data=LabelData(
                    source_app="hangar",
                    primary_id="K02",
                    qr_payload="https://example.com/k02",
                    items=(LabelDataItem(item="A"),),
                ),
            )
