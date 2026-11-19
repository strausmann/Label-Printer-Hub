# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The sheet code on the back of the liner, and the tray loading test page (#350).

**Code strip (R-350-3).** A 22 x 62 mm strip, upright in back-side coordinates (viewed on the
liner, top = the sheet's top after turning it over along the long edge). From the top: a QR of
the sheet's scan payload, 17 mm square with a two-module quiet zone (ECC M), then the sheet code
and "<type> · <date>", both turned to read from bottom to top, shrunk and ended with an ellipsis
until they fit. A thin frame shows the strip. The strip goes horizontally centred into the first
free strip of the backing design that takes it, 2 mm below that strip's top; without a design
it goes to (10, 10) mm. A tray that feeds the image's bottom edge first gets the page turned
by 180 degrees (``rotate_180``): the strip moves to the mirrored place, the QR image is turned
and the texts read from top to bottom. No calibration applies: the front's calibration does
not describe the back, and the position need not be exact.

**Loading test page (R-350-5).** A big "TOP ↑" at the top edge of the printed image and
"PRINTED SIDE" in the middle, in the hub's language. The person marks a cross on the face-up
side next to the edge that goes in first, prints the page and answers two questions.

Both payloads carry everything the renderer needs, so a retry prints the same page again.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID

import qrcode
import qrcode.constants
import qrcode.exceptions
from PIL import Image
from pydantic import BaseModel, ConfigDict

from app.page_render.pdf import PageImage, PageText, VectorPen, text_width_mm, write_pdf
from app.page_render.transform import PT_PER_MM, page_size_mm
from app.services.page_jobs import PagePayload
from app.sheets.errors import BackStripDoesNotFitError

__all__ = [
    "DEFAULT_STRIP_ORIGIN_HMM",
    "QR_EDGE_HMM",
    "QR_INSET_HMM",
    "STRIP_H_HMM",
    "STRIP_TOP_GAP_HMM",
    "STRIP_W_HMM",
    "BackPageLayout",
    "BackStripDoesNotFitError",
    "SheetBackDetail",
    "StripHmm",
    "back_page_layout",
    "loading_page_payload",
    "place_strip",
    "render_sheet_back_page",
    "render_tray_loading_page",
]

STRIP_W_HMM: Final = 2200
STRIP_H_HMM: Final = 6200
STRIP_TOP_GAP_HMM: Final = 200
DEFAULT_STRIP_ORIGIN_HMM: Final = (1000, 1000)
QR_EDGE_HMM: Final = 1700
QR_INSET_HMM: Final = 250
RENDER_DPI: Final = 600

_QR_QUIET_MODULES: Final = 2
_FRAME_MM: Final = 0.35
_TEXT_GAP_HMM: Final = 200  # between the QR and the start of the texts
_LINE_GAP_HMM: Final = 250  # between the two text lines
_CODE_CAP_HMM: Final = 460
_INFO_CAP_HMM: Final = 320
_CAP_EM: Final = 0.72  # cap height as a fraction of the font size (as the margin ID)
_MIN_PT: Final = 6.0

_LOADING_TEXTS: Final[dict[str, tuple[str, str]]] = {
    "en": ("TOP ↑", "PRINTED SIDE"),
    "de": ("OBEN ↑", "BEDRUCKTE SEITE"),
}
_LOADING_TOP_PT: Final = 48.0
_LOADING_SIDE_PT: Final = 36.0


@dataclass(frozen=True)
class StripHmm:
    """A rectangle on the back of the liner in hundredths of a millimetre."""

    x: int
    y: int
    w: int
    h: int


class SheetBackDetail(BaseModel):
    """The ``detail`` of a ``sheet_back_page`` payload: all the renderer needs."""

    model_config = ConfigDict(extra="ignore")

    sheet_id: UUID
    sheet_code: str
    type_text: str
    date: str
    scan_payload: str
    strip: StripHmm
    rotate_180: bool


def place_strip(page_w_hmm: int, page_h_hmm: int, free: Sequence[StripHmm]) -> StripHmm:
    """Where the code strip goes: centred in the first free strip that takes it, 2 mm below its
    top; at (10, 10) mm without a design. Raises ``BackStripDoesNotFitError`` when none does."""
    if not free:
        x, y = DEFAULT_STRIP_ORIGIN_HMM
        return StripHmm(x, y, STRIP_W_HMM, STRIP_H_HMM)
    for s in free:
        fits = s.w >= STRIP_W_HMM and s.h >= STRIP_TOP_GAP_HMM + STRIP_H_HMM
        inside = s.x >= 0 and s.y >= 0 and s.x + s.w <= page_w_hmm and s.y + s.h <= page_h_hmm
        if fits and inside:
            return StripHmm(
                s.x + (s.w - STRIP_W_HMM) // 2, s.y + STRIP_TOP_GAP_HMM, STRIP_W_HMM, STRIP_H_HMM
            )
    raise BackStripDoesNotFitError()


# ---------------------------------------------------------------------------- code strip


@dataclass(frozen=True)
class BackPageLayout:
    """What the back page draws, in page coordinates (turned already when ``rotate_180``)."""

    frame: StripHmm
    qr: StripHmm
    qr_turned: bool
    texts: tuple[PageText, PageText]


def _size_for_cap(cap_hmm: int) -> float:
    return cap_hmm / 100 / _CAP_EM * PT_PER_MM


def _fit(text: str, size_pt: float, room_mm: float, *, cut: bool) -> tuple[str, float]:
    """Shrink to ``_MIN_PT``; then, if ``cut``, shorten with an ellipsis until it fits."""
    size = size_pt
    while size > _MIN_PT and text_width_mm(text, size) > room_mm:
        size -= 0.5
    size = max(size, _MIN_PT)
    if not cut or text_width_mm(text, size) <= room_mm:
        return text, size
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if text_width_mm(text[:mid].rstrip() + "…", size) <= room_mm:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + "…", size


def back_page_layout(detail: SheetBackDetail, page: str = "A4") -> BackPageLayout:
    """The strip's frame, QR box and the two texts; upright, then turned if asked."""
    s = detail.strip
    qr = StripHmm(s.x + QR_INSET_HMM, s.y + QR_INSET_HMM, QR_EDGE_HMM, QR_EDGE_HMM)
    run_start = qr.y + qr.h + _TEXT_GAP_HMM
    run_end = s.y + s.h - QR_INSET_HMM
    room_mm = (run_end - run_start) / 100
    lines_w = _CODE_CAP_HMM + _LINE_GAP_HMM + _INFO_CAP_HMM
    left = s.x + (s.w - lines_w) // 2
    # Turned to read from bottom to top, a line's caps reach left of its baseline: the code
    # (on top when read) is the left line, the type and date the right one.
    code_text, code_pt = _fit(detail.sheet_code, _size_for_cap(_CODE_CAP_HMM), room_mm, cut=False)
    info_text, info_pt = _fit(
        f"{detail.type_text} · {detail.date}", _size_for_cap(_INFO_CAP_HMM), room_mm, cut=True
    )
    code = PageText(left + _CODE_CAP_HMM, run_end, code_pt, code_text, rotation=270)
    info = PageText(
        left + _CODE_CAP_HMM + _LINE_GAP_HMM + _INFO_CAP_HMM,
        run_end,
        info_pt,
        info_text,
        rotation=270,
    )
    if not detail.rotate_180:
        return BackPageLayout(s, qr, False, (code, info))
    w_mm, h_mm = page_size_mm(page)
    w, h = round(w_mm * 100), round(h_mm * 100)

    def turn(r: StripHmm) -> StripHmm:
        return StripHmm(w - r.x - r.w, h - r.y - r.h, r.w, r.h)

    def turn_text(t: PageText) -> PageText:
        return PageText(w - t.x_hmm, h - t.baseline_y_hmm, t.size_pt, t.text, rotation=90)

    return BackPageLayout(turn(s), turn(qr), True, (turn_text(code), turn_text(info)))


def _qr_image(payload: str, edge_px: int) -> Image.Image | None:
    """The QR in an ``edge_px`` square with a two-module quiet zone, whole-pixel modules."""
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=1, border=_QR_QUIET_MODULES
    )
    try:
        qr.add_data(payload)
        qr.make(fit=True)
    except (qrcode.exceptions.DataOverflowError, ValueError):
        return None
    matrix = qr.get_matrix()
    side = len(matrix)
    module = edge_px // side
    if module < 1:
        return None
    flat = bytes(0 if dark else 255 for row in matrix for dark in row)
    symbol = (
        Image.frombytes("L", (side, side), flat)
        .resize((side * module, side * module), Image.Resampling.NEAREST)
        .convert("1")
    )
    canvas = Image.new("1", (edge_px, edge_px), 1)
    canvas.paste(symbol, ((edge_px - symbol.width) // 2, (edge_px - symbol.height) // 2))
    return canvas


def render_sheet_back_page(payload: PagePayload, *, compress: bool = True) -> bytes:
    """The PDF of a ``sheet_back_page`` payload (a job, a retry and a reprint alike)."""
    detail = SheetBackDetail.model_validate(payload.detail)
    lay = back_page_layout(detail, payload.media)
    images: list[PageImage] = []
    edge_px = round(QR_EDGE_HMM / 2540 * RENDER_DPI)
    qr = _qr_image(detail.scan_payload, edge_px)
    if qr is not None:
        if lay.qr_turned:
            qr = qr.rotate(180)
        images.append(PageImage(lay.qr.x, lay.qr.y, lay.qr.w, lay.qr.h, qr))
    f = lay.frame

    def frame(pen: VectorPen) -> None:
        pen.rect(f.x / 100, f.y / 100, f.w / 100, f.h / 100, width_mm=_FRAME_MM)

    return write_pdf(
        payload.media,
        images=images,
        texts=[t for t in lay.texts if t.text],
        vector=frame,
        compress=compress,
        title=payload.job_name,
    )


# ---------------------------------------------------------------------------- loading page


def loading_page_payload(
    tray: str, media: Literal["A4", "Letter"], language: str | None
) -> PagePayload:
    """The ``tray_loading_page`` payload: the two texts in the hub's language."""
    top, side = _LOADING_TEXTS.get(language or "", _LOADING_TEXTS["en"])
    return PagePayload(
        kind="tray_loading_page",
        media=media,
        tray=tray,
        render_dpi=RENDER_DPI,
        job_name=f"Tray loading test · {tray}",
        calibration=None,
        detail={"tray": tray, "top_text": top, "side_text": side},
    )


def render_tray_loading_page(payload: PagePayload, *, compress: bool = True) -> bytes:
    """The loading test page: "TOP ↑" at the image's top edge, "PRINTED SIDE" in the middle."""
    top = str(payload.detail.get("top_text") or _LOADING_TEXTS["en"][0])
    side = str(payload.detail.get("side_text") or _LOADING_TEXTS["en"][1])
    w_mm, h_mm = page_size_mm(payload.media)
    texts: list[PageText] = []
    for text, size, baseline_mm in (
        (top, _LOADING_TOP_PT, 30.0),
        (side, _LOADING_SIDE_PT, h_mm / 2),
    ):
        width = text_width_mm(text, size)
        while width > w_mm - 30 and size > _MIN_PT:
            size -= 2
            width = text_width_mm(text, size)
        texts.append(
            PageText(round((w_mm - width) / 2 * 100), round(baseline_mm * 100), size, text)
        )
    return write_pdf(payload.media, texts=texts, compress=compress, title=payload.job_name)
