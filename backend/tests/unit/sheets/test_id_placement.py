# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Where the sheet code of a sheet type goes by default (#350, R-350-2)."""

from __future__ import annotations

from app.seed.sheet_seed import load_seed
from app.sheets.exchange import geometry_from_doc
from app.sheets.geometry import Geometry
from app.sheets.id_placement import geometry_margin_possible, resolve_default_placement


def _seed_geometry(key: str) -> Geometry:
    doc = next(d for d in load_seed().docs if d.type.key == key)
    return geometry_from_doc(doc.version.geometry)


def test_shipped_3490_resolves_to_back_side() -> None:
    g = _seed_geometry("avery-zweckform-3490")
    assert geometry_margin_possible(g) is False
    assert resolve_default_placement("auto", margin_printable=False) == "back_side"


def test_shipped_6121_resolves_to_margin() -> None:
    g = _seed_geometry("avery-zweckform-6121")
    assert geometry_margin_possible(g) is True
    assert resolve_default_placement("auto", margin_printable=True) == "margin"


def test_auto_assumes_the_5mm_hardware_margin() -> None:
    # A4, a 5.5 mm top margin and no other band: 550 - 500 - 100 = -50 < 400. Without the
    # assumed hardware margin the top band would be 450 >= 400 and look printable.
    g = Geometry("A4", 21000, 29700, 21000, 29150, 1, 1, 21000, 29150, 550, 0, None, "rectangle")
    assert geometry_margin_possible(g) is False


def test_explicit_setting_wins_over_margin() -> None:
    assert resolve_default_placement("cell", margin_printable=True) == "cell"
    assert resolve_default_placement("back_side", margin_printable=True) == "back_side"
    assert resolve_default_placement("margin", margin_printable=False) == "margin"
