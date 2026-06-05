"""Unit tests for TapeGeometry model and TAPE_GEOMETRY constants table."""

from __future__ import annotations

import pytest
from app.schemas.tape_geometry import TAPE_GEOMETRY, TapeGeometry


class TestTapeGeometryModel:
    def test_valid_values_accepted(self) -> None:
        geom = TapeGeometry(
            printable_px=70,
            qr_max_px=66,
            qr_padding_px=2,
            text_start_x=72,
            line_spacing_px=4,
            font_xl=22,
            font_l=18,
            font_m=14,
            font_s=10,
        )
        assert geom.printable_px == 70

    def test_zero_printable_px_rejected(self) -> None:
        with pytest.raises(ValueError, match="greater than 0"):
            TapeGeometry(
                printable_px=0,
                qr_max_px=66,
                qr_padding_px=2,
                text_start_x=72,
                line_spacing_px=4,
                font_xl=22,
                font_l=18,
                font_m=14,
                font_s=10,
            )

    def test_negative_qr_padding_rejected(self) -> None:
        with pytest.raises(ValueError, match="greater than or equal to 0"):
            TapeGeometry(
                printable_px=70,
                qr_max_px=66,
                qr_padding_px=-1,
                text_start_x=72,
                line_spacing_px=4,
                font_xl=22,
                font_l=18,
                font_m=14,
                font_s=10,
            )

    def test_frozen_immutable(self) -> None:
        geom = TapeGeometry(
            printable_px=70,
            qr_max_px=66,
            qr_padding_px=2,
            text_start_x=72,
            line_spacing_px=4,
            font_xl=22,
            font_l=18,
            font_m=14,
            font_s=10,
        )
        with pytest.raises(ValueError):
            geom.printable_px = 100  # type: ignore[misc]


class TestTapeGeometryConstants:
    def test_all_seven_sizes_defined(self) -> None:
        assert set(TAPE_GEOMETRY.keys()) == {4, 6, 9, 12, 18, 24, 62}

    def test_12mm_v4_winner_values(self) -> None:
        geom = TAPE_GEOMETRY[12]
        assert geom.printable_px == 70
        assert geom.qr_max_px == 66
        assert geom.text_start_x == 72
        assert geom.font_xl == 22
        assert geom.font_l == 18

    def test_qr_max_px_follows_formula(self) -> None:
        """qr_max_px = printable_px - 2 * qr_padding_px"""
        for tape_mm, geom in TAPE_GEOMETRY.items():
            expected = geom.printable_px - 2 * geom.qr_padding_px
            assert geom.qr_max_px == expected, (
                f"{tape_mm}mm: qr_max_px={geom.qr_max_px} expected {expected}"
            )

    def test_text_start_x_follows_formula(self) -> None:
        """text_start_x = printable_px + qr_padding_px"""
        for tape_mm, geom in TAPE_GEOMETRY.items():
            expected = geom.printable_px + geom.qr_padding_px
            assert geom.text_start_x == expected, (
                f"{tape_mm}mm: text_start_x={geom.text_start_x} expected {expected}"
            )
