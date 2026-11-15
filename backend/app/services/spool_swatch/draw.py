# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Placing and drawing the swatch label (#346, R-346-2, R-346-7a, R-346-9, R-346-11).

``place_swatch`` decides every text of one spool in hmm (which lines, which cap, where);
``render_swatch`` draws that placement at one resolution. It is the one function behind the
tape job, the tape preview, the raw print, the sheet job and the sheet preview, so preview and
print cannot drift apart.
"""

from __future__ import annotations

import math
from typing import Final, NamedTuple

import qrcode
import qrcode.constants
import qrcode.exceptions
import qrcode.util
from PIL import Image, ImageDraw

from app.printer_backends.exceptions import QrPayloadTooLongError
from app.schemas.label_layout import LabelOrientation
from app.schemas.spool_swatch import SpoolSwatch
from app.services.spool_swatch import font
from app.services.spool_swatch.font import Weight, text_mm, to_px
from app.services.spool_swatch.layout import SwatchLayout, SwatchTier, layout_for_box
from app.services.spool_swatch.metrics import (
    TAPE_METRICS,
    FittedText,
    SwatchMetrics,
    fit_text,
    label_slot,
)
from app.services.spool_swatch.text import swatch_text

SWATCH_TAPE_PX: Final = (696, 425)
"""The across image on 62 mm endless: 62 x 36.0 mm at 300 dpi (R-346-9)."""
SWATCH_TAPE_MARGIN_PX: Final = 12
"""``round(1.0 mm x 300 / 25.4)`` per side."""
SWATCH_TAPE_DPI: Final = 300
INK_THRESHOLD: Final = 115  # as the tape layouts (``ql_layout.INK_THRESHOLD``)
_QUIET_MODULES: Final = 2


class Run(NamedTuple):
    """One glyph run to draw: pen origin x and baseline in hmm."""

    x: float
    baseline: int
    text: str
    weight: Weight
    cap_mm: float
    fill: int


class PlacedRow(NamedTuple):
    label: tuple[str, ...]
    value: tuple[str, ...]
    baselines: tuple[int, ...]
    """Baselines of the row's lines (label and value share the first)."""
    value_baselines: tuple[int, ...]


class PlacedColumn(NamedTuple):
    x: int
    tab: float
    """Where every value of the column starts (hmm)."""
    rows: tuple[PlacedRow, ...]
    lines: int


class SwatchPlacement(NamedTuple):
    layout: SwatchLayout
    vendor: FittedText
    vendor_slot: int
    title: FittedText
    colour: FittedText
    colour_baselines: tuple[int, ...]
    hexes: FittedText
    columns: tuple[PlacedColumn, ...]
    footer: FittedText | None
    caption: FittedText
    runs: tuple[Run, ...]
    truncated: bool


def _width(lines: tuple[str, ...], weight: Weight, cap: float) -> float:
    return max((text_mm(t, weight, cap) for t in lines), default=0.0) * 100


def _place_columns(
    swatch_rows: tuple[tuple[tuple[str, str], ...], ...],
    layout: SwatchLayout,
    m: SwatchMetrics,
    language: str,
) -> tuple[list[tuple[int, int, list[tuple[FittedText, FittedText, int]]]], bool]:
    """Fit labels and values of each shown column; returns (x, lines, rows) per column."""
    placed: list[tuple[int, int, list[tuple[FittedText, FittedText, int]]]] = []
    truncated = False
    for index, (x, width) in enumerate(layout.columns):
        rows = swatch_rows[index]
        slot = label_slot(m, 1 if index == 0 else 2)
        labels = [
            fit_text("label", label, slot_hmm=slot, free_lines=2, metrics=m, language=language)
            for label, _ in rows
        ]
        widest = max((_width(lab.lines, 700, m.row_cap_mm) for lab in labels), default=0.0)
        tab = x + widest + m.run_margin + m.tab_gap
        value_slot = math.floor(x + width - tab - m.run_margin)
        budget = layout.row_lines - sum(max(1, len(lab.lines)) for lab in labels)
        fitted: list[tuple[FittedText, FittedText, int]] = []
        for lab, (_, value) in zip(labels, rows, strict=True):
            own = max(1, len(lab.lines))
            val = fit_text(
                "value",
                value,
                slot_hmm=value_slot,
                free_lines=own + max(0, budget),
                metrics=m,
                language=language,
            )
            used = max(own, len(val.lines))
            budget -= used - own
            truncated = truncated or lab.truncated or val.truncated
            fitted.append((lab, val, used))
        placed.append((x, sum(u for _, _, u in fitted), fitted))
    return placed, truncated


