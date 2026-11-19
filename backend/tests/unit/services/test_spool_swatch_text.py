# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Texts and numbers of the swatch label in the hub language (#346, R-346-6)."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.schemas.spool_swatch import SpoolSwatch
from app.services.spool_swatch import SWATCH_TEXTS, swatch_font, swatch_text
from PIL import ImageFont, features

_DEJAVU = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


def _swatch(language: str = "en", **kw: object) -> SpoolSwatch:
    base: dict[str, object] = {"spool_id": 12, "language": language}
    base.update(kw)
    return SpoolSwatch.model_validate(base)


def _rows(swatch: SpoolSwatch) -> dict[str, str]:
    text = swatch_text(swatch)
    return dict(text.column_1 + text.column_2)


def _value(swatch: SpoolSwatch, key: str) -> str | None:
    label = SWATCH_TEXTS[swatch.language][key]
    return _rows(swatch).get(label)


@pytest.mark.parametrize(
    ("language", "nozzle", "expected"),
    [
        ("en", (210, 230), "210\u2013230 °C"),
        ("de", (210, 230), "210\u2013230 °C"),
        ("en", (215, 215), "215 °C"),
        ("de", (215, 215), "215 °C"),
    ],
)
def test_nozzle_range_and_single(language: str, nozzle: tuple[int, int], expected: str) -> None:
    assert _value(_swatch(language, nozzle_c=nozzle), "nozzle") == expected


@pytest.mark.parametrize("language", ["en", "de"])
def test_bed_is_one_value(language: str) -> None:
    assert _value(_swatch(language, bed_c=60), "bed") == "60 °C"


@pytest.mark.parametrize(
    ("language", "value", "expected"),
    [
        ("en", 0.025, "0.025"),
        ("de", 0.025, "0,025"),
        ("en", 0.020, "0.02"),
        ("en", 0.1, "0.1"),
        ("en", 1.0, "1"),
        ("en", 0.0254, "0.025"),
    ],
)
def test_pressure_advance_trims_zeros(language: str, value: float, expected: str) -> None:
    assert _value(_swatch(language, pressure_advance=value), "pressure_advance") == expected


@pytest.mark.parametrize(("language", "expected"), [("en", "0.96"), ("de", "0,96")])
def test_flow_ratio(language: str, expected: str) -> None:
    assert _value(_swatch(language, flow_ratio=0.96), "flow_ratio") == expected


@pytest.mark.parametrize(
    ("language", "kw", "expected"),
    [
        ("en", {"drying_c": 60, "drying_h": (6, 8)}, "60 °C · 6\u20138 h"),
        ("de", {"drying_c": 60, "drying_h": (6, 8)}, "60 °C · 6\u20138 h"),
        ("en", {"drying_c": 60}, "60 °C"),
        ("en", {"drying_h": (8, 8)}, "8 h"),
        ("de", {"drying_h": (6.5, 8)}, "6,5\u20138 h"),
        ("en", {"drying_h": (6.5, 8)}, "6.5\u20138 h"),
    ],
)
def test_drying_combinations(language: str, kw: dict[str, object], expected: str) -> None:
    assert _value(_swatch(language, **kw), "drying") == expected


@pytest.mark.parametrize(
    ("grams", "expected"), [(140.5, "141 g"), (140.4, "140 g"), (1000, "1000 g"), (2.5, "3 g")]
)
def test_weights_round_half_up(grams: float, expected: str) -> None:
    assert _value(_swatch(spool_weight_g=grams), "empty_spool") == expected
    assert _value(_swatch(net_weight_g=grams), "net") == expected


def test_footer_joins_present_parts() -> None:
    full = {"diameter_mm": 1.75, "density_g_cm3": 1.24, "lot": "2508-A", "opened": "2026-11-03"}
    assert swatch_text(_swatch("en", **full)).footer == (
        "Ø 1.75 mm · 1.24 g/cm³ · Lot 2508-A · opened 2026-11-03"
    )
    assert swatch_text(_swatch("de", **full)).footer == (
        "Ø 1,75 mm · 1,24 g/cm³ · Charge 2508-A · geöffnet 03.11.2026"
    )
    assert swatch_text(_swatch("en", diameter_mm=1.75)).footer == "Ø 1.75 mm"
    assert swatch_text(_swatch("en", diameter_mm=2.85)).footer == "Ø 2.85 mm"
    assert swatch_text(_swatch("en", diameter_mm=3.0)).footer == "Ø 3 mm"
    assert swatch_text(_swatch("en")).footer == ""


