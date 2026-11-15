# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The test page of a page printer: a frame on the printable area and what is needed to find
the printer again (#228).

The frame follows the printer's reported hardware margins; a printer that reports none gets a
5 mm inset frame and the line "Margins not reported" (the planner counts unknown margins as
5 mm on every side too). The page names the printer, the tray and the time, and carries a QR
to the printer's page in the hub. It never touches the calibration renderer, a sheet record or
any connection detail of the printer: only the printer's display name, the tray key, the hub
version and the hub URL of the printer end up in the stored payload and on the paper.

``build_test_page_payload`` is the only place that turns a printer into a payload; both the
first print and a retry render the stored payload with ``render_test_page``.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Final

from app.models.printer import Printer
from app.page_render.pdf import PageImage, VectorPen, text_width_mm, write_pdf
from app.page_render.transform import page_size_mm
from app.schemas.capabilities import HardwareMargins
from app.services.page_jobs import PagePayload
from app.sheets.cell_render import build_qr

_log = logging.getLogger(__name__)

INSET_MM: Final = 5.0
FRAME_MM: Final = 0.3
QR_MM: Final = 40.0
RENDER_DPI: Final = 600
_PAD_MM: Final = 8.0
_MIN_INNER_MM: Final = 60.0
_NAME_PT: Final = 14.0


def _sane(m: HardwareMargins, w_mm: float, h_mm: float) -> bool:
    """False for margins that leave no room for the content (a broken report)."""
    sides = (m.top, m.left, m.bottom, m.right)
    return (
        all(0 <= s < 100 for s in sides)
        and w_mm - m.left - m.right >= _MIN_INNER_MM
        and h_mm - m.top - m.bottom >= _MIN_INNER_MM
    )


def build_test_page_payload(
    printer: Printer,
    tray: str,
    media: str,
    margins_mm: HardwareMargins | None,
    now: datetime,
    version: str,
    printer_url: str,
) -> PagePayload:
    """The payload of a test page; ``detail`` is exactly what the renderer draws."""
    return PagePayload(
        kind="test_page",
        media=media,  # type: ignore[arg-type]  # validated by the model: "A4" or "Letter"
        tray=tray,
        render_dpi=RENDER_DPI,
        job_name=f"Test page · {tray}",
        detail={
            "printer_name": printer.name,
            "date": f"{now:%Y-%m-%d %H:%M}",
            "version": version,
            "printer_url": printer_url,
            "margins_mm": None if margins_mm is None else margins_mm.model_dump(),
        },
    )


def _fit(text: str, size_pt: float, room_mm: float) -> str:
    """``text`` shortened with an ellipsis until it fits in ``room_mm``."""
    if text_width_mm(text, size_pt) <= room_mm:
        return text
    for end in range(len(text) - 1, 0, -1):
        cut = text[:end].rstrip() + "…"
        if text_width_mm(cut, size_pt) <= room_mm:
            return cut
    return "…"


def render_test_page(payload: PagePayload, *, compress: bool = True) -> bytes:
    """The PDF of a ``test_page`` payload (one page, gray only, deterministic)."""
    d: dict[str, Any] = payload.detail
    w_mm, h_mm = page_size_mm(payload.media)
    reported = d.get("margins_mm")
    margins = HardwareMargins(**reported) if reported else None
    if margins is not None and not _sane(margins, w_mm, h_mm):
        margins = None
    if margins is None:
        left = top = right = bottom = INSET_MM
    else:
        left, top, right, bottom = margins.left, margins.top, margins.right, margins.bottom
    frame_w, frame_h = w_mm - left - right, h_mm - top - bottom
    x0 = left + _PAD_MM
    room = frame_w - 2 * _PAD_MM

    qr_img = build_qr(str(d["printer_url"]), round(QR_MM / 25.4 * RENDER_DPI))
    if qr_img is None:
        # Dropped, not fatal: the URL line below stays. The URL itself is not logged.
        _log.warning("Test page: the printer URL does not fit in a QR code; printing it as text")
    qr_top = top + 62.0
    images = (
        []
        if qr_img is None
        else [
            PageImage(
                round(x0 * 100), round(qr_top * 100), round(QR_MM * 100), round(QR_MM * 100), qr_img
            )
        ]
    )

    def draw(pen: VectorPen) -> None:
        pen.rect(left, top, frame_w, frame_h, width_mm=FRAME_MM)
        pen.text(x0, top + 20.0, "Test page", size_pt=24)
        pen.text(x0, top + 32.0, _fit(str(d["printer_name"]), _NAME_PT, room), size_pt=_NAME_PT)
        pen.text(x0, top + 40.0, _fit(f"Tray: {payload.tray}", 11, room), size_pt=11)
        pen.text(x0, top + 47.0, str(d["date"]), size_pt=11)
        pen.text(x0, top + 54.0, _fit(f"Printer Hub test page {d['version']}", 9, room), size_pt=9)
        if margins is None:
            pen.text(x0, top + 59.0, "Margins not reported", size_pt=9)
        pen.text(x0, qr_top + QR_MM + 5.0, _fit(str(d["printer_url"]), 7, room), size_pt=7)

    return write_pdf(
        payload.media,
        images=images,
        vector=draw,
        compress=compress,
        title="Test page",
    )
