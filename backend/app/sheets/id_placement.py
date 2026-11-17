# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Where the sheet code of a new sheet goes by default (#350, R-350-2).

A sheet type stores ``auto``, ``margin``, ``back_side`` or ``cell``. ``auto`` never resolves to
``cell``: with a printer the margin check decides (``printable``), without one the geometry
does, with the assumed 5 mm hardware margin of a printer that does not report its own.
"""

from __future__ import annotations

from typing import Literal

from app.page_render.transform import IDENTITY
from app.sheets.geometry import Geometry
from app.sheets.planner import MIN_MARGIN_TEXT_HMM, margin_bands_hmm

__all__ = [
    "ResolvedPlacement",
    "TypePlacement",
    "geometry_margin_possible",
    "resolve_default_placement",
    "resolve_type_placement",
]

TypePlacement = Literal["auto", "margin", "back_side", "cell"]
ResolvedPlacement = Literal["margin", "back_side", "cell"]


def geometry_margin_possible(g: Geometry) -> bool:
    """Whether any margin band of ``g`` is deep enough for the margin text on a printer whose
    hardware margin is unknown (``hw=None``: 5 mm per side) and without calibration."""
    return max(margin_bands_hmm(g, hw=None, dev=IDENTITY).values()) >= MIN_MARGIN_TEXT_HMM


def resolve_default_placement(
    setting: TypePlacement, *, margin_printable: bool
) -> ResolvedPlacement:
    """The placement a new sheet gets: an explicit setting as it is, ``auto`` by the margin."""
    if setting == "auto":
        return "margin" if margin_printable else "back_side"
    return setting


def resolve_type_placement(setting: str, g: Geometry) -> ResolvedPlacement:
    """``resolve_default_placement`` without a printer: the geometry decides ``auto``."""
    placement: TypePlacement = (
        setting if setting in ("margin", "back_side", "cell") else "auto"  # type: ignore[assignment]
    )
    return resolve_default_placement(placement, margin_printable=geometry_margin_possible(g))
