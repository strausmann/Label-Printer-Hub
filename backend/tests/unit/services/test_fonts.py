# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Every TrueType font Labelyard loads uses the pinned layout engine (#211)."""

from __future__ import annotations

import pytest
from app.page_render.pdf import resolve_font_path
from app.services import ql_layout
from app.services.fonts import PINNED_LAYOUT, load_truetype
from app.services.layout_engine import LayoutEngine
from app.sheets.cell_render import load_cell_font
from app.sheets.sheet_page import _preview_font
from PIL import ImageFont, features


def test_pinned_layout_is_the_engine_of_the_release_image() -> None:
    """The 1.7.0 image has no libfribidi, so ``features.check("raqm")`` is False there."""
    assert PINNED_LAYOUT == ImageFont.Layout.BASIC


def test_runner_engine_is_recorded(record_property: pytest.RecordProperty) -> None:
    """Records which engine Pillow would pick on this machine; the pin makes it irrelevant.

    Shown with ``-rP`` and kept in the junit properties, so a runner that differs from the
    image (RAQM here, BASIC in the image) is visible without failing the build: the golden
    images are rendered with the pinned engine on every machine.
    """
    default = ImageFont.Layout.RAQM if features.check("raqm") else ImageFont.Layout.BASIC
    record_property("pillow_default_layout", default.name)
    record_property("pinned_layout", PINNED_LAYOUT.name)


def test_load_truetype_applies_the_pinned_engine() -> None:
    font = load_truetype(str(resolve_font_path()), 12)
    assert font.layout_engine == PINNED_LAYOUT


def test_every_font_uses_the_pinned_engine() -> None:
    fonts = [
        LayoutEngine._load_font(24),
        *(ql_layout._font(role, 24) for role in ql_layout._Role),
        load_cell_font(24),
        _preview_font(7.5),
    ]
    assert fonts
    for font in fonts:
        assert isinstance(font, ImageFont.FreeTypeFont), "the bundled font must load, not a bitmap"
        assert font.layout_engine == PINNED_LAYOUT
