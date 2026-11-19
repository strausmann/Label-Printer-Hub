# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Shared fixtures of the swatch label tests (#346): media boxes and fictitious spools."""

from __future__ import annotations

from functools import cache
from typing import Any

from app.schemas.spool_swatch import SpoolSwatch
from app.seed.sheet_seed import load_seed
from app.sheets.cell_render import content_box
from app.sheets.exchange import geometry_from_doc
from app.sheets.geometry import Geometry
from PIL import Image

SAMPLE_URL = "https://labels.example.org/spool/show/12"
QL_BOX = (5690, 3395)
"""Content box of the 62 x 36 mm QL tape: 672 x 401 px at 300 dpi, in hmm."""

L4737REV = "avery-zweckform-l4737rev"
L4736REV = "avery-zweckform-l4736rev"
Z6121 = "avery-zweckform-6121"


@cache
def seed_geometry(key: str) -> Geometry:
    for doc in load_seed().docs:
        if doc.type.key == key:
            return geometry_from_doc(doc.version.geometry)
    raise KeyError(key)


def seed_box(key: str) -> tuple[int, int]:
    """Content box (w, h) in hmm of the first cell of a seeded sheet type."""
    box = content_box(seed_geometry(key), 1)
    return box.w, box.h


def label_box(label_w: int, label_h: int) -> tuple[int, int]:
    """Content box of a label without a seed entry (rectangle, unknown corner radius)."""
    g = Geometry(
        page_size="A4",
        page_w=21000,
        page_h=29700,
        label_w=label_w,
        label_h=label_h,
        cols=1,
        rows=1,
        pitch_x=label_w,
        pitch_y=label_h,
        margin_top=0,
        margin_left=0,
        corner_radius=None,
        shape="rectangle",
    )
    box = content_box(g, 1)
    return box.w, box.h


def swatch(language: str = "en", **kw: Any) -> SpoolSwatch:
    base: dict[str, Any] = {
        "spool_id": 12,
        "language": language,
        "vendor": "TecBears",
        "title": "PETG",
        "color_name": "Orange",
        "color_hexes": ("FF5F00",),
    }
    base.update(kw)
    return SpoolSwatch.model_validate(base)


def every_row(language: str = "en", **kw: Any) -> SpoolSwatch:
    """A spool with every row and the footer filled (fictitious values)."""
    base: dict[str, Any] = {
        "nozzle_c": (210, 230),
        "bed_c": 60,
        "pressure_advance": 0.025,
        "flow_ratio": 0.96,
        "drying_c": 60,
        "drying_h": (6, 8),
        "spool_weight_g": 140,
        "net_weight_g": 1000,
        "location": "AMS slot 9",
        "diameter_mm": 1.75,
        "density_g_cm3": 1.24,
        "lot": "X-0001",
        "opened": "2026-11-03",
    }
    base.update(kw)
    return swatch(language, **base)


def ink_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    """Bounding box of the black pixels of a ``1`` or ``L`` image (x1/y1 exclusive)."""
    gray = image.convert("L")
    return gray.point(lambda v: 255 if v < 128 else 0).getbbox()
