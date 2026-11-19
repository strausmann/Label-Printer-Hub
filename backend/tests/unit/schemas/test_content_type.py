# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for ContentType enum."""

from __future__ import annotations

from app.schemas.content_type import ContentType, has_qr


class TestContentType:
    def test_all_eight_values_defined(self) -> None:
        assert {c.value for c in ContentType} == {
            "qr_only",
            "qr_one_line",
            "qr_two_lines",
            "qr_three_lines",
            "text_one_line",
            "text_two_lines",
            "qr_with_listing",
            "spool_swatch",
        }

    def test_string_value_round_trip(self) -> None:
        assert ContentType("qr_two_lines") == ContentType.QR_TWO_LINES
        assert ContentType.QR_TWO_LINES.value == "qr_two_lines"

    def test_has_qr(self) -> None:
        with_qr = {c for c in ContentType if has_qr(c)}
        assert with_qr == {
            ContentType.QR_ONLY,
            ContentType.QR_ONE_LINE,
            ContentType.QR_TWO_LINES,
            ContentType.QR_THREE_LINES,
            ContentType.QR_WITH_LISTING,
            ContentType.SPOOL_SWATCH,
        }
