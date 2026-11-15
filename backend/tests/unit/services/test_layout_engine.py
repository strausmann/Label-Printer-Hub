# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

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

    def test_qr_with_listing_with_items_passes_validation(self) -> None:
        """Validation passes with non-empty items; render returns a PIL Image."""
        eng = LayoutEngine()
        img = eng.render(
            tape_mm=12,
            content_type=ContentType.QR_WITH_LISTING,
            data=LabelData(
                source_app="hangar",
                primary_id="K02",
                qr_payload="https://example.com/k02",
                items=(LabelDataItem(item="A"),),
            ),
        )
        assert img is not None
        assert img.height == 70  # 12mm printable_px


# ---------------------------------------------------------------------------
# #346: the swatch label on tape
# ---------------------------------------------------------------------------


def _swatch_data() -> LabelData:
    from tests.helpers.spool_swatch import SAMPLE_URL, every_row

    return LabelData(source_app="spoolman", qr_payload=SAMPLE_URL, swatch=every_row())


def test_swatch_on_62_is_696_by_425() -> None:
    from app.services.spool_swatch import render_tape_swatch

    image = LayoutEngine().render(62, ContentType.SPOOL_SWATCH, _swatch_data())
    assert image.size == (696, 425)
    data = _swatch_data()
    assert image.tobytes() == render_tape_swatch(data.swatch, data.qr_payload).tobytes()  # type: ignore[arg-type]


def test_swatch_ignores_orientation_and_preset() -> None:
    from app.schemas.label_layout import LabelOrientation, QlLayoutPreset

    engine = LayoutEngine()
    plain = engine.render(62, ContentType.SPOOL_SWATCH, _swatch_data())
    turned = engine.render(
        62,
        ContentType.SPOOL_SWATCH,
        _swatch_data(),
        orientation=LabelOrientation.ALONG,
        preset=QlLayoutPreset.STANDARD,
    )
    assert turned.tobytes() == plain.tobytes()


@pytest.mark.parametrize("tape_mm", [29, 38, 50, 54])
def test_swatch_on_the_other_dk_widths(tape_mm: int) -> None:
    from app.services.spool_swatch import render_tape_swatch

    data = _swatch_data()
    image = LayoutEngine().render(tape_mm, ContentType.SPOOL_SWATCH, data)
    assert image.tobytes() == render_tape_swatch(data.swatch, data.qr_payload, tape_mm).tobytes()  # type: ignore[arg-type]


def test_swatch_on_12mm_is_unsupported() -> None:
    with pytest.raises(UnsupportedTapeError) as exc:
        LayoutEngine().render(12, ContentType.SPOOL_SWATCH, _swatch_data())
    assert exc.value.tape_mm == 12


def test_swatch_without_swatch_data_is_a_mismatch() -> None:
    data = LabelData(source_app="manual", qr_payload="https://x.example/1", title="t")
    with pytest.raises(ContentTypeDataMismatchError) as exc:
        LayoutEngine().render(62, ContentType.SPOOL_SWATCH, data)
    assert exc.value.missing_fields == ("swatch",)