def place_swatch(
    swatch: SpoolSwatch, layout: SwatchLayout, metrics: SwatchMetrics
) -> SwatchPlacement:
    """Every text of ``swatch`` fitted and positioned in hmm for ``layout`` (R-346-7a)."""
    m = metrics
    lay = layout
    lang = swatch.language
    texts = swatch_text(swatch)
    runs: list[Run] = []
    core = lay.tier is SwatchTier.CORE

    # Value columns: labels wrap, values wrap while the column has free lines, then cut.
    columns_rows = (texts.column_1, texts.column_2)
    fitted_columns, truncated = _place_columns(columns_rows, lay, m, lang)
    used_lines = max((lines for _, lines, _ in fitted_columns), default=0)
    rows_top = lay.rows_bottom - used_lines * m.row_pitch
    columns: list[PlacedColumn] = []
    for (x, lines, fitted), (_, width) in zip(fitted_columns, lay.columns, strict=True):
        labels_w = max((_width(lab.lines, 700, m.row_cap_mm) for lab, _, _ in fitted), default=0)
        tab = x + labels_w + m.run_margin + m.tab_gap
        line = 0
        rows: list[PlacedRow] = []
        for lab, val, used in fitted:
            baselines = tuple(
                rows_top + (line + k + 1) * m.row_pitch - m.row_baseline for k in range(used)
            )
            rows.append(PlacedRow(lab.lines, val.lines, baselines, baselines[: len(val.lines)]))
            for text, base in zip(lab.lines, baselines, strict=False):
                runs.append(Run(x, base, text, 700, m.row_cap_mm, 0))
            for text, base in zip(val.lines, baselines, strict=False):
                runs.append(Run(tab, base, text, 400, m.row_cap_mm, 0))
            line += used
        del width
        columns.append(PlacedColumn(x, tab, tuple(rows), lines))

    # Hex codes: top right in the vendor block (upper tiers), or a line under the colour (core).
    if core:
        hex_rows_room = (lay.box_h - lay.colour_bottom) // m.row_pitch
        hexes = fit_text(
            "hex_line",
            texts.hexes,
            slot_hmm=lay.left_w,
            free_lines=hex_rows_room,
            metrics=m,
            language=lang,
        )
        free = lay.box_h - lay.colour_bottom - len(hexes.lines) * m.row_pitch
        vendor_slot = lay.left_w
    else:
        hexes = fit_text(
            "hex_block",
            texts.hexes,
            slot_hmm=lay.box_w - m.hex_gap - m.vendor_min,
            free_lines=2,
            metrics=m,
            language=lang,
        )
        free = rows_top - lay.colour_bottom
        hex_w = round(_width(hexes.lines, 400, m.row_cap_mm))
        vendor_slot = lay.box_w - hex_w - m.hex_gap if hexes.lines else lay.box_w
        baselines = lay.vendor_row_baselines[2 - len(hexes.lines) :]
        for text, base in zip(hexes.lines, baselines, strict=True):
            right = lay.box_w - text_mm(text, 400, m.row_cap_mm) * 100 - m.run_margin
            runs.append(Run(right, base, text, 400, m.row_cap_mm, 0))

    # Colour line: a second line only where the left part has 3.0 mm free under it.
    colour = fit_text(
        "colour",
        texts.color_name,
        slot_hmm=lay.left_w,
        free_lines=2 if free >= m.colour_h else 1,
        metrics=m,
        language=lang,
    )
    colour_baselines = lay.colour_baselines[: len(colour.lines)]
    for text, base in zip(colour.lines, colour_baselines, strict=True):
        runs.append(Run(0, base, text, 700, colour.cap_mm, 0))
    if core:
        shift = (len(colour.lines) - 1) * m.colour_h if colour.lines else 0
        for k, text in enumerate(hexes.lines):
            base = lay.colour_bottom + shift + (k + 1) * m.row_pitch - m.row_baseline
            runs.append(Run(0, base, text, 400, m.row_cap_mm, 0))

    # Vendor: wrap (two lines on tape, two rows on sheets), shrink, cut.
    vendor = fit_text(
        "vendor", texts.vendor, slot_hmm=vendor_slot, free_lines=2, metrics=m, language=lang
    )
    if len(vendor.lines) == 2:
        vendor_bases = lay.vendor_baselines if m.vendor_lines >= 2 else lay.vendor_row_baselines
    else:
        vendor_bases = lay.vendor_baselines[:1]
    for text, base in zip(vendor.lines, vendor_bases, strict=False):
        runs.append(Run(0, base, text, 700, vendor.cap_mm, 0))

    # Bar title, white, inset 0.6 mm inside the bar.
    bar_x, _, bar_w, _ = lay.bar
    title = fit_text(
        "title",
        texts.title,
        slot_hmm=bar_w - 2 * m.bar_inset,
        free_lines=1,
        metrics=m,
        language=lang,
    )
    for text in title.lines:
        runs.append(Run(bar_x + m.bar_inset, lay.bar_baseline, text, 700, title.cap_mm, 255))

    footer: FittedText | None = None
    if lay.footer_baseline is not None:
        footer = fit_text(
            "footer", texts.footer, slot_hmm=lay.box_w, free_lines=1, metrics=m, language=lang
        )
        for text in footer.lines:
            runs.append(Run(0, lay.footer_baseline, text, 400, m.row_cap_mm, 0))

    slot_x, slot_w = lay.caption_slot
    caption = fit_text(
        "caption", texts.caption, slot_hmm=slot_w, free_lines=1, metrics=m, language=lang
    )
    qr_x, _, edge = lay.qr_box
    for text in caption.lines:
        span = text_mm(text, 400, m.row_cap_mm) * 100
        start = min(qr_x + (edge - span) / 2, qr_x + edge - span - m.run_margin)
        runs.append(Run(max(slot_x, start), lay.caption_baseline, text, 400, m.row_cap_mm, 0))

    truncated = (
        truncated
        or vendor.truncated
        or title.truncated
        or colour.truncated
        or hexes.truncated
        or caption.truncated
        or (footer is not None and footer.truncated)
    )
    return SwatchPlacement(
        layout=lay,
        vendor=vendor,
        vendor_slot=vendor_slot,
        title=title,
        colour=colour,
        colour_baselines=colour_baselines,
        hexes=hexes,
        columns=tuple(columns),
        footer=footer,
        caption=caption,
        runs=tuple(runs),
        truncated=truncated,
    )


