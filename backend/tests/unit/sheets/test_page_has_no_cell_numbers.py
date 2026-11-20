# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The printed page never carries the cell numbers the sheet-grid preview shows (#249).

The numbers 1..48 in the UI grid are an aid for the person choosing cells; they are not content.
This guard records every string the page renderer draws and asserts none is a bare cell number.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.page_render import pdf as pdf_module
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.services.page_jobs import PagePayload
from app.sheets.sheet_page import SheetCellPayload, SheetPageDetail, render_sheet_page
from PIL import ImageDraw

from tests.unit.sheets.test_sheet_page import L4736, _detail, _payload

N_CELLS = 48


def _cells() -> list[SheetCellPayload]:
    return [
        SheetCellPayload(
            cell=n,
            content_type=ContentType.QR_TWO_LINES,
            label_data=LabelData(
                source_app="t", primary_id="X", title="X", qr_payload="https://h/x"
            ).model_dump(mode="json"),
            mapped=False,
        )
        for n in range(1, N_CELLS + 1)
    ]


def _drawn_strings(monkeypatch: pytest.MonkeyPatch, payload: PagePayload) -> list[str]:
    """Every string the page renderer draws: PDF text runs and the text rasterised into cells."""
    drawn: list[str] = []
    original_pdf = pdf_module.write_pdf
    original_text = ImageDraw.ImageDraw.text

    def spy_pdf(media: str, *, images: Any, texts: Any, **kw: Any) -> bytes:
        drawn.extend(t.text for t in texts)
        return original_pdf(media, images=images, texts=texts, **kw)

    def spy_text(self: ImageDraw.ImageDraw, xy: Any, text: Any, *a: Any, **kw: Any) -> Any:
        drawn.append(str(text))
        return original_text(self, xy, text, *a, **kw)

    monkeypatch.setattr("app.sheets.sheet_page.write_pdf", spy_pdf)
    monkeypatch.setattr(ImageDraw.ImageDraw, "text", spy_text)
    render_sheet_page(payload)
    return drawn


def test_page_has_no_cell_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    detail: SheetPageDetail = _detail(L4736).model_copy(update={"cells": _cells()})
    assert len(detail.cells) == N_CELLS
    drawn = _drawn_strings(monkeypatch, _payload(detail))
    numbers = {str(n) for n in range(1, N_CELLS + 1)}
    assert drawn, "the recorder saw no text at all"
    assert not [s for s in drawn if s.strip() in numbers], drawn


def test_guard_sees_a_drawn_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """The recorder works: the sheet code printed in the margin is recorded."""
    from app.sheets.sheet_page import MarginIdPayload

    detail = _detail(L4736, margin=MarginIdPayload(text="L4736-0001", usable_hmm=700))
    assert "L4736-0001" in _drawn_strings(monkeypatch, _payload(detail))
