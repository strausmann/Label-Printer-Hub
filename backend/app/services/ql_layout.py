"""QL 62 mm label geometry: across-width presets and the full-width along layout (#258).

Two orientations exist on 62 mm DK endless tape:

- **across** — the image is exactly ``dots_printable[0]`` = 696 px wide (the width
  ``brother_ql.convert`` expects, so it never resizes). A QR code of fixed size sits on the
  left, the text block beside it; the label length (image height) follows the content.
  The three presets are the layouts printed and approved on a QL-820NWB on 2026-11-09
  (``docs/design/ql-layout-presets`` on branch ``docs/ql-layout-presets``); their output for
  the reference content is pinned pixel-exact by the golden tests.
- **along** — the content runs along the tape (the 1.4.1 output). The image is landscape: its
  height is the 696 px band across the tape, its width the label length. The QR takes the
  full printable width minus its quiet zone. The backend rotates it on the ``along`` flag.

Within an orientation the QR code never changes with the content: version 3 with whole-pixel
modules. A payload that exceeds version 3 is refused (``QrPayloadTooLongError``), never
shrunk. Error correction is M; a payload that only fits with L uses L, which keeps the module
count and therefore the exact pixel size and position of the code.

Feed margin: every preset keeps the brother_ql default feed margin. Four prints in a row
showed that the QL-820NWB keeps about 3 mm of feed at each end whatever feed margin is sent
(35, 12 or 0 dots), so sending less has no effect (README "Resolved"; controller ruling for
Task 21a). The "feed margin sent" column of the README records what the spike sent, not a
requirement. Only the layout margin and the quiet zone along the feed shorten the label.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Final

import qrcode
import qrcode.constants
import qrcode.exceptions
from PIL import Image, ImageDraw, ImageFont

from app.printer_backends.exceptions import QrPayloadTooLongError, UnsupportedTapeError
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.schemas.label_layout import LabelOrientation, LayoutDefault, QlLayoutPreset

DOTS_PER_MM: Final = 300 / 25.4
QL62_PRINTABLE_PX: Final = 696
"""``brother_ql`` ``label_type_specs['62']['dots_printable'][0]`` at 300 dpi."""

ACROSS_TAPES_MM: Final[frozenset[int]] = frozenset({62})
"""Tape widths with an across-width layout. Other DK endless widths follow later (#258)."""

QR_VERSION: Final = 3
QR_MODULES: Final = 17 + 4 * QR_VERSION  # 29
QR_QUIET_ACROSS_MODULES: Final = 4
QR_MAX_BYTES: Final = 53
"""Byte-mode capacity of a version-3 code with error correction L."""

TEXT_GAP_PX: Final = round(1.5 * DOTS_PER_MM)  # QR quiet zone -> text block
TEXT_RIGHT_PX: Final = round(1.0 * DOTS_PER_MM)  # text block -> tape edge
LINE_GAP_PX: Final = round(0.9 * DOTS_PER_MM)
MIN_FONT_PX: Final = 20
INK_THRESHOLD: Final = 115
"""Greyscale values below this become black: about 55 % ink."""

FIELD_MAX_LINES: Final = 3
"""A wrapped field (title, model, ...) takes at most this many lines, then an ellipsis."""
ACROSS_MAX_LENGTH_PX: Final = round(50 * DOTS_PER_MM)
"""The across label grows with the text up to this length, beyond that lines are cut."""

ELLIPSIS: Final = "…"

_FONT_DIR: Final = Path(__file__).resolve().parents[1] / "page_render" / "fonts"
_MONO_BOLD: Final = _FONT_DIR / "IBMPlexMono-Bold.ttf"
_SANS_VARIABLE: Final = _FONT_DIR / "AtkinsonHyperlegibleNext-Variable.ttf"


class _Role(Enum):
    """What a text line is; decides its font."""

    CODE = 0  # asset tag: IBM Plex Mono Bold, largest
    TITLE = 1  # Atkinson Hyperlegible Next Bold
    DETAIL = 2  # model etc.: Atkinson Hyperlegible Next Regular
    SERIAL = 3  # serial etc.: IBM Plex Mono Bold (as printed on the approved references)


@dataclass(frozen=True)
class _AcrossPreset:
    qr_budget_share: float
    """Share of the tape width for QR + quiet zone across; module = floor(budget / 37)."""
    quiet_along_modules: int
    layout_margin_mm: float
    font_px: tuple[int, int, int, int]
    """Base font size per ``_Role`` (code, title, detail, serial)."""

    @property
    def module_px(self) -> int:
        budget = round(QL62_PRINTABLE_PX * self.qr_budget_share)
        return budget // (QR_MODULES + 2 * QR_QUIET_ACROSS_MODULES)

    @property
    def margin_px(self) -> int:
        return round(self.layout_margin_mm * DOTS_PER_MM)


# Exact values of the README table; standard's fonts scale with its larger code.
ACROSS_PRESETS: Final[dict[QlLayoutPreset, _AcrossPreset]] = {
    QlLayoutPreset.COMPACT: _AcrossPreset(0.32, 2, 0.0, (54, 44, 30, 30)),
    QlLayoutPreset.SMALL_QR: _AcrossPreset(0.32, 4, 0.5, (54, 44, 30, 30)),
    QlLayoutPreset.STANDARD: _AcrossPreset(0.42, 4, 2.0, (62, 50, 34, 34)),
}

# Along (62 mm): the band is the full printable width.
ALONG_MODULE_PX: Final = QL62_PRINTABLE_PX // (QR_MODULES + 2 * QR_QUIET_ACROSS_MODULES)  # 18
ALONG_FONT_PX: Final = (120, 96, 72, 72)


# ---------------------------------------------------------------------------------------
# Orientation and preset resolution
# ---------------------------------------------------------------------------------------


def resolve_layout(
    tape_mm: int,
    orientation: LabelOrientation | None,
    preset: QlLayoutPreset | None,
    default: LayoutDefault | None,
) -> tuple[LabelOrientation, QlLayoutPreset | None]:
    """Decide orientation and preset: request, then stored default, then the tape default.

    Tape default: 62 mm across with the compact preset, every other width along. ``along``
    returns no preset. Raises ``UnsupportedTapeError`` for ``across`` on a tape without an
    across-width layout.
    """
    across_ok = tape_mm in ACROSS_TAPES_MM
    chosen = (
        orientation
        or (default.orientation if default is not None else None)
        or (LabelOrientation.ACROSS if across_ok else LabelOrientation.ALONG)
    )
    if chosen is LabelOrientation.ACROSS and not across_ok:
        raise UnsupportedTapeError(tape_mm=tape_mm, orientation=str(chosen))
    if chosen is LabelOrientation.ALONG:
        return chosen, None
    chosen_preset = (
        preset or (default.preset if default is not None else None) or QlLayoutPreset.COMPACT
    )
    return chosen, chosen_preset


# ---------------------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------------------


def build_fixed_qr(payload: str, module_px: int) -> Image.Image:
    """A version-3 QR code without quiet zone, ``module_px`` device pixels per module.

    Error correction M, falling back to L for a longer payload (same module count, same
    size). Raises ``QrPayloadTooLongError`` when the payload does not fit version 3-L.
    """
    for ecc in (qrcode.constants.ERROR_CORRECT_M, qrcode.constants.ERROR_CORRECT_L):
        qr = qrcode.QRCode(version=QR_VERSION, error_correction=ecc, box_size=module_px, border=0)
        qr.add_data(payload)
        try:
            qr.make(fit=False)
        except qrcode.exceptions.DataOverflowError:
            continue
        image: Image.Image = qr.make_image(fill_color="black", back_color="white").get_image()
        return image.convert("L")
    raise QrPayloadTooLongError(length=len(payload.encode("utf-8")), max_bytes=QR_MAX_BYTES)


@lru_cache(maxsize=64)
def _font(role: _Role, size_px: int) -> ImageFont.FreeTypeFont:
    """The font of ``role`` at ``size_px``; the variable sans gets its weight set once."""
    if role in (_Role.CODE, _Role.SERIAL):
        return ImageFont.truetype(str(_MONO_BOLD), size_px)
    font = ImageFont.truetype(str(_SANS_VARIABLE), size_px)
    font.set_variation_by_axes([700 if role is _Role.TITLE else 400])
    return font


@dataclass(frozen=True)
class _Line:
    text: str
    font: ImageFont.FreeTypeFont

    @property
    def height(self) -> int:
        """Line pitch: cap top of the line to the bottom of its ink, plus the line gap."""
        return int(self.font.getbbox(self.text)[3] - self.font.getbbox("H")[1]) + LINE_GAP_PX

    def draw(self, draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
        draw.text((x, y - self.font.getbbox("H")[1]), self.text, font=self.font, fill=0)


def _ellipsize(text: str, font: ImageFont.FreeTypeFont, width: int) -> str:
    if font.getlength(text) <= width:
        return text
    while text and font.getlength(text.rstrip() + ELLIPSIS) > width:
        text = text[:-1]
    return text.rstrip() + ELLIPSIS


def _wrap(text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    """Greedy word wrap; a word wider than ``width`` is broken by characters."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if font.getlength(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = ""
        while font.getlength(word) > width:
            cut = len(word)
            while cut > 1 and font.getlength(word[:cut]) > width:
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
        current = word
    if current:
        lines.append(current)
    return lines


def _field_lines(text: str, role: _Role, base_px: int, width: int, max_lines: int) -> list[_Line]:
    """Lay one field out: shrink within limits, then wrap, then cut with an ellipsis.

    The longest line decides the font size: the field keeps its base size if it fits,
    otherwise it shrinks in 2 px steps down to its minimum, and only then wraps (all lines
    of the field share one size).
    """
    floor_px = max(MIN_FONT_PX, round(base_px * 0.7))
    size = base_px
    font = _font(role, size)
    while font.getlength(text) > width and size - 2 >= floor_px:
        size -= 2
        font = _font(role, size)
    if font.getlength(text) <= width:
        return [_Line(text, font)]
    wrapped = _wrap(text, font, width)
    if len(wrapped) > max_lines:
        rest = " ".join(wrapped[max_lines - 1 :])
        wrapped = [*wrapped[: max_lines - 1], _ellipsize(rest, font, width)]
    return [_Line(t, font) for t in wrapped]


def _fields(content_type: ContentType, data: LabelData) -> list[tuple[str, _Role]]:
    """The text fields of a label, in print order, with the role that picks the font."""
    code = data.primary_id or ""
    title = data.title or ""
    match content_type:
        case ContentType.QR_ONLY:
            return []
        case ContentType.QR_ONE_LINE | ContentType.TEXT_ONE_LINE:
            return [(code, _Role.CODE)]
        case ContentType.QR_TWO_LINES | ContentType.TEXT_TWO_LINES:
            return [(code, _Role.CODE), (title, _Role.TITLE)]
        case ContentType.QR_THREE_LINES:
            # Across the width there is room for every secondary line: the first is the
            # model (sans), further ones are codes such as the serial (mono).
            fields = [(code, _Role.CODE), (title, _Role.TITLE)]
            for index, line in enumerate(data.secondary):
                fields.append((line, _Role.DETAIL if index == 0 else _Role.SERIAL))
            return fields
        case ContentType.QR_WITH_LISTING:
            return [(code, _Role.CODE), *((it.item, _Role.DETAIL) for it in data.items)]


def _has_qr(content_type: ContentType) -> bool:
    return content_type not in (ContentType.TEXT_ONE_LINE, ContentType.TEXT_TWO_LINES)


def _threshold(image: Image.Image) -> Image.Image:
    return image.point(lambda v: 0 if v < INK_THRESHOLD else 255, "1")


# ---------------------------------------------------------------------------------------
# Across (62 mm)
# ---------------------------------------------------------------------------------------


def render_across(
    content_type: ContentType, data: LabelData, preset: QlLayoutPreset
) -> Image.Image:
    """Render a 62 mm label across the tape width: 696 px wide, length from the content."""
    spec = ACROSS_PRESETS[preset]
    width = QL62_PRINTABLE_PX
    module = spec.module_px
    margin = spec.margin_px
    has_qr = _has_qr(content_type)

    if has_qr:
        qr_side = (QR_MODULES + 2 * QR_QUIET_ACROSS_MODULES) * module
        qr_length = (QR_MODULES + 2 * spec.quiet_along_modules) * module
        text_x = qr_side + TEXT_GAP_PX
    else:
        qr_length = 0
        text_x = TEXT_RIGHT_PX
    text_width = width - text_x - TEXT_RIGHT_PX

    fields = _fields(content_type, data)
    blocks = [
        _field_lines(text, role, spec.font_px[role.value], text_width, FIELD_MAX_LINES)
        for text, role in fields
    ]
    blocks = _fit_length(blocks, content_type, spec, text_width, qr_length, margin)
    lines = [line for block in blocks for line in block]

    text_height = sum(line.height for line in lines)
    height = max(qr_length, text_height) + 2 * margin
    canvas = Image.new("L", (width, height), 255)
    if has_qr:
        qr = build_fixed_qr(data.qr_payload or "", module)
        canvas.paste(qr, (QR_QUIET_ACROSS_MODULES * module, (height - QR_MODULES * module) // 2))
    draw = ImageDraw.Draw(canvas)
    y = margin + (height - 2 * margin - text_height) // 2
    for line in lines:
        line.draw(draw, text_x, y)
        y += line.height
    return _threshold(canvas)


def _fit_length(
    blocks: list[list[_Line]],
    content_type: ContentType,
    spec: _AcrossPreset,
    text_width: int,
    qr_length: int,
    margin: int,
) -> list[list[_Line]]:
    """Cut lines until the label is no longer than ``ACROSS_MAX_LENGTH_PX``.

    Wrapped fields lose lines first (the field with the most lines first, its last kept
    line gets an ellipsis); a listing then keeps as many items as fit plus "+N more".
    """

    def length(bs: list[list[_Line]]) -> int:
        return max(qr_length, sum(line.height for b in bs for line in b)) + 2 * margin

    blocks = [list(b) for b in blocks]
    while length(blocks) > ACROSS_MAX_LENGTH_PX:
        index = max(range(len(blocks)), key=lambda i: len(blocks[i]), default=None)
        if index is None or len(blocks[index]) <= 1:
            break
        block = blocks[index]
        kept = block[:-1]
        last = kept[-1]
        kept[-1] = _Line(
            _ellipsize(last.text + " " + block[-1].text, last.font, text_width), last.font
        )
        blocks[index] = kept

    if content_type is ContentType.QR_WITH_LISTING and length(blocks) > ACROSS_MAX_LENGTH_PX:
        head, items = blocks[:1], blocks[1:]
        more_font = _font(_Role.DETAIL, spec.font_px[_Role.DETAIL.value])
        for keep in range(len(items) - 1, -1, -1):
            more = [_Line(f"+{len(items) - keep} more", more_font)]
            candidate = [*head, *items[:keep], more]
            if length(candidate) <= ACROSS_MAX_LENGTH_PX:
                return candidate
        return head
    while len(blocks) > 1 and length(blocks) > ACROSS_MAX_LENGTH_PX:
        blocks = blocks[:-1]
    return blocks


# ---------------------------------------------------------------------------------------
# Along (62 mm)
# ---------------------------------------------------------------------------------------


def render_along_62(content_type: ContentType, data: LabelData) -> Image.Image:
    """Render a 62 mm label along the tape: a 696 px band, length grows with the text.

    The image is landscape (height = band across the tape); the QL backend rotates it on the
    ``along`` flag. The QR side is the printable width minus its 4-module quiet zone.
    """
    band = QL62_PRINTABLE_PX
    module = ALONG_MODULE_PX
    has_qr = _has_qr(content_type)
    qr_side = (QR_MODULES + 2 * QR_QUIET_ACROSS_MODULES) * module if has_qr else 0
    text_x = qr_side + TEXT_GAP_PX if has_qr else TEXT_RIGHT_PX

    lines: list[_Line] = []
    for text, role in _fields(content_type, data):
        lines.append(_Line(text, _font(role, ALONG_FONT_PX[role.value])))
    room = band - 2 * TEXT_RIGHT_PX
    if content_type is ContentType.QR_WITH_LISTING and sum(ln.height for ln in lines) > room:
        more_font = _font(_Role.DETAIL, ALONG_FONT_PX[_Role.DETAIL.value])
        head, items = lines[:1], lines[1:]
        for keep in range(len(items) - 1, -1, -1):
            candidate = [*head, *items[:keep], _Line(f"+{len(items) - keep} more", more_font)]
            if sum(ln.height for ln in candidate) <= room:
                lines = candidate
                break

    text_width = max((int(ln.font.getlength(ln.text)) for ln in lines), default=0)
    length = text_x + text_width + TEXT_RIGHT_PX if lines else max(qr_side, 1)
    canvas = Image.new("L", (length, band), 255)
    if has_qr:
        qr = build_fixed_qr(data.qr_payload or "", module)
        quiet = QR_QUIET_ACROSS_MODULES * module
        canvas.paste(qr, (quiet, (band - qr_side) // 2 + quiet))
    draw = ImageDraw.Draw(canvas)
    text_height = sum(ln.height for ln in lines)
    y = max(0, (band - text_height) // 2)
    for line in lines:
        line.draw(draw, text_x, y)
        y += line.height
    return _threshold(canvas)
