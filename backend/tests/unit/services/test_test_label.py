# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The test label on every tape width (#377, R-377-1): band table, ruler, lines, QR."""

from __future__ import annotations

import itertools
import unicodedata
from typing import Any

import pytest
import qrcode
import qrcode.constants
from app.printer_backends.exceptions import UnsupportedTapeError
from app.services import test_label as tl
from app.services.layout_engine import LayoutEngine
from app.services.test_label import (
    MAX_LENGTH_MM,
    QR_MIN_MODULE_MM,
    QR_QUIET_MODULES,
    TapeBand,
    TapeTestText,
    plan_test_label,
    render_test_label,
)
from app.services.test_label import test_label_band as band_of
from PIL import Image

QL = {12: 106, 29: 306, 38: 413, 50: 554, 54: 590, 62: 696}
PT_180 = {4: 24, 6: 32, 9: 50, 12: 70, 18: 112, 24: 128}
PT_360 = {4: 48, 6: 64, 9: 106, 12: 150, 18: 234, 24: 320, 36: 454}

BAND_TABLE: list[tuple[str, str, int, int, int]] = [
    *(("brother_ql", "QL-820NWB", mm, px, 300) for mm, px in QL.items()),
    *(
        ("ptouch", model, mm, px, 180)
        for model in ("PT-E550W", "PT-P750W")
        for mm, px in PT_180.items()
    ),
    *(
        ("ptouch", model, mm, px, 360)
        for model in ("PT-P900", "PT-P900W", "PT-P910BT", "PT-P950NW")
        for mm, px in PT_360.items()
    ),
]
# One case per band (a model shares its table with its siblings).
BANDS: list[tuple[str, str, int]] = [
    *(("brother_ql", "QL-820NWB", mm) for mm in QL),
    *(("ptouch", "PT-E550W", mm) for mm in PT_180),
    *(("ptouch", "PT-P900", mm) for mm in PT_360),
]

LINK = "https://hub12.invalid/printers/0d5c6b1e-8f6a-4f4e-9d61-3a2b9c1f7e42"  # 67 bytes


def _text(width_mm: int, *, printer: str = "Workshop QL", link: str = LINK) -> TapeTestText:
    return TapeTestText(
        printer=printer,
        width_mm=width_mm,
        printed_at="2026-11-17 14:03",
        version="1.7.0-rc.4",
        qr_payload=link,
    )


def _render(backend: str, model: str, mm: int, **kw: Any) -> tuple[Image.Image, TapeBand]:
    band = band_of(backend, model, mm)
    return render_test_label(mm, _text(mm, **kw), band), band


def _black(image: Image.Image) -> list[list[bool]]:
    data = image.convert("L").tobytes()
    w = image.width
    return [[data[y * w + x] < 128 for x in range(w)] for y in range(image.height)]


def _has_finder(image: Image.Image, module: int) -> bool:
    """A QR finder pattern: rows with black-white-black-white-black runs of 1:1:3:1:1 modules,
    the same run in 3 modules of consecutive rows at the same column."""
    rows = _black(image)
    want = [module, module, 3 * module, module, module]
    hits: dict[int, list[int]] = {}
    for y, row in enumerate(rows):
        runs: list[tuple[bool, int, int]] = []  # (black, start, length)
        start = 0
        for x in range(1, len(row) + 1):
            if x == len(row) or row[x] != row[start]:
                runs.append((row[start], start, x - start))
                start = x
        for i in range(len(runs) - 4):
            window = runs[i : i + 5]
            if window[0][0] and [r[2] for r in window] == want:
                hits.setdefault(window[0][1], []).append(y)
    for ys in hits.values():
        streak = 1
        for a, b in itertools.pairwise(ys):
            streak = streak + 1 if b == a + 1 else 1
            if streak >= 3 * module:
                return True
    return False


