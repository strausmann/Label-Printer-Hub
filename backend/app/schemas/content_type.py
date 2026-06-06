"""Semantic content types — tape-independent label descriptions.

Each ContentType describes WHAT is rendered (QR + N text lines, or listing,
or text-only). The renderer (LayoutEngine) consumes (tape_mm, content_type,
data) and produces a PIL Image — pixel positions are computed from the
TapeGeometry table, not from the ContentType.
"""

from __future__ import annotations

from enum import StrEnum


class ContentType(StrEnum):
    """Tape-independent semantic content types for label rendering."""

    QR_ONLY = "qr_only"
    """QR fills the full tape height; no text."""

    QR_ONE_LINE = "qr_one_line"
    """QR left + 1 text line (XL, vertically centered): qr_payload + primary_id."""

    QR_TWO_LINES = "qr_two_lines"
    """QR left + 2 text lines (XL primary_id + L title)."""

    QR_THREE_LINES = "qr_three_lines"
    """QR left + 3 text lines (XL primary_id + L title + S secondary[0])."""

    TEXT_ONE_LINE = "text_one_line"
    """Full-width text XL (primary_id); no QR."""

    TEXT_TWO_LINES = "text_two_lines"
    """2 text lines (XL primary_id + L title); no QR."""

    QR_WITH_LISTING = "qr_with_listing"
    """QR + N item lines (M font); overflow shows "+N more"."""