def _byte_capacity_m(version: int) -> int:
    bits = qrcode.util.BIT_LIMIT_TABLE[qrcode.constants.ERROR_CORRECT_M][version]
    count_bits = qrcode.util.length_in_bits(qrcode.util.MODE_8BIT_BYTE, version)
    return int((bits - 4 - count_bits) // 8)


def swatch_symbol(
    payload: str, box_px: int, *, mask: int | None = None
) -> tuple[Image.Image, int] | None:
    """The QR ink (no quiet zone) for a ``box_px`` square, and its module size in px.

    Error correction M, the smallest version; ``module = box_px // (modules + 4)`` whole pixels
    (two quiet modules each side lie inside the box). ``None`` when no version fits with
    modules of at least one pixel. ``mask`` as ``cell_render.build_qr``'s.
    """
    from app.sheets.cell_render import qr_version

    version = qr_version(payload)
    if version is None:
        return None
    modules = 17 + 4 * version
    module = box_px // (modules + 2 * _QUIET_MODULES)
    if module < 1:
        return None
    qr = qrcode.QRCode(
        version=version,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        border=0,
        mask_pattern=mask,
    )
    try:
        qr.add_data(payload)
        qr.make(fit=False)
    except (qrcode.exceptions.DataOverflowError, ValueError):
        return None
    matrix = qr.get_matrix()
    flat = bytes(0 if dark else 255 for row in matrix for dark in row)
    side = len(matrix)
    image = Image.frombytes("L", (side, side), flat).resize(
        (side * module, side * module), Image.Resampling.NEAREST
    )
    return image.convert("1"), module


def _too_long(payload: str, box_px: int) -> QrPayloadTooLongError:
    version = min(40, (box_px - 2 * _QUIET_MODULES - 17) // 4)
    capacity = _byte_capacity_m(version) if version >= 1 else 0
    return QrPayloadTooLongError(length=len(payload.encode("utf-8")), max_bytes=capacity)


def render_swatch(
    swatch: SpoolSwatch,
    qr_payload: str,
    *,
    layout: SwatchLayout,
    width_px: int,
    height_px: int,
    dpi: int,
    metrics: SwatchMetrics,
    qr_mask: int | None = None,
) -> tuple[Image.Image, bool]:
    """The label as a 1-bit image of exactly ``width_px`` x ``height_px``; second value: cut.

    Raises:
        QrDoesNotFitError: sheet metrics, no QR version fits the box.
        QrPayloadTooLongError: tape metrics, no QR version fits the box.
    """
    qr_x, qr_y, edge = layout.qr_box
    box_px = to_px(edge, dpi)
    symbol = swatch_symbol(qr_payload, box_px, mask=qr_mask)
    if symbol is None:
        if metrics.name == TAPE_METRICS.name:
            raise _too_long(qr_payload, box_px)
        from app.sheets.cell_render import QrDoesNotFitError

        raise QrDoesNotFitError(content_type="spool_swatch")
    placement = place_swatch(swatch, layout, metrics)
    canvas = Image.new("L", (width_px, height_px), 255)
    draw = ImageDraw.Draw(canvas)
    bx, by, bw, bh = layout.bar
    draw.rectangle(
        (to_px(bx, dpi), to_px(by, dpi), to_px(bx + bw, dpi) - 1, to_px(by + bh, dpi) - 1), fill=0
    )
    if layout.footer_rule is not None:
        y, thick = layout.footer_rule
        draw.rectangle((0, to_px(y, dpi), width_px - 1, to_px(y + thick, dpi) - 1), fill=0)
    for run in placement.runs:
        font.draw_glyphs(
            draw,
            run.x,
            run.baseline,
            run.text,
            weight=run.weight,
            cap_mm=run.cap_mm,
            dpi=dpi,
            fill=run.fill,
        )
    image, module = symbol
    canvas.paste(
        image.convert("L"),
        (to_px(qr_x, dpi) + (box_px - image.width) // 2, to_px(qr_y, dpi) + 2 * module),
    )
    return canvas.point(lambda v: 0 if v < INK_THRESHOLD else 255, "1"), placement.truncated


def tape_box_hmm() -> tuple[int, int]:
    """Content box of the 62 mm tape image in hmm (5690 x 3395)."""
    w, h = SWATCH_TAPE_PX
    inner = (w - 2 * SWATCH_TAPE_MARGIN_PX, h - 2 * SWATCH_TAPE_MARGIN_PX)
    return round(inner[0] * 2540 / SWATCH_TAPE_DPI), round(inner[1] * 2540 / SWATCH_TAPE_DPI)


def render_tape_swatch(swatch: SpoolSwatch, qr_payload: str) -> Image.Image:
    """The 696 x 425 across image for 62 mm endless (R-346-9), tier ``full``."""
    w, h = SWATCH_TAPE_PX
    margin = SWATCH_TAPE_MARGIN_PX
    box = tape_box_hmm()
    image, _ = render_swatch(
        swatch,
        qr_payload,
        layout=layout_for_box(*box, TAPE_METRICS),
        width_px=w - 2 * margin,
        height_px=h - 2 * margin,
        dpi=SWATCH_TAPE_DPI,
        metrics=TAPE_METRICS,
    )
    canvas = Image.new("1", (w, h), 1)
    canvas.paste(image, (margin, margin))
    return canvas


def swatch_for_batch(image: Image.Image, batch_orientation: LabelOrientation | None) -> Image.Image:
    """The swatch's across image as handed to the backend in a batch of ``batch_orientation``.

    The QL backend turns every image of an ``along`` batch with ``ROTATE_270``; the swatch is
    turned the other way first, so the printed bitmap equals the across image.
    """
    if batch_orientation is LabelOrientation.ALONG:
        return image.transpose(Image.Transpose.ROTATE_90)
    return image
