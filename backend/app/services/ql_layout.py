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

Within an orientation the QR **box** never changes with the content (controller ruling on the
maintainer's "identical pixel size and position"): each preset, and the along layout, has a
fixed box for the code plus its quiet zone, defined by the approved reference (version 3 at
the preset's module size). The QR version follows the payload: the smallest version that
holds it at error correction M, drawn with the largest whole-pixel module size that keeps the
quiet zone (4 modules across the width, the preset's count along the feed) inside the box,
and centred in the box. The reference payload is version 3 at the preset's module size, so
the golden images are unchanged. Modules never go below ``QR_MIN_MODULE_PX``; a payload that
needs smaller modules is refused (``QrPayloadTooLongError``).

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
import qrcode.util
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

QR_REFERENCE_VERSION: Final = 3
QR_MODULES: Final = 17 + 4 * QR_REFERENCE_VERSION  # 29: the version the boxes are sized for
QR_QUIET_ACROSS_MODULES: Final = 4
QR_MIN_MODULE_PX: Final = 4
"""Smallest module size drawn (0.34 mm at 300 dpi); below it a payload is refused."""

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
ALONG_MAX_LENGTH_MM: Final = 200
ALONG_MAX_LENGTH_PX: Final = round(ALONG_MAX_LENGTH_MM * DOTS_PER_MM)
"""An along label grows with its longest line up to 200 mm; longer lines get an ellipsis.
The image is never allocated beyond this length (696 x 2362 px)."""

# Work bounds. Label data from an integration lookup is not capped by the request schema,
# so the renderer bounds the measuring work itself (#258 security review).
LINE_CHAR_BOUND: Final = 200
"""More characters than fit one line at the smallest font on the widest text block (at most
696 px / ~4 px per narrow glyph); text beyond ``(lines + 1) * LINE_CHAR_BOUND`` can never be
shown and is cut before any measuring."""
MAX_SECONDARY_LINES: Final = 10
MAX_LISTING_ROWS: Final = 40
"""Listing rows that are laid out at all; the rest count towards "+N more"."""

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

    @property
    def qr_box(self) -> QrBox:
        """The fixed QR box: version 3 at ``module_px`` plus the preset's quiet zones."""
        return QrBox(
            across=(QR_MODULES + 2 * QR_QUIET_ACROSS_MODULES) * self.module_px,
            along=(QR_MODULES + 2 * self.quiet_along_modules) * self.module_px,
            quiet_across=QR_QUIET_ACROSS_MODULES,
            quiet_along=self.quiet_along_modules,
        )


# Exact values of the README table; standard's fonts scale with its larger code.
ACROSS_PRESETS: Final[dict[QlLayoutPreset, _AcrossPreset]] = {
    QlLayoutPreset.COMPACT: _AcrossPreset(0.32, 2, 0.0, (54, 44, 30, 30)),
    QlLayoutPreset.SMALL_QR: _AcrossPreset(0.32, 4, 0.5, (54, 44, 30, 30)),
    QlLayoutPreset.STANDARD: _AcrossPreset(0.42, 4, 2.0, (62, 50, 34, 34)),
}

# Along (62 mm): the band is the full printable width.
ALONG_MODULE_PX: Final = QL62_PRINTABLE_PX // (QR_MODULES + 2 * QR_QUIET_ACROSS_MODULES)  # 18
ALONG_FONT_PX: Final = (120, 96, 72, 72)
ALONG_BOX_PX: Final = (QR_MODULES + 2 * QR_QUIET_ACROSS_MODULES) * ALONG_MODULE_PX  # 666


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


@dataclass(frozen=True)
class QrBox:
    """The fixed area of a QR code plus its quiet zone, in device pixels.

    ``across`` runs across the tape width, ``along`` along the feed; ``quiet_*`` are the
    minimum quiet zones in modules on each side.
    """

    across: int
    along: int
    quiet_across: int
    quiet_along: int

    def module_px(self, modules: int) -> int:
        """Largest whole-pixel module size that fits ``modules`` plus the quiet zones."""
        return min(
            self.across // (modules + 2 * self.quiet_across),
            self.along // (modules + 2 * self.quiet_along),
        )

    @property
    def max_version(self) -> int:
        """Highest QR version that still fits at ``QR_MIN_MODULE_PX`` (0: none fits)."""
        version = 0
        while version < 40 and self.module_px(17 + 4 * (version + 1)) >= QR_MIN_MODULE_PX:
            version += 1
        return version


def _byte_capacity_m(version: int) -> int:
    """Byte-mode capacity of ``version`` at error correction M (14 for 1, ..., 122 for 7)."""
    bits = qrcode.util.BIT_LIMIT_TABLE[qrcode.constants.ERROR_CORRECT_M][version]
    count_bits = qrcode.util.length_in_bits(qrcode.util.MODE_8BIT_BYTE, version)
    return int((bits - 4 - count_bits) // 8)


def build_box_qr(payload: str, box: QrBox) -> tuple[Image.Image, int]:
    """The QR code for ``payload`` drawn to fit ``box``; returns (image, module size).

    The smallest version that holds the payload at error correction M, at the largest
    whole-pixel module size that keeps the quiet zones inside the box. The image is the code
    without quiet zone (``modules * module`` px square); the caller centres it in the box.
    Raises ``QrPayloadTooLongError`` when the payload needs modules below
    ``QR_MIN_MODULE_PX`` (``max_bytes``: the byte capacity of the largest version that fits).
    """
    max_version = box.max_version
    length = len(payload.encode("utf-8"))
    refused = QrPayloadTooLongError(length=length, max_bytes=_byte_capacity_m(max_version))
    if length > 4 * _byte_capacity_m(max_version):  # cheap reject before any encoding work
        raise refused
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, border=0)
    qr.add_data(payload)
    try:
        qr.make(fit=True)
    except qrcode.exceptions.DataOverflowError:
        raise refused from None
    if qr.version > max_version:
        raise refused
    module = box.module_px(qr.modules_count)
    qr.box_size = module
    image: Image.Image = qr.make_image(fill_color="black", back_color="white").get_image()
    return image.convert("L"), module


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


def _longest_fitting_prefix(
    text: str, font: ImageFont.FreeTypeFont, width: int, suffix: str
) -> int:
    """Largest ``n`` with ``text[:n] + suffix`` no wider than ``width`` (binary search)."""
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if font.getlength(text[:mid].rstrip() + suffix) <= width:
            low = mid
        else:
            high = mid - 1
    return low


def _ellipsize(text: str, font: ImageFont.FreeTypeFont, width: int) -> str:
    """``text`` if it fits, else its longest prefix that fits with an ellipsis (O(log n))."""
    if font.getlength(text) <= width:
        return text
    cut = _longest_fitting_prefix(text, font, width, ELLIPSIS)
    return text[:cut].rstrip() + ELLIPSIS


def _wrap(text: str, font: ImageFont.FreeTypeFont, width: int, limit: int) -> list[str]:
    """Greedy word wrap; a word wider than ``width`` is broken by characters.

    Stops as soon as it has ``limit`` lines plus a remainder: the caller only ever shows
    ``limit`` lines, so the rest is returned unmeasured as the last element.
    """
    lines: list[str] = []
    words = text.split()
    current = ""
    for index, word in enumerate(words):
        if len(lines) >= limit:
            return [*lines, " ".join([current, *words[index:]]).strip()]
        candidate = f"{current} {word}" if current else word
        if font.getlength(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = ""
        while font.getlength(word) > width and len(lines) < limit:
            cut = max(1, _longest_fitting_prefix(word, font, width, ""))
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
    of the field share one size). Text beyond what ``max_lines`` lines can ever show is cut
    before measuring, so the work is bounded whatever the input length.
    """
    bound = (max_lines + 1) * LINE_CHAR_BOUND
    cut_off = len(text) > bound
    text = text[:bound]
    floor_px = max(MIN_FONT_PX, round(base_px * 0.7))
    size = base_px
    font = _font(role, size)
    while font.getlength(text) > width and size - 2 >= floor_px:
        size -= 2
        font = _font(role, size)
    if not cut_off and font.getlength(text) <= width:
        return [_Line(text, font)]
    wrapped = _wrap(text, font, width, max_lines)
    if len(wrapped) > max_lines or cut_off:
        kept = wrapped[: max_lines - 1]
        rest = " ".join(wrapped[max_lines - 1 :])
        last = _ellipsize(rest, font, width)
        if cut_off and not last.endswith(ELLIPSIS):  # the cut must show even if rest fits
            last = rest[: _longest_fitting_prefix(rest, font, width, ELLIPSIS)].rstrip() + ELLIPSIS
        wrapped = [*kept, last]
    return [_Line(t, font) for t in wrapped]


def _fields(content_type: ContentType, data: LabelData) -> tuple[list[tuple[str, _Role]], int]:
    """The text fields of a label, in print order, with the role that picks the font.

    Returns the fields and how many listing rows were left out beyond ``MAX_LISTING_ROWS``
    (they count towards "+N more"); secondary lines beyond ``MAX_SECONDARY_LINES`` are not
    shown at all. Both bounds keep the layout work independent of the data size.
    """
    code = data.primary_id or ""
    title = data.title or ""
    match content_type:
        case ContentType.QR_ONLY:
            return [], 0
        case ContentType.QR_ONE_LINE | ContentType.TEXT_ONE_LINE:
            return [(code, _Role.CODE)], 0
        case ContentType.QR_TWO_LINES | ContentType.TEXT_TWO_LINES:
            return [(code, _Role.CODE), (title, _Role.TITLE)], 0
        case ContentType.QR_THREE_LINES:
            # Across the width there is room for every secondary line: the first is the
            # model (sans), further ones are codes such as the serial (mono).
            fields = [(code, _Role.CODE), (title, _Role.TITLE)]
            for index, line in enumerate(data.secondary[:MAX_SECONDARY_LINES]):
                fields.append((line, _Role.DETAIL if index == 0 else _Role.SERIAL))
            return fields, 0
        case ContentType.QR_WITH_LISTING:
            shown = data.items[:MAX_LISTING_ROWS]
            rows = [(it.item, _Role.DETAIL) for it in shown]
            return [(code, _Role.CODE), *rows], len(data.items) - len(shown)


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
    margin = spec.margin_px
    has_qr = _has_qr(content_type)
    box = spec.qr_box

    qr: Image.Image | None = None
    if has_qr:
        qr, _ = build_box_qr(data.qr_payload or "", box)  # refuses before any text work
        qr_length = box.along
        text_x = box.across + TEXT_GAP_PX
    else:
        qr_length = 0
        text_x = TEXT_RIGHT_PX
    text_width = width - text_x - TEXT_RIGHT_PX

    fields, hidden = _fields(content_type, data)
    blocks = [
        _field_lines(text, role, spec.font_px[role.value], text_width, FIELD_MAX_LINES)
        for text, role in fields
    ]
    blocks = _fit_length(blocks, content_type, spec, text_width, qr_length, margin, hidden)
    lines = [line for block in blocks for line in block]

    text_height = sum(line.height for line in lines)
    height = max(qr_length, text_height) + 2 * margin
    canvas = Image.new("L", (width, height), 255)
    if qr is not None:
        # centred in the fixed box (box at x=0, vertically centred on the label)
        canvas.paste(qr, ((box.across - qr.width) // 2, (height - qr.height) // 2))
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
    hidden: int = 0,
) -> list[list[_Line]]:
    """Cut lines until the label is no longer than ``ACROSS_MAX_LENGTH_PX``.

    Wrapped fields lose lines first (the field with the most lines first, its last kept
    line gets an ellipsis); a listing then keeps as many items as fit plus "+N more", where
    N includes the ``hidden`` rows that were never laid out.
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

    if content_type is ContentType.QR_WITH_LISTING and (
        hidden or length(blocks) > ACROSS_MAX_LENGTH_PX
    ):
        head, items = blocks[:1], blocks[1:]
        more_font = _font(_Role.DETAIL, spec.font_px[_Role.DETAIL.value])
        for keep in range(len(items) - (0 if hidden else 1), -1, -1):
            more = [_Line(f"+{len(items) - keep + hidden} more", more_font)]
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
    ``along`` flag. The QR box is fixed (``ALONG_BOX_PX`` square, the printable width minus
    the remainder of a whole-pixel version-3 code); the code is centred in it.
    """
    band = QL62_PRINTABLE_PX
    has_qr = _has_qr(content_type)
    qr_side = ALONG_BOX_PX if has_qr else 0
    text_x = qr_side + TEXT_GAP_PX if has_qr else TEXT_RIGHT_PX
    qr: Image.Image | None = None
    if has_qr:
        box = QrBox(ALONG_BOX_PX, ALONG_BOX_PX, QR_QUIET_ACROSS_MODULES, QR_QUIET_ACROSS_MODULES)
        qr, _ = build_box_qr(data.qr_payload or "", box)

    fields, hidden = _fields(content_type, data)
    max_text_width = ALONG_MAX_LENGTH_PX - text_x - TEXT_RIGHT_PX
    lines = _along_lines(
        fields,
        max_text_width,
        band - 2 * TEXT_RIGHT_PX,
        hidden,
        listing=content_type is ContentType.QR_WITH_LISTING,
    )

    text_width = max((int(ln.font.getlength(ln.text)) for ln in lines), default=0)
    length = text_x + text_width + TEXT_RIGHT_PX if lines else max(qr_side, 1)
    length = min(length, ALONG_MAX_LENGTH_PX)  # never allocate beyond the documented cap
    canvas = Image.new("L", (length, band), 255)
    if qr is not None:
        offset = (qr_side - qr.width) // 2  # centred in the fixed box
        canvas.paste(qr, (offset, (band - qr_side) // 2 + offset))
    draw = ImageDraw.Draw(canvas)
    text_height = sum(ln.height for ln in lines)
    y = max(0, (band - text_height) // 2)
    for line in lines:
        line.draw(draw, text_x, y)
        y += line.height
    return _threshold(canvas)


def _along_lines(
    fields: list[tuple[str, _Role]],
    text_width: int,
    room: int,
    hidden: int,
    *,
    listing: bool = False,
) -> list[_Line]:
    """One line per field at the along font sizes, each cut to ``text_width`` (ellipsis).

    A listing keeps as many rows as fit the band height ``room`` plus "+N more" (N includes
    the ``hidden`` rows never laid out). Text is cut to ``2 * LINE_CHAR_BOUND`` characters
    before measuring, so the work does not grow with the input.
    """
    bound = 2 * LINE_CHAR_BOUND
    lines: list[_Line] = []
    for text, role in fields:
        font = _font(role, ALONG_FONT_PX[role.value])
        shown = _ellipsize(text[:bound], font, text_width)
        if len(text) > bound and not shown.endswith(ELLIPSIS):
            cut = _longest_fitting_prefix(text[:bound], font, text_width, ELLIPSIS)
            shown = text[:cut].rstrip() + ELLIPSIS
        lines.append(_Line(shown, font))
    if listing and (hidden or sum(ln.height for ln in lines) > room):
        more_font = _font(_Role.DETAIL, ALONG_FONT_PX[_Role.DETAIL.value])
        head, items = lines[:1], lines[1:]
        for keep in range(len(items) - (0 if hidden else 1), -1, -1):
            more = _Line(f"+{len(items) - keep + hidden} more", more_font)
            candidate = [*head, *items[:keep], more]
            if sum(ln.height for ln in candidate) <= room:
                return candidate
        return head
    return lines
