# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The swatch label in a sheet cell (#346, R-346-10)."""

from __future__ import annotations

import pytest
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.services.spool_swatch import SHEET_METRICS, SwatchTier, layout_for_box, render_swatch
from app.sheets.cell_render import DEFAULT_CELL_RENDERER, content_box, map_content_type
from app.sheets.errors import ItemContentMismatchError
from app.sheets.print_service import ResolvedItem, check_item_fits
from app.sheets.reservation import ItemMeta

from tests.helpers.spool_swatch import (
    L4736REV,
    L4737REV,
    SAMPLE_URL,
    every_row,
    seed_box,
    seed_geometry,
)


def _label(payload: str = SAMPLE_URL) -> LabelData:
    return LabelData(source_app="spoolman", qr_payload=payload, swatch=every_row("de"))


@pytest.mark.parametrize(
    ("key", "tier"), [(L4737REV, SwatchTier.NO_FOOTER), (L4736REV, SwatchTier.CORE)]
)
@pytest.mark.parametrize("dpi", [300, 600])
def test_cell_render_draws_the_swatch(key: str, tier: SwatchTier, dpi: int) -> None:
    w, h = seed_box(key)
    cell = DEFAULT_CELL_RENDERER.render(
        box_w_mm=w / 100,
        box_h_mm=h / 100,
        dpi=dpi,
        content_type=ContentType.SPOOL_SWATCH,
        data=_label(),
    )
    layout = layout_for_box(w, h, SHEET_METRICS)
    assert layout.tier is tier
    expected, truncated = render_swatch(
        every_row("de"),
        SAMPLE_URL,
        layout=layout,
        width_px=cell.image.width,
        height_px=cell.image.height,
        dpi=dpi,
        metrics=SHEET_METRICS,
    )
    assert cell.image.size == (round(w / 2540 * dpi), round(h / 2540 * dpi))
    assert cell.image.tobytes() == expected.tobytes()
    assert cell.truncated is truncated


def test_type_without_qr_maps_to_text_two_lines() -> None:
    assert map_content_type(ContentType.SPOOL_SWATCH, allow_qr=False) == (
        ContentType.TEXT_TWO_LINES,
        True,
    )


def _resolved(label: LabelData) -> ResolvedItem:
    return ResolvedItem(
        label=label,
        content_type=ContentType.SPOOL_SWATCH,
        meta=ItemMeta(source="spoolman", purpose="p", ref=None),
        lookup=None,
    )


def test_check_item_fits_refuses_a_too_small_cell() -> None:
    g = seed_geometry("avery-5167")
    box = content_box(g, 1)
    assert (box.w, box.h) == (4149, 974)
    with pytest.raises(ItemContentMismatchError) as exc:
        check_item_fits(_resolved(_label()), 3, allow_qr=True, geometry=g, cell=1, render_dpi=300)
    assert exc.value.detail == {"item_index": 3, "missing_fields": ["label_size"]}


def test_check_item_fits_refuses_a_qr_that_does_not_fit_the_swatch_box() -> None:
    g = seed_geometry(L4737REV)
    check_item_fits(_resolved(_label()), 0, allow_qr=True, geometry=g, cell=1, render_dpi=300)
    payload = "https://x.example/" + "a" * 2400
    with pytest.raises(ItemContentMismatchError) as exc:
        check_item_fits(
            _resolved(_label(payload)), 0, allow_qr=True, geometry=g, cell=1, render_dpi=300
        )
    assert exc.value.detail == {"item_index": 0, "missing_fields": ["qr_payload"]}