def _module_mm(link: str, band: TapeBand) -> float:
    """The module the spec asks for: box = band minus ruler zone, box // (modules + 4)."""
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0)
    qr.add_data(link)
    qr.make(fit=True)
    zone = min(round(tl.RULER_ZONE_MM * band.dpi / 25.4), band.px * 2 // 5)
    module = (band.px - zone) // (qr.modules_count + 2 * QR_QUIET_MODULES)
    return module * 25.4 / band.dpi


def _long_tick_starts(image: Image.Image) -> list[int]:
    """Left edges of the ruler's long ticks: the columns whose ink, counted up from the bottom
    row, is the longest of the label."""
    rows = _black(image)
    runs = []
    for x in range(image.width):
        n = 0
        while n < image.height and rows[image.height - 1 - n][x]:
            n += 1
        runs.append(n)
    longest = max(runs)
    return [
        x for x in range(image.width) if runs[x] == longest and (x == 0 or runs[x - 1] != longest)
    ]


# ------------------------------------------------------------------------------------- band


@pytest.mark.parametrize(
    ("backend", "model", "mm", "px", "dpi"),
    BAND_TABLE,
    ids=[f"{b}-{m}-{mm}" for b, m, mm, _px, _dpi in BAND_TABLE],
)
def test_band_table(backend: str, model: str, mm: int, px: int, dpi: int) -> None:
    assert band_of(backend, model, mm) == TapeBand(px, dpi)


@pytest.mark.parametrize(
    ("backend", "model", "mm"),
    [("ptouch", "PT-E550W", 36), ("brother_ql", "QL-820NWB", 24), ("ptouch", "PT-X", 36),
     ("brother_ql", "QL-X", 24), ("mock", "m", 62)],
)  # fmt: skip
def test_band_refuses_a_width_the_model_lacks(backend: str, model: str, mm: int) -> None:
    with pytest.raises(UnsupportedTapeError) as caught:
        band_of(backend, model, mm)
    assert caught.value.tape_mm == mm


# ------------------------------------------------------------------------------------- render


@pytest.mark.parametrize(
    ("backend", "model", "mm"), BANDS, ids=[f"{m}-{mm}" for _b, m, mm in BANDS]
)
def test_every_band_renders(backend: str, model: str, mm: int) -> None:
    image, band = _render(backend, model, mm)
    assert image.height == band.px
    rows = _black(image)
    quarter = image.width // 4
    for q in range(4):
        assert any(any(row[q * quarter : (q + 1) * quarter]) for row in rows), q


@pytest.mark.parametrize(
    ("backend", "model", "mm", "dpi", "expected"),
    [("brother_ql", "QL-820NWB", 29, 300, 591), ("ptouch", "PT-E550W", 24, 180, 354),
     ("ptouch", "PT-P900", 24, 360, 709), ("ptouch", "PT-E550W", 6, 180, 354)],
    ids=["300", "180", "360", "180-no-numbers"],
)  # fmt: skip
def test_ruler_spans_50_mm(backend: str, model: str, mm: int, dpi: int, expected: int) -> None:
    image, band = _render(backend, model, mm)
    assert band.dpi == dpi
    starts = _long_tick_starts(image)
    assert len(starts) == 6  # 0, 10, ..., 50 mm
    assert abs((starts[-1] - starts[0]) - expected) <= 1


def test_text_lines_by_height() -> None:
    for backend, model, mm in BANDS:
        band = band_of(backend, model, mm)
        plan = plan_test_label(mm, _text(mm), band)
        if mm < 12:
            assert plan.lines == (f"Workshop QL · {mm} mm",), (model, mm)
            continue
        area = band.px - plan.zone_px
        three = area // (3 * 1.5) >= 8
        assert plan.lines[:2] == ("Workshop QL", f"{mm} mm · 2026-11-17 14:03"), (model, mm)
        assert plan.lines[2:] == (("Labelyard 1.7.0-rc.4",) if three else ()), (model, mm)
    # The narrow PT 12 mm band at 180 dpi holds three lines at 9 px; PT 12 mm stays readable.
    assert len(plan_test_label(12, _text(12), band_of("ptouch", "PT-E550W", 12)).lines) == 3


def test_ruler_has_numbers_from_12_mm_only() -> None:
    narrow, _ = _render("ptouch", "PT-E550W", 9)
    wide, _ = _render("ptouch", "PT-E550W", 12)

    # Numbers stand above the short ticks: ink in the ruler zone not reaching the bottom row.
    def floating_ink(image: Image.Image, mm: int) -> int:
        rows = _black(image)
        zone = plan_test_label(mm, _text(mm), band_of("ptouch", "PT-E550W", mm)).zone_px
        bottom = rows[-1]
        return sum(
            1
            for y in range(image.height - zone, image.height - 1)
            for x in range(image.width)
            if rows[y][x] and not bottom[x]
        )

    assert floating_ink(narrow, 9) == 0
    assert floating_ink(wide, 12) > 0


@pytest.mark.parametrize(("backend", "model", "mm"), [c for c in BANDS if c[2] <= 24])
def test_no_qr_up_to_24_mm(backend: str, model: str, mm: int) -> None:
    band = band_of(backend, model, mm)
    assert len(LINK) == 67
    plan = plan_test_label(mm, _text(mm), band)
    assert plan.qr_module_px == 0
    image = render_test_label(mm, _text(mm), band)
    module = round(_module_mm(LINK, band) * band.dpi / 25.4)
    assert not _has_finder(image, max(module, 1))


@pytest.mark.parametrize(
    ("backend", "model", "mm"),
    [("brother_ql", "QL-820NWB", mm) for mm in (29, 38, 50, 54, 62)] + [("ptouch", "PT-P900", 36)],
)
def test_qr_from_29_mm_when_modules_are_large_enough(backend: str, model: str, mm: int) -> None:
    band = band_of(backend, model, mm)
    module_mm = _module_mm(LINK, band)
    assert module_mm >= QR_MIN_MODULE_MM
    image = render_test_label(mm, _text(mm), band)
    assert _has_finder(image, round(module_mm * band.dpi / 25.4))


@pytest.mark.parametrize("mm", [29, 62])
def test_a_long_link_draws_the_qr_only_with_large_enough_modules(mm: int) -> None:
    link = "https://hub.example.invalid/printers/" + "p" * (1200 - 37)
    assert len(link.encode()) == 1200
    band = band_of("brother_ql", "QL-820NWB", mm)
    module_mm = _module_mm(link, band)
    module_px = round(module_mm * band.dpi / 25.4)
    drawn = plan_test_label(mm, _text(mm, link=link), band).qr_module_px > 0
    assert drawn == (module_mm >= QR_MIN_MODULE_MM)
    image = render_test_label(mm, _text(mm, link=link), band)
    if drawn:
        assert _has_finder(image, module_px)
    # On 29 mm the 1 200-byte link needs modules below 0.25 mm; on 62 mm they are large enough.
    assert drawn == (mm == 62)


def test_a_link_too_long_never_raises() -> None:
    for link in ("https://h.invalid/" + "p" * 5000, ""):
        for backend, model, mm in BANDS:
            band = band_of(backend, model, mm)
            image = render_test_label(mm, _text(mm, link=link), band)
            assert image.height == band.px
            if link:
                assert plan_test_label(mm, _text(mm, link=link), band).qr_module_px == 0


@pytest.mark.parametrize(
    ("backend", "model", "mm"), BANDS, ids=[f"{m}-{mm}" for _b, m, mm in BANDS]
)
def test_long_printer_name_is_shortened(backend: str, model: str, mm: int) -> None:
    name = "WORKSHOP " * 7 + "W"  # 64 wide characters: too long for 100 mm on every band
    assert len(name) == 64
    band = band_of(backend, model, mm)
    plan = plan_test_label(mm, _text(mm, printer=name), band)
    image = render_test_label(mm, _text(mm, printer=name), band)
    assert image.width <= round(MAX_LENGTH_MM * band.dpi / 25.4)
    first = plan.lines[0]
    if name not in first:
        assert first.endswith("…") or first.endswith(f"… · {mm} mm")
    # At the small cap heights of narrow tape the whole name may fit 100 mm; from 18 mm on it
    # never does.
    if mm >= 18:
        assert name not in first


def test_does_not_use_the_layout_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("the test label never uses the layout engine")

    monkeypatch.setattr(LayoutEngine, "render", refuse)
    for backend, model, mm in BANDS:
        image, band = _render(backend, model, mm)
        assert image.height == band.px


def test_text_round_trips_through_the_payload() -> None:
    text = _text(29)
    assert TapeTestText.from_payload({**text.to_payload(), "px": 306, "dpi": 300}) == text


@pytest.mark.parametrize(
    ("backend", "model", "mm"), BANDS, ids=[f"{m}-{mm}" for _b, m, mm in BANDS]
)
def test_first_line_is_not_clipped(backend: str, model: str, mm: int) -> None:
    """The tops of the first line (ascenders: k, d, l, b) stay inside the band."""
    image, _band = _render(backend, model, mm, printer="Workshop Kldb")
    rows = _black(image)
    first = next(y for y, row in enumerate(rows) if any(row))
    assert first >= 1


def test_shortening_keeps_combining_and_zwj_sequences_whole() -> None:
    """Every width budget: the cut never separates a mark or a ZWJ from its neighbours."""
    for unit in ("We\u0301", "W\U0001f468\u200d\U0001f469"):
        name = unit * 20
        for budget in range(40, 400, 7):
            first = tl._shorten(name, "", 700, 40, 300, budget)
            if not first.endswith("…"):
                continue
            kept = first[:-1].rstrip()
            assert name.startswith(kept)
            following = name[len(kept)]
            assert not unicodedata.combining(following) and following != "\u200d", budget
            assert not kept.endswith("\u200d"), budget


@pytest.mark.parametrize(
    ("backend", "model", "mm", "band"),
    [("ptouch", "PT-H500", 24, TapeBand(128, 180)), ("ptouch", "PT-H500", 12, TapeBand(70, 180)),
     ("ptouch", "", 4, TapeBand(24, 180)), ("brother_ql", "QL-1100", 62, TapeBand(696, 300)),
     ("brother_ql", "QL-1100", 29, TapeBand(306, 300)),
     ("mock", "PT-P750W", 24, TapeBand(128, 180)), ("mock", "QL-820NWB", 62, TapeBand(696, 300)),
     ("mock", "m", 24, TapeBand(128, 180))],
)  # fmt: skip
def test_an_unknown_model_falls_back_by_backend(
    backend: str, model: str, mm: int, band: TapeBand
) -> None:
    """An unknown model never breaks the test print: P-touch standard pins at 180 dpi, QL the
    DK dots at 300 dpi; a backend the hub has no table for goes by the model's family."""
    assert band_of(backend, model, mm) == band
    assert render_test_label(mm, _text(mm), band).height == band.px
