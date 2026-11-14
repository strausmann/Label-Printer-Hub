# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for ContentType enum."""

from __future__ import annotations

from app.schemas.content_type import ContentType


class TestContentType:
    def test_all_seven_values_defined(self) -> None:
        assert {c.value for c in ContentType} == {
            "qr_only",
            "qr_one_line",
            "qr_two_lines",
            "qr_three_lines",
            "text_one_line",
            "text_two_lines",
            "qr_with_listing",
        }

    def test_string_value_round_trip(self) -> None:
        assert ContentType("qr_two_lines") == ContentType.QR_TWO_LINES
        assert ContentType.QR_TWO_LINES.value == "qr_two_lines"
