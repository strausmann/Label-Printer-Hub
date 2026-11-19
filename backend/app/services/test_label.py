# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The test label of a tape printer, drawn on every tape the printer takes (#377, R-377-1).

The label has its own renderer and never goes through the ``LayoutEngine``: the layout engine
knows the content types and the tapes they are designed for, the test label has to come out on
every tape a model takes. It always runs **along** the tape, as a band whose height is the
printable band of the model and tape (``test_label_band``), at the model's resolution.

On the band, from the bottom up: a 50 mm ruler (ticks every 1, 5 and 10 mm; numbers every 10 mm
from 12 mm tape on), then the text (the printer's name, the tape width, the date and the hub's
version, as many lines as fit) and, from 29 mm tape on, a QR code to the printer's page when its
modules come out at least 0.25 mm. A link too long for the QR leaves the QR out, it never
refuses the label.

Taint boundary: only the fields of ``TapeTestText`` reach the paper; the printer's connection
never does.
"""

from __future__ import annotations

import math
import unicodedata
from dataclasses import asdict, dataclass, fields
from typing import Any, Final, NamedTuple

import qrcode
import qrcode.constants
import qrcode.exceptions
from PIL import Image, ImageDraw

from app.printer_backends.exceptions import UnsupportedTapeError
from app.printer_backends.ptouch_backend import _PTOUCH_PRINTER_CLASSES, _PTOUCH_TAPE_CLASSES
from app.printer_models.ql import QL_DK_ENDLESS_TAPES
from app.services.spool_swatch.font import Weight, draw_glyphs, text_mm

RULER_MM: Final = 50
"""Length of the ruler; its first and last long tick are this far apart."""
RULER_ZONE_MM: Final = 4.0
"""Height of the ruler zone at the bottom of the band (less on a band too narrow for it)."""
QR_MIN_MODULE_MM: Final = 0.25
"""The smallest module that is drawn; a smaller one leaves the QR out."""
QR_QUIET_MODULES: Final = 2
"""Quiet zone of the QR, in modules (a deliberate deviation from the norm's 4, R-377-1)."""
QR_FROM_TAPE_MM: Final = 29
"""The QR is drawn only on tapes at least this wide (QL 29-62 mm, PT 36 mm)."""
MAX_LENGTH_MM: Final = 100
"""The label is never longer than this; a long printer name is shortened to fit."""
NUMBERS_FROM_TAPE_MM: Final = 12
"""The ruler carries numbers and the text runs in lines from this tape width on."""

QL_DPI: Final = 300
_STANDARD_PT: Final = _PTOUCH_PRINTER_CLASSES["PT-E550W"]
"""The pin table of a P-touch model the hub does not know: the 128-pin, 180 dpi standard."""
_MARGIN_MM: Final = 2.0
_GAP_MM: Final = 1.5
_CAP_MAX_MM: Final = 3.5
_MIN_CAP_PX: Final = 8
_LINE_PITCH: Final = 1.5
"""Distance of two baselines, in cap heights."""
_TICK_WIDTH_MM: Final = 0.2
_ELLIPSIS: Final = "…"


class TapeBand(NamedTuple):
    """The printable band across the tape, in device pixels, and the resolution it is at."""

    px: int
    dpi: int


def test_label_band(backend: str, model: str, tape_mm: int) -> TapeBand:
    """The band the test label is drawn on for ``model`` of ``backend`` and ``tape_mm``.

    ``brother_ql``: the DK endless tape's printable dots at 300 dpi, whatever the model.
    ``ptouch``: the pins of the tape in the model's pin table at the model's resolution; a model
    the hub has no pin table for falls back to the standard P-touch pins at 180 dpi
    (``_STANDARD_PT``), so an unknown model never breaks the test print. Any other tape backend
    (``mock``) is treated as QL when the model is a QL, else as P-touch. Raises
    ``UnsupportedTapeError`` only for a width the table in use does not have.
    """
    if backend == "brother_ql" or (backend != "ptouch" and model.upper().startswith("QL")):
        for spec in QL_DK_ENDLESS_TAPES:
            if spec.width_mm == tape_mm:
                return TapeBand(spec.print_area_dots, QL_DPI)
        raise UnsupportedTapeError(tape_mm=tape_mm)
    printer_cls: Any = _PTOUCH_PRINTER_CLASSES.get(model, _STANDARD_PT)
    tape_cls = _PTOUCH_TAPE_CLASSES.get(tape_mm)
    config = printer_cls.PIN_CONFIGS.get(tape_cls) if tape_cls is not None else None
    if config is None:
        raise UnsupportedTapeError(tape_mm=tape_mm)
    return TapeBand(int(config.print_pins), int(printer_cls.RESOLUTION_DPI))


test_label_band.__test__ = False  # type: ignore[attr-defined]  # a function of the hub, not a test


@dataclass(frozen=True)
class TapeTestText:
    """What the test label says; stored with the job so a re-render prints the same label."""

    printer: str
    width_mm: int
    printed_at: str
    """``YYYY-MM-DD HH:MM``."""
    version: str
    qr_payload: str

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> TapeTestText:
        return cls(**{f.name: payload[f.name] for f in fields(cls)})


class LabelPlan(NamedTuple):
    """Where everything goes; ``render_test_label`` draws exactly this."""

    lines: tuple[str, ...]
    cap_px: int
    zone_px: int
    qr_module_px: int
    """0 when no QR is drawn."""
    width_px: int


def _px(mm: float, dpi: int) -> int:
    return round(mm * dpi / 25.4)


def _mm(px: float, dpi: int) -> float:
    return px * 25.4 / dpi


def _text_px(text: str, weight: Weight, cap_px: int, dpi: int) -> int:
    return math.ceil(text_mm(text, weight, _mm(cap_px, dpi)) * dpi / 25.4) + 1


def _qr(payload: str, box_px: int, dpi: int) -> qrcode.QRCode[Any] | None:
    """The QR at the largest module that fits the box with its quiet zone, or ``None``."""
    qr: qrcode.QRCode[Any] = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=1,
        border=QR_QUIET_MODULES,
    )
    qr.add_data(payload)
    try:
        qr.make(fit=True)
    except (qrcode.exceptions.DataOverflowError, ValueError):
        return None  # longer than any QR version holds: the label prints without it
    module_px = box_px // (qr.modules_count + 2 * QR_QUIET_MODULES)
    if module_px < 1 or _mm(module_px, dpi) < QR_MIN_MODULE_MM:
        return None
    qr.box_size = module_px
    return qr


