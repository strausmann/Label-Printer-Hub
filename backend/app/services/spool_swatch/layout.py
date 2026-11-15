# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tiers, thresholds and positions of the swatch label (#346, R-346-2, R-346-8).

The tier is the first whose width and height the content box meets (both >=, in hmm), decided
once from the box and handed to the renderer. ``swatch_layout`` gives every element an absolute
position in hmm relative to the content box; nothing depends on the spool's data or on a
resolution. The QR box is fixed per tier, so ``check_item_fits``, the preview and the print use
one box whatever rows a spool has.
"""

from __future__ import annotations

from enum import StrEnum
from typing import NamedTuple

from app.printer_backends.exceptions import ContentTypeDataMismatchError
from app.services.spool_swatch.metrics import SwatchMetrics


class SwatchTier(StrEnum):
    FULL = "full"
    """Everything, with the footer."""
    NO_FOOTER = "no_footer"
    FIRST_COLUMN = "first_column"
    """Without the footer and column 2."""
    CORE = "core"
    """Vendor, bar, colour, hex line, QR and caption."""


def _left_part(m: SwatchMetrics, lines: int) -> int:
    return m.vendor_block + m.bar_h + m.colour_gap + m.colour_h + lines * m.row_pitch


def _qr_column(m: SwatchMetrics, edge: int) -> int:
    return m.vendor_block + m.bar_h + edge + m.row_pitch


def tier_thresholds(metrics: SwatchMetrics) -> tuple[tuple[SwatchTier, int, int], ...]:
    """(tier, minimum width, minimum height) in hmm, in the order the tiers are tried."""
    m = metrics
    columns = m.column_1 + m.column_gap + m.column_2 + m.qr_gap
    two = _left_part(m, m.lines_two_columns)
    return (
        (
            SwatchTier.FULL,
            columns + m.q_full,
            max(two, _qr_column(m, m.q_full)) + m.footer,
        ),
        (SwatchTier.NO_FOOTER, columns + m.q_min, max(two, _qr_column(m, m.q_min))),
        (
            SwatchTier.FIRST_COLUMN,
            m.column_1 + m.qr_gap + m.q_min,
            max(_left_part(m, m.lines_first_column), _qr_column(m, m.q_min)),
        ),
        (
            SwatchTier.CORE,
            m.c_min + m.qr_gap + m.q_min,
            max(_left_part(m, 1), m.q_min + m.row_pitch),
        ),
    )


def swatch_tier(box_w_hmm: int, box_h_hmm: int, metrics: SwatchMetrics) -> SwatchTier | None:
    """The first tier whose width and height the box meets; ``None`` below ``core``."""
    for tier, width, height in tier_thresholds(metrics):
        if box_w_hmm >= width and box_h_hmm >= height:
            return tier
    return None


class SwatchLayout(NamedTuple):
    """Absolute positions in hmm relative to the content box; data- and resolution-free."""

    tier: SwatchTier
    box_w: int
    box_h: int
    qr_box: tuple[int, int, int]
    """(x, y, edge) of the square QR box; the quiet zone lies inside it."""
    left_w: int
    """Width of the part left of the QR column (colour line, ``core``'s bar and hex line)."""
    vendor_baselines: tuple[int, ...]
    """Baselines of the vendor lines at the vendor cap (tape: two, the second reserved)."""
    vendor_row_baselines: tuple[int, int]
    """Baselines of the two rows at the row cap inside the vendor block (bottom-aligned)."""
    bar: tuple[int, int, int, int]
    """(x, y, w, h) of the black bar."""
    bar_baseline: int
    colour_baselines: tuple[int, int]
    """First colour line and the line it may wrap onto (3.0 mm lower)."""
    colour_bottom: int
    columns: tuple[tuple[int, int], ...]
    """(x, width) of each value column the tier shows."""
    rows_bottom: int
    """Bottom of the rows region: the box bottom, or the footer rule on ``full``."""
    row_lines: int
    """Lines the value columns may use (6, 5 on ``first_column``, 0 on ``core``)."""
    footer_rule: tuple[int, int] | None
    """(y, thickness) of the footer rule on ``full``."""
    footer_baseline: int | None
    caption_baseline: int
    caption_slot: tuple[int, int]
    """(x, width) the caption may use: the QR box and the 0.8 mm gap left of it."""


def swatch_layout(
    tier: SwatchTier, box_w_hmm: int, box_h_hmm: int, metrics: SwatchMetrics
) -> SwatchLayout:
    """Positions of every element for ``tier`` in a ``box_w_hmm`` x ``box_h_hmm`` content box."""
    m = metrics
    w, h = box_w_hmm, box_h_hmm
    v, b = m.vendor_block, m.bar_h
    footer = m.footer if tier is SwatchTier.FULL else 0
    if tier is SwatchTier.CORE:
        edge = min(h - m.row_pitch, w - m.c_min - m.qr_gap, m.q_max)
        qr_y = 0
        columns: tuple[tuple[int, int], ...] = ()
        lines = 0
    else:
        lower = h - footer - v - b
        if tier is SwatchTier.FIRST_COLUMN:
            room = w - m.column_1 - m.qr_gap
            columns = ((0, m.column_1),)
            lines = m.lines_first_column
        else:
            room = w - m.column_1 - m.column_gap - m.column_2 - m.qr_gap
            columns = ((0, m.column_1), (m.column_1 + m.column_gap, m.column_2))
            lines = m.lines_two_columns
        edge = min(lower - m.row_pitch, room, m.q_max)
        qr_y = v + b
    qr_x = w - edge
    left_w = qr_x - m.qr_gap
    bar_w = left_w if tier is SwatchTier.CORE else w
    colour_top = v + b + m.colour_gap
    colour_bottom = colour_top + m.colour_h
    first_colour = colour_bottom - m.colour_baseline
    return SwatchLayout(
        tier=tier,
        box_w=w,
        box_h=h,
        qr_box=(qr_x, qr_y, edge),
        left_w=left_w,
        vendor_baselines=tuple(
            (i + 1) * m.vendor_line - m.vendor_baseline for i in range(m.vendor_lines)
        ),
        vendor_row_baselines=(v - m.row_pitch - m.row_baseline, v - m.row_baseline),
        bar=(0, v, bar_w, b),
        bar_baseline=v + b - m.bar_baseline,
        colour_baselines=(first_colour, first_colour + m.colour_h),
        colour_bottom=colour_bottom,
        columns=columns,
        rows_bottom=h - footer,
        row_lines=lines,
        footer_rule=(h - m.footer, m.footer_rule) if footer else None,
        footer_baseline=h - m.row_baseline if footer else None,
        caption_baseline=qr_y + edge + m.row_pitch - m.row_baseline,
        caption_slot=(qr_x - m.qr_gap, edge + m.qr_gap),
    )


def layout_for_box(box_w_hmm: int, box_h_hmm: int, metrics: SwatchMetrics) -> SwatchLayout:
    """The tier and layout of a content box; below ``core`` the label does not fit.

    Raises:
        ContentTypeDataMismatchError: ``missing_fields=("label_size",)`` below ``core``.
    """
    tier = swatch_tier(box_w_hmm, box_h_hmm, metrics)
    if tier is None:
        raise ContentTypeDataMismatchError(
            content_type="spool_swatch", missing_fields=("label_size",)
        )
    return swatch_layout(tier, box_w_hmm, box_h_hmm, metrics)