@pytest.mark.parametrize("language", ["en", "de"])
def test_rows_without_value_are_absent(language: str) -> None:
    text = swatch_text(_swatch(language, nozzle_c=(210, 230), location="Shelf A2"))
    assert len(text.column_1) == 1
    assert len(text.column_2) == 1
    assert "—" not in repr(text)
    empty = swatch_text(_swatch(language))
    assert empty.column_1 == ()
    assert empty.column_2 == ()


def test_field_labels() -> None:
    en = SWATCH_TEXTS["en"]
    assert en["nozzle"] == "Nozzle"
    assert en["bed"] == "Bed"
    assert en["pressure_advance"] == "PA (K)"
    assert en["flow_ratio"] == "Flow ratio"
    assert en["drying"] == "Drying"
    assert en["empty_spool"] == "Empty spool"
    assert en["net"] == "Net"
    assert en["location"] == "Location"
    de = SWATCH_TEXTS["de"]
    assert de["nozzle"] == "Düse"
    assert de["bed"] == "Bett"
    assert de["pressure_advance"] == "PA (K)"
    assert de["flow_ratio"] == "Fluss­rate"
    assert de["drying"] == "Trock­nung"
    assert de["empty_spool"] == "Leer­spule"
    assert de["net"] == "Netto"
    assert de["location"] == "Ort"


def test_rows_are_in_their_columns() -> None:
    full = _swatch(
        "en",
        nozzle_c=(210, 230),
        bed_c=60,
        pressure_advance=0.025,
        flow_ratio=0.96,
        drying_c=60,
        drying_h=(6, 8),
        spool_weight_g=140,
        net_weight_g=1000,
        location="AMS slot 9",
    )
    text = swatch_text(full)
    assert [label for label, _ in text.column_1] == ["Nozzle", "Bed", "PA (K)", "Flow ratio"]
    assert [label for label, _ in text.column_2] == ["Drying", "Empty spool", "Net", "Location"]


def test_hex_line_joins_all_codes() -> None:
    three = swatch_text(_swatch(color_hexes=("FF5F00", "C2C1C0", "000000")))
    assert three.hex_line == "#FF5F00 · #C2C1C0 · #000000"
    assert swatch_text(_swatch(color_hexes=("FF5F00",))).hex_line == "#FF5F00"
    assert swatch_text(_swatch()).hex_line == ""


def test_hex_block_lists_every_code() -> None:
    text = swatch_text(_swatch(color_hexes=("7F3696", "006EC9", "FFFFFF")))
    assert text.hexes == ("#7F3696", "#006EC9", "#FFFFFF")


def test_caption_is_hash_id() -> None:
    assert swatch_text(_swatch()).caption == "#12"


def test_bar_and_colour_line_and_vendor() -> None:
    text = swatch_text(_swatch(vendor="TecBears", title="PETG", color_name="Orange"))
    assert (text.vendor, text.title, text.color_name) == ("TecBears", "PETG", "Orange")
    assert swatch_text(_swatch()).title == "#12"
    assert swatch_text(_swatch()).vendor == ""


@pytest.mark.skipif(not _DEJAVU.exists(), reason="DejaVu Sans not installed")
def test_swatch_font_is_atkinson_whatever_the_pdf_font(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LABELYARD_PDF_FONT", str(_DEJAVU))
    swatch_font.cache_clear()
    assert swatch_font(700, 28.29).getname()[0].startswith("Atkinson")
    assert swatch_font(400, 28.29).getlength("Nozzle") != swatch_font(700, 28.29).getlength(
        "Nozzle"
    )


def test_swatch_font_uses_the_basic_engine() -> None:
    swatch_font.cache_clear()
    assert swatch_font(400, 28.29).layout_engine == ImageFont.Layout.BASIC
    if features.check("raqm"):
        default = ImageFont.truetype(str(_atkinson_path()), 28)
        assert default.layout_engine != ImageFont.Layout.BASIC
    assert swatch_font(700, 28.29).layout_engine == ImageFont.Layout.BASIC


def _atkinson_path() -> Path:
    from app.services.spool_swatch import SWATCH_FONT_PATH

    return SWATCH_FONT_PATH