def _shorten(text: str, suffix: str, weight: Weight, cap_px: int, dpi: int, max_px: int) -> str:
    """``text + suffix``, with ``text`` cut and ended with ``…`` until it fits ``max_px``."""
    if _text_px(text + suffix, weight, cap_px, dpi) <= max_px:
        return text + suffix
    for end in range(len(text) - 1, -1, -1):
        if not _is_cut_point(text, end):
            continue
        candidate = text[:end].rstrip() + _ELLIPSIS + suffix
        if _text_px(candidate, weight, cap_px, dpi) <= max_px:
            return candidate
    return _ELLIPSIS + suffix


_JOINERS: Final = frozenset({"\u200d", "\ufe0e", "\ufe0f"})


def _is_cut_point(text: str, end: int) -> bool:
    """Whether ``text[:end]`` ends between two characters, not inside a combining or ZWJ
    sequence (a cheap approximation of a grapheme boundary)."""
    if end == 0:
        return True
    following, previous = text[end], text[end - 1]
    if unicodedata.combining(following) or following in _JOINERS:
        return False
    return previous != "\u200d"


def _weight(index: int, lines: int) -> Weight:
    return 700 if index == 0 and lines > 1 else 400


def plan_test_label(tape_mm: int, text: TapeTestText, band: TapeBand) -> LabelPlan:
    """Decide lines, sizes and the QR of the test label on ``band``."""
    dpi, height = band.dpi, band.px
    zone = min(_px(RULER_ZONE_MM, dpi), height * 2 // 5)
    area = height - zone
    margin, gap = _px(_MARGIN_MM, dpi), _px(_GAP_MM, dpi)
    max_width = _px(MAX_LENGTH_MM, dpi)

    qr = _qr(text.qr_payload, area, dpi) if tape_mm >= QR_FROM_TAPE_MM else None
    qr_px = 0 if qr is None else qr.box_size * (qr.modules_count + 2 * QR_QUIET_MODULES)
    text_budget = max_width - 2 * margin - (qr_px + gap if qr is not None else 0)

    cap_max = _px(_CAP_MAX_MM, dpi)
    lines: tuple[str, ...]
    if tape_mm < NUMBERS_FROM_TAPE_MM:
        cap = max(1, min(cap_max, int(area / _LINE_PITCH)))
        lines = (_shorten(text.printer, f" · {text.width_mm} mm", 400, cap, dpi, text_budget),)
    else:
        three = int(area / (3 * _LINE_PITCH)) >= _MIN_CAP_PX
        fixed = [f"{text.width_mm} mm · {text.printed_at}"]
        if three:
            fixed.append(f"Labelyard {text.version}")
        cap = max(1, min(cap_max, int(area / (len(fixed) + 1) / _LINE_PITCH)))
        widest = max(_text_px(line, 400, cap, dpi) for line in fixed)
        if widest > text_budget:
            cap = max(1, cap * text_budget // widest)
        while cap > 1 and max(_text_px(line, 400, cap, dpi) for line in fixed) > text_budget:
            cap -= 1
        lines = (_shorten(text.printer, "", 700, cap, dpi, text_budget), *fixed)

    text_width = max(
        _text_px(line, _weight(i, len(lines)), cap, dpi) for i, line in enumerate(lines)
    )
    content_end = margin + text_width + (gap + qr_px if qr is not None else 0)
    ruler_end = margin + _px(RULER_MM, dpi) + _tick_width(dpi) + _number_room(tape_mm, zone, dpi)
    width = min(max_width, max(content_end, ruler_end) + margin)
    return LabelPlan(lines, cap, zone, 0 if qr is None else qr.box_size, width)


def _tick_width(dpi: int) -> int:
    return max(1, _px(_TICK_WIDTH_MM, dpi))


def _number_cap(zone: int) -> int:
    return max(1, round(zone * 0.3))


def _number_room(tape_mm: int, zone: int, dpi: int) -> int:
    if tape_mm < NUMBERS_FROM_TAPE_MM:
        return 0
    return _px(0.3, dpi) + _text_px(str(RULER_MM), 400, _number_cap(zone), dpi)


def _draw_ruler(draw: ImageDraw.ImageDraw, tape_mm: int, plan: LabelPlan, band: TapeBand) -> None:
    dpi, bottom, zone = band.dpi, band.px - 1, plan.zone_px
    x0, tick_w = _px(_MARGIN_MM, dpi), _tick_width(dpi)
    numbers = tape_mm >= NUMBERS_FROM_TAPE_MM
    cap = _number_cap(zone)
    for mm in range(RULER_MM + 1):
        x = x0 + _px(mm, dpi)
        level = 3 if mm % 10 == 0 else 2 if mm % 5 == 0 else 1
        length = max(level, round(zone * level / 4))
        draw.rectangle((x, bottom - length + 1, x + tick_w - 1, bottom), fill=0)
        if numbers and level == 3:
            baseline = bottom - round(zone * 0.35)
            draw_glyphs(
                draw,
                _mm(x + tick_w + _px(0.3, dpi), dpi) * 100,
                round(_mm(baseline, dpi) * 100),
                str(mm),
                weight=400,
                cap_mm=_mm(cap, dpi),
                dpi=dpi,
                fill=0,
            )


def render_test_label(tape_mm: int, text: TapeTestText, band: TapeBand) -> Image.Image:
    """The test label as a 1-bit band: ``band.px`` high, running along the tape."""
    plan = plan_test_label(tape_mm, text, band)
    dpi = band.dpi
    image = Image.new("1", (plan.width_px, band.px), color=1)
    draw = ImageDraw.Draw(image)
    area = band.px - plan.zone_px
    margin = _px(_MARGIN_MM, dpi)

    pitch = round(plan.cap_px * _LINE_PITCH)
    # Centre what is drawn: the last line ends at its baseline, not one pitch below it.
    top = max(0, (area - ((len(plan.lines) - 1) * pitch + plan.cap_px)) // 2)
    text_width = 0
    for i, line in enumerate(plan.lines):
        weight = _weight(i, len(plan.lines))
        baseline = top + plan.cap_px + i * pitch
        draw_glyphs(
            draw,
            _mm(margin, dpi) * 100,
            round(_mm(baseline, dpi) * 100),
            line,
            weight=weight,
            cap_mm=_mm(plan.cap_px, dpi),
            dpi=dpi,
            fill=0,
        )
        text_width = max(text_width, _text_px(line, weight, plan.cap_px, dpi))

    if plan.qr_module_px:
        qr = _qr(text.qr_payload, area, dpi)
        assert qr is not None and qr.box_size == plan.qr_module_px
        code = qr.make_image(fill_color="black", back_color="white").convert("1")
        image.paste(code, (margin + text_width + _px(_GAP_MM, dpi), (area - code.height) // 2))

    _draw_ruler(draw, tape_mm, plan, band)
    return image
