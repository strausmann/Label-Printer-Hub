# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The printable calibration page: what is drawn where, read back from the PDF operators."""

from __future__ import annotations

import math
import shutil
from collections import Counter
from dataclasses import asdict
from itertools import pairwise

import pytest
from app.calibration import scale
from app.calibration.fit import crossing_point
from app.calibration.page import (
    CHECKERBOARD_SENTENCE,
    _scale_segments,
    draw_calibration_page,
    footer_text,
    render_calibration_page,
)
from app.page_render.pdf import PT_PER_MM, _register_font, resolve_font_path, write_pdf
from app.page_render.transform import Deviation, correction_pdf_matrix
from app.services.page_jobs import CalibrationSnapshot, PagePayload
from app.sheets.errors import CalibrationTypeUnsuitableError
from app.sheets.geometry import Geometry
from reportlab.pdfbase import pdfmetrics

from tests.helpers import pdf_inspect as pi

L4736 = Geometry("A4", 21000, 29700, 4570, 2120, 4, 12, 4820, 2120, 2130, 985, None, "rectangle")
L4731 = Geometry("A4", 21000, 29700, 2540, 1000, 7, 27, 2790, 1000, 1350, 860, 150, "rectangle")
# Avery 7160-like: a gap between the columns, none between the rows.
G7160 = Geometry("A4", 21000, 29700, 6350, 3810, 3, 7, 6600, 3810, 1510, 720, None, "rectangle")
# Gaps in both directions.
GAPPED = Geometry("A4", 21000, 29700, 4000, 2000, 3, 4, 4500, 2500, 2000, 1000, None, "rectangle")
# No margin at all, in the top left corner: a column line and a row line run into the square.
EDGE = Geometry("A4", 21000, 29700, 1000, 1100, 3, 3, 1000, 1100, 0, 0, None, "rectangle")
A4_W, A4_H = 210.0, 297.0
SQUARE = 15.0
FOOTER = "t v1 · printer · tray auto · 2026-11-05 · Calibration page — printed without correction"


def _pdf(g: Geometry, footer: str = FOOTER) -> bytes:
    return write_pdf(
        "A4", vector=lambda pen: draw_calibration_page(pen, g, footer=footer), compress=False
    )


def _mm(x_pt: float, y_pt: float) -> tuple[float, float]:
    return x_pt / PT_PER_MM, A4_H - y_pt / PT_PER_MM


def _strokes(pdf: bytes) -> list[dict]:
    """Every single-segment stroke: width and dash in mm, the two end points in page mm."""
    out: list[dict] = []
    cur: dict | None = None
    for op, a in pi.operations(pdf):
        if op == "q":
            cur = {"width": None, "dash": None, "pts": []}
        elif cur is None:
            continue
        elif op == "w":
            cur["width"] = round(a[0] / PT_PER_MM, 3)
        elif op == "d":
            cur["dash"] = tuple(round(v / PT_PER_MM, 3) for v in a[:-1])
        elif op in ("m", "l"):
            cur["pts"].append(_mm(*a))
        elif op == "S":
            if cur["pts"]:
                out.append(cur)
        elif op == "Q":
            cur = None
    return out


def _len(s: dict) -> float:
    (x1, y1), (x2, y2) = s["pts"]
    return round(abs(x2 - x1) + abs(y2 - y1), 2)


def _vertical(s: dict) -> bool:
    return abs(s["pts"][0][0] - s["pts"][1][0]) < 1e-6


def _grid(g: Geometry) -> tuple[float, float]:
    return (
        ((g.cols - 1) * g.pitch_x + g.label_w) / 100,
        ((g.rows - 1) * g.pitch_y + g.label_h) / 100,
    )


def _long(pdf: bytes, g: Geometry, *, vertical: bool) -> list[dict]:
    gw, gh = _grid(g)
    want = gh if vertical else gw
    return [s for s in _strokes(pdf) if _vertical(s) == vertical and abs(_len(s) - want) < 0.02]


def _inside(x: float, y: float, w: float = A4_W, h: float = A4_H) -> bool:
    return (
        (x < SQUARE or x > w - SQUARE)
        and (y < SQUARE or y > h - SQUARE)
        and (0 < x < w and 0 < y < h)
    )


def _points(pdf: bytes) -> list[tuple[float, float]]:
    """Every drawn point: the end points and a sample every 0.25 mm along each segment, so a
    line that merely passes through a square is seen too."""
    pts: list[tuple[float, float]] = []
    for s in _strokes(pdf):
        (x1, y1), (x2, y2) = s["pts"]
        n = max(1, int(max(abs(x2 - x1), abs(y2 - y1)) / 0.25))
        pts += [(x1 + (x2 - x1) * i / n, y1 + (y2 - y1) * i / n) for i in range(n + 1)]
    return pts


def _strictly_in_square(x: float, y: float) -> bool:
    """Strictly inside; the PDF's fixed-decimal rounding is far below the 1 µm tolerance."""
    eps = 1e-3
    return (eps < x < SQUARE - eps or A4_W - SQUARE + eps < x < A4_W - eps) and (
        eps < y < SQUARE - eps or A4_H - SQUARE + eps < y < A4_H - eps
    )


# ---------------------------------------------------------------------------- line counts


def test_page_line_counts_l4736() -> None:
    pdf = _pdf(L4736)
    solid = [s for s in _long(pdf, L4736, vertical=True) if s["dash"] is None]
    dotted = [s for s in _long(pdf, L4736, vertical=False) if s["dash"] == (0.2, 0.4)]
    dashed = [s for s in _long(pdf, L4736, vertical=False) if s["dash"] == (1.0, 0.5)]
    assert len(solid) == 3
    assert len(dotted) == 11
    assert dashed == []
    assert all(s["width"] == 0.1 for s in solid + dotted)
    xs = sorted(round(s["pts"][0][0], 2) for s in solid)
    assert xs == [round(crossing_point(L4736, i, 1)[0], 2) for i in (1, 2, 3)]
    ys = sorted(round(s["pts"][0][1], 2) for s in dotted)
    assert ys == [round(crossing_point(L4736, 1, j)[1], 2) for j in range(1, 12)]
    # 33 crossings, each with a scale in both directions: one centre tick each, the longest.
    centre = Counter((_vertical(s)) for s in _strokes(pdf) if _len(s) == scale.TICK_CENTRE_MM)
    assert centre == {True: 33, False: 33}
    # 9 ticks per scale: 1 centre, 4 whole millimetres, 4 half millimetres.
    lengths = Counter(
        (_vertical(s), _len(s))
        for s in _strokes(pdf)
        if _len(s) in (scale.TICK_HALF_MM, scale.TICK_WHOLE_MM)
    )
    assert lengths[(True, scale.TICK_HALF_MM)] == lengths[(False, scale.TICK_HALF_MM)] == 33 * 4
    assert lengths[(True, scale.TICK_WHOLE_MM)] == lengths[(False, scale.TICK_WHOLE_MM)] == 33 * 4
    assert CHECKERBOARD_SENTENCE in pi.texts(pdf)


def test_the_mini_scale_ticks_are_half_a_millimetre_apart_with_white_between() -> None:
    """A colour laser fills in a hairline gap (#348): the 0.5 mm pitch and the ticks are held."""
    pdf = _pdf(L4736)
    cx, cy = crossing_point(L4736, 1, 1)
    # The ticks of the scale along x at the first crossing: vertical, centred on the crossing's row.
    ticks = sorted(
        s["pts"][0][0] - cx
        for s in _strokes(pdf)
        if _vertical(s)
        and _len(s) in (scale.TICK_HALF_MM, scale.TICK_WHOLE_MM, scale.TICK_CENTRE_MM)
        and abs((s["pts"][0][1] + s["pts"][1][1]) / 2 - cy) < 0.01
        and abs(s["pts"][0][0] - cx) < scale.HALF_MM + 0.01
    )
    assert [round(t, 2) for t in ticks] == [-2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0]
    pitch = min(b - a for a, b in pairwise(ticks))
    assert round(pitch, 2) == scale.STEP_MM == 0.5
    # Whole millimetres are clearly longer than half millimetres, the centre is the longest.
    assert scale.TICK_HALF_MM < scale.TICK_WHOLE_MM < scale.TICK_CENTRE_MM
    assert scale.TICK_WHOLE_MM - scale.TICK_HALF_MM >= 0.4
    # The ruler on the grid edge keeps its 0.5 mm pitch.
    assert scale.STEP_MM == 0.5


def test_the_white_between_two_mini_scale_ticks_survives_a_colour_laser() -> None:
    """From the drawing constants alone: pitch minus stroke width is the white between two ticks."""
    assert scale.STEP_MM - scale.LINE_MM >= scale.MIN_GAP_MM - 1e-9


def _render_crop(pdf: bytes, cx: float, cy: float, half_mm: float, dpi: int = 600):
    """The square of ``2 * half_mm`` around (cx, cy) as a grey image, and its pixels per mm."""
    import subprocess
    import tempfile
    from pathlib import Path

    from PIL import Image

    ppm = dpi / 25.4
    with tempfile.TemporaryDirectory() as d:
        src = Path(d, "page.pdf")
        src.write_bytes(pdf)
        out = Path(d, "crop")
        side = round(2 * half_mm * ppm)
        subprocess.run(
            [
                "pdftoppm", "-r", str(dpi), "-gray", "-png", "-singlefile",
                "-x", str(round((cx - half_mm) * ppm)), "-y", str(round((cy - half_mm) * ppm)),
                "-W", str(side), "-H", str(side), str(src), str(out),
            ],
            check=True,
        )  # fmt: skip
        with Image.open(out.with_suffix(".png")) as im:
            return im.convert("L").copy(), ppm


@pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="needs poppler's pdftoppm")
def test_a_corner_mark_never_comes_within_the_white_of_a_tick() -> None:
    """Measured on the 600 dpi image of a 2.5 mm gap sheet (#348), not from the constants.

    The label-corner legs of such a sheet sit at +-1.25 mm of the crossing, between the ticks at
    1.0 and 1.5 mm. Every ink pixel that is neither tick nor on the gap lines through the crossing
    must keep ``MIN_GAP_MM`` from the ticks.
    """
    half = 4.0
    cx, cy = crossing_point(L4736, 2, 5)
    im, ppm = _render_crop(_pdf(L4736), cx, cy, half)
    w, h = im.size
    ink = {(x, y) for y in range(h) for x in range(w) if im.getpixel((x, y)) < 128}
    # Where the ticks are (this only classifies pixels; the clearance is measured below).
    pad = 0.075 * ppm

    def px(mm_x: float, mm_y: float) -> tuple[float, float]:
        return (mm_x - cx + half) * ppm, (mm_y - cy + half) * ppm

    rects = []
    for along_x in (True, False):
        for x1, y1, x2, y2 in _scale_segments(cx, cy, along_x=along_x):
            (a, b), (c, d) = px(x1, y1), px(x2, y2)
            rects.append((min(a, c) - pad, min(b, d) - pad, max(a, c) + pad, max(b, d) + pad))

    def is_tick(p: tuple[int, int]) -> bool:
        return any(r[0] <= p[0] + 0.5 <= r[2] and r[1] <= p[1] + 0.5 <= r[3] for r in rects)

    centre = half * ppm  # the gap lines run through the middle of the crop
    ticks = {p for p in ink if is_tick(p)}
    other = [
        p
        for p in ink - ticks
        if abs(p[0] + 0.5 - centre) > 0.1 * ppm and abs(p[1] + 0.5 - centre) > 0.1 * ppm
    ]
    assert len(ticks) > 100  # the scales are really in the image
    clearance = min(
        (math.hypot(p[0] - t[0], p[1] - t[1]) / ppm for p in other for t in ticks),
        default=math.inf,
    )
    assert clearance >= scale.MIN_GAP_MM, f"other ink {clearance:.2f} mm from a tick"


def test_page_line_counts_gapped_type() -> None:
    pdf = _pdf(G7160)
    assert len([s for s in _long(pdf, G7160, vertical=True) if s["dash"] is None]) == 2
    assert len([s for s in _long(pdf, G7160, vertical=False) if s["dash"] == (0.2, 0.4)]) == 6
    assert CHECKERBOARD_SENTENCE in pi.texts(pdf)
    full = _pdf(GAPPED)
    assert len([s for s in _long(full, GAPPED, vertical=True) if s["dash"] is None]) == 2
    dashed = [s for s in _long(full, GAPPED, vertical=False) if s["dash"] == (1.0, 0.5)]
    assert len(dashed) == 3
    assert [s for s in _long(full, GAPPED, vertical=False) if s["dash"] == (0.2, 0.4)] == []
    assert CHECKERBOARD_SENTENCE not in pi.texts(full)


def test_page_labels_the_gaps_on_both_sides() -> None:
    texts = Counter(pi.texts(_pdf(L4736)))
    for i in (1, 2, 3):
        assert texts[f"S{i}"] == 2  # above and below the grid
    for j in range(1, 12):
        assert texts[f"Z{j}"] == 2  # left and right of the grid
    assert texts["S4"] == 0 and texts["Z12"] == 0


def test_page_has_rulers_with_half_millimetre_ticks_on_all_edges() -> None:
    g = L4736
    gw, gh = _grid(g)
    x0, y0 = g.margin_left / 100, g.margin_top / 100
    ticks = [s for s in _strokes(_pdf(g)) if _len(s) == 1.0]

    def edge(s: dict, axis: int, fn: object, at: float) -> bool:
        return abs(fn(p[axis] for p in s["pts"]) - at) < 0.01  # type: ignore[operator]

    top = [s for s in ticks if _vertical(s) and edge(s, 1, max, y0)]  # drawn upwards
    bottom = [s for s in ticks if _vertical(s) and edge(s, 1, min, y0 + gh)]
    left = [s for s in ticks if not _vertical(s) and edge(s, 0, max, x0)]
    right = [s for s in ticks if not _vertical(s) and edge(s, 0, min, x0 + gw)]
    assert (len(top), len(bottom)) == (3 * 13, 3 * 13)
    assert (len(left), len(right)) == (11 * 13, 11 * 13)
    cx = crossing_point(g, 1, 1)[0]
    near = sorted(round(s["pts"][0][0] - cx, 2) for s in top if abs(s["pts"][0][0] - cx) < 3.01)
    assert near == [round(-3 + 0.5 * k, 2) for k in range(13)]


def test_page_has_a_corner_mark_at_every_label_corner() -> None:
    pdf = _pdf(L4736)
    marks = [s for s in _strokes(pdf) if _len(s) == 1.5]
    # Two legs per corner. A corner inside the scale of a crossing has no mark (see
    # test_a_corner_mark_never_comes_within_the_white_of_a_tick): of the 4 x 12 labels that
    # leaves the outer corners (2 sides x 2 corners x 12 rows) and the corners on the top and
    # bottom edge of the grid next to the 3 column gaps (3 x 2 x 2).
    assert len(marks) == 2 * (2 * 2 * 12 + 3 * 2 * 2)
    # The first label's top left corner: legs run right and down, hugging the label.
    x, y = L4736.margin_left / 100, L4736.margin_top / 100
    near = [
        s for s in marks if any(abs(p[0] - x) < 0.01 and abs(p[1] - y) < 0.01 for p in s["pts"])
    ]
    assert len(near) == 2


# ---------------------------------------------------------------------------- corners


@pytest.mark.parametrize("g", [L4736, L4731, EDGE], ids=["l4736", "l4731", "no-margin"])
def test_page_is_gray_only_and_corners_empty(g: Geometry) -> None:
    pdf = _pdf(g)
    assert pi.colour_operators(pdf) == set()
    assert not {"rg", "RG", "k", "K"} & set(pi.operators(pdf))
    inside = [p for p in _points(pdf) if _strictly_in_square(*p)]
    assert inside == []
    texts_in = [
        p
        for p in pi.text_positions(pdf)
        if _strictly_in_square(p[0] / PT_PER_MM, A4_H - p[1] / PT_PER_MM)
    ]
    assert texts_in == []
    assert pi.texts(pdf)  # something is drawn


def test_l4731_leaves_out_the_corner_marks_inside_the_squares() -> None:
    pdf = _pdf(L4731)
    marks = [s for s in _strokes(pdf) if _len(s) == 1.5]
    # The corners that lie inside a square have no mark, nor have those inside the scale of a
    # crossing (pinned: 128 corners keep their mark on this 7 x 27 sheet).
    assert len(marks) == 128 * 2
    assert not any(
        abs(p[0] - 8.6) < 0.01 and abs(p[1] - 13.5) < 0.01 for s in marks for p in s["pts"]
    )


def test_a_zero_margin_type_loses_marks_but_keeps_its_clipped_lines() -> None:
    pdf = _pdf(EDGE)
    marks = [s for s in _strokes(pdf) if _len(s) == 1.5]
    assert 0 < len(marks) < 4 * 9 * 2  # the corners inside the top left square are gone
    col = [
        s
        for s in _strokes(pdf)
        if _vertical(s) and round(s["pts"][0][0], 2) == 10.0 and _len(s) > 10
    ]
    row = [
        s
        for s in _strokes(pdf)
        if not _vertical(s) and round(s["pts"][0][1], 2) == 11.0 and _len(s) > 10
    ]
    assert [
        (round(min(p[1] for p in s["pts"]), 2), round(max(p[1] for p in s["pts"]), 2)) for s in col
    ] == [(15.0, 33.0)]
    assert [
        (round(min(p[0] for p in s["pts"]), 2), round(max(p[0] for p in s["pts"]), 2)) for s in row
    ] == [(15.0, 30.0)]


def test_footer_is_centred_and_clear_of_the_squares() -> None:
    pdf = _pdf(L4736)
    footer = FOOTER
    [pos] = [p for t, p in zip(pi.texts(pdf), pi.text_positions(pdf), strict=True) if t == footer]
    font = _register_font(resolve_font_path())
    width = pdfmetrics.stringWidth(footer, font, 6) / PT_PER_MM
    x, y = pos[0] / PT_PER_MM, A4_H - pos[1] / PT_PER_MM
    assert x + width / 2 == pytest.approx(A4_W / 2, abs=0.05)
    assert y == pytest.approx(A4_H - 7, abs=0.01)
    assert x > SQUARE and x + width < A4_W - SQUARE


# ---------------------------------------------------------------------------- the renderer


def _payload(
    g: Geometry = L4736,
    *,
    corrected: bool = False,
    snapshot: CalibrationSnapshot | None = None,
    name: str = "Office",
    key: str = "t",
    tray: str = "auto",
) -> PagePayload:
    return PagePayload(
        kind="calibration_page",
        media="A4",
        tray=tray,
        render_dpi=600,
        job_name="Calibration page · t v1",
        calibration=snapshot if corrected else None,
        detail={
            "type_key": key,
            "version": 1,
            "printer_name": name,
            "date": "2026-11-05",
            "corrected": corrected,
            "geometry": asdict(g),
        },
    )


def test_footer_text_wording() -> None:
    assert footer_text("t", 1, "Office", "auto", "2026-11-05", corrected=False) == (
        "t v1 · Office · tray auto · 2026-11-05 · Calibration page — printed without correction"
    )
    assert footer_text("t", 1, "Office", "auto", "2026-11-05", corrected=True).endswith(
        "Calibration page — check print with correction"
    )


def test_uncorrected_page_has_no_cm_correction() -> None:
    pdf = render_calibration_page(_payload(), compress=False)
    assert pi.cm_matrices(pdf) == []
    assert any(t.endswith("printed without correction") for t in pi.texts(pdf))


def test_corrected_page_has_correction_matrix() -> None:
    snap = CalibrationSnapshot(method="manual", dx_hmm=120, dy_hmm=-40, sx_ppm=1_001_000)
    pdf = render_calibration_page(_payload(corrected=True, snapshot=snap), compress=False)
    dev = Deviation(120, -40, 1_001_000, 1_000_000, 0)
    assert pi.cm_matrices(pdf)[0] == pytest.approx(correction_pdf_matrix(dev, "A4"), abs=1e-3)
    assert any(t.endswith("check print with correction") for t in pi.texts(pdf))


def test_corrected_page_of_an_uncalibrated_tray_is_the_identity() -> None:
    snap = CalibrationSnapshot(method="none")
    pdf = render_calibration_page(_payload(corrected=True, snapshot=snap), compress=False)
    assert pi.cm_matrices(pdf) == []
    assert any(t.endswith("check print with correction") for t in pi.texts(pdf))
    # A corrected job whose payload carries no snapshot at all behaves the same.
    pdf2 = render_calibration_page(_payload(corrected=True, snapshot=None), compress=False)
    assert pi.cm_matrices(pdf2) == []


def test_same_payload_gives_the_same_bytes() -> None:
    assert render_calibration_page(_payload()) == render_calibration_page(_payload())


def test_printer_name_is_text_and_never_an_operator() -> None:
    name = r"a(b)c\d) Q 0 0 0 rg (x"
    pdf = render_calibration_page(_payload(name=name), compress=False)
    assert pi.colour_operators(pdf) == set()
    assert any(name in t for t in pi.texts(pdf))


def test_a_long_printer_name_cannot_push_the_footer_into_a_square() -> None:
    pdf = render_calibration_page(_payload(name="x" * 300), compress=False)
    [t] = [t for t in pi.texts(pdf) if t.endswith("printed without correction")]
    pos = pi.text_positions(pdf)[pi.texts(pdf).index(t)]
    width = pdfmetrics.stringWidth(t, _register_font(resolve_font_path()), 6) / PT_PER_MM
    assert pos[0] / PT_PER_MM > SQUARE
    assert pos[0] / PT_PER_MM + width < A4_W - SQUARE


# ---------------------------------------------------------------------------- unsuitable


@pytest.mark.parametrize(
    "g",
    [
        Geometry("A4", 21000, 29700, 4570, 2120, 1, 12, 4820, 2120, 2130, 985, None, "rectangle"),
        Geometry("A4", 21000, 29700, 4570, 2120, 4, 1, 4820, 2120, 2130, 985, None, "rectangle"),
    ],
    ids=["one-column", "one-row"],
)
def test_unsuitable_type(g: Geometry) -> None:
    with pytest.raises(CalibrationTypeUnsuitableError) as e:
        _pdf(g)
    assert e.value.error_code == "calibration_type_unsuitable" and e.value.status == 422


# ---------------------------------------------------------------------------- footer fit (I1, I2)


def _footer_extent(pdf: bytes) -> tuple[str, float, float]:
    """The footer line (the text ending in the outcome) with its real left and right edge in mm."""
    texts = pi.texts(pdf)
    [i] = [i for i, t in enumerate(texts) if "Calibration page —" in t]
    width = pdfmetrics.stringWidth(texts[i], _register_font(resolve_font_path()), 6) / PT_PER_MM
    left = pi.text_positions(pdf)[i][0] / PT_PER_MM
    return texts[i], left, left + width


@pytest.mark.parametrize("glyph", ["W", "M", "m", "0"])
@pytest.mark.parametrize("corrected", [False, True])
def test_footer_with_wide_glyphs_stays_clear_of_both_squares(glyph: str, corrected: bool) -> None:
    pdf = render_calibration_page(
        _payload(
            corrected=corrected,
            snapshot=CalibrationSnapshot(method="none"),
            key=glyph * 200,
            name=glyph * 255,
            tray=glyph * 100,
        ),
        compress=False,
    )
    text, left, right = _footer_extent(pdf)
    assert left >= SQUARE and right <= A4_W - SQUARE, (left, right)
    # Whatever is shortened, the fixed parts stay.
    assert " v1 " in text and "2026-11-05" in text
    assert text.endswith(
        "check print with correction" if corrected else "printed without correction"
    )


def test_footer_of_the_longest_ordinary_names_is_present_and_marked() -> None:
    snap = CalibrationSnapshot(method="manual", dx_hmm=10)
    pdf = render_calibration_page(
        _payload(corrected=True, snapshot=snap, key="k" * 40, name="n" * 24, tray="t" * 24),
        compress=False,
    )
    text, left, right = _footer_extent(pdf)
    assert text.endswith("Calibration page — check print with correction")
    assert left >= SQUARE and right <= A4_W - SQUARE
    assert "k" * 40 in text  # 179 mm: fits, so nothing is cut


def test_a_footer_that_cannot_fit_is_an_error_not_a_missing_footer() -> None:
    with pytest.raises(ValueError, match="footer"):
        _pdf(L4736, footer="W" * 200)


# ---------------------------------------------------------------------------- boundary (M1, M2)

# A label corner exactly on x = 15 / y = 15 (kept), and the same 0.01 mm further in (dropped).
ON_EDGE = Geometry("A4", 21000, 29700, 1000, 1100, 3, 3, 1000, 1100, 1500, 1500, None, "rectangle")
JUST_IN = Geometry("A4", 21000, 29700, 1000, 1100, 3, 3, 1000, 1100, 1499, 1499, None, "rectangle")
# Gap lines exactly on x = 15 and y = 15 (kept whole), and 0.01 mm inside (clipped).
LINE_ON_EDGE = Geometry(
    "A4", 21000, 29700, 1000, 1100, 3, 3, 1000, 1100, 400, 500, None, "rectangle"
)
LINE_JUST_IN = Geometry(
    "A4", 21000, 29700, 1000, 1100, 3, 3, 1000, 1100, 399, 499, None, "rectangle"
)


def _marks_at(pdf: bytes, x: float, y: float) -> list[dict]:
    return [
        s
        for s in _strokes(pdf)
        if _len(s) == 1.5 and any(abs(p[0] - x) < 0.005 and abs(p[1] - y) < 0.005 for p in s["pts"])
    ]


def test_an_element_touching_a_square_edge_is_kept() -> None:
    assert len(_marks_at(_pdf(ON_EDGE), 15.0, 15.0)) == 2


def test_an_element_0_01_mm_inside_a_square_is_dropped() -> None:
    assert _marks_at(_pdf(JUST_IN), 14.99, 14.99) == []


def test_a_gap_line_on_the_edge_is_not_clipped_and_one_0_01_mm_inside_is() -> None:
    def vertical(g: Geometry, x: float) -> list[dict]:
        return [
            s
            for s in _strokes(_pdf(g))
            if _vertical(s) and abs(s["pts"][0][0] - x) < 0.005 and _len(s) > 20
        ]

    [on] = vertical(LINE_ON_EDGE, 15.0)
    assert round(min(p[1] for p in on["pts"]), 2) == 4.0  # starts at the grid top: not clipped
    [inside] = vertical(LINE_JUST_IN, 14.99)
    assert round(min(p[1] for p in inside["pts"]), 2) == 15.0  # clipped at the square


def test_a_mark_whose_legs_point_away_from_the_square_is_kept() -> None:
    # The label's bottom right corner is at (16, 16): legs run to -x and -y, both outside the
    # square. Only the bounding box of the L overlaps it, which is not "a point inside".
    # A 6 mm gap keeps the corner far from the scale of the crossing (3 mm away, the scale
    # reaches 2 mm), so the mark is not left out for that reason.
    g = Geometry("A4", 21000, 29700, 1000, 1000, 3, 3, 1600, 1600, 600, 600, None, "rectangle")
    pdf = _pdf(g)

    def legs(to: tuple[float, float]) -> int:
        return sum(
            1
            for s in _strokes(pdf)
            if any(abs(p[0] - 16.0) < 0.005 and abs(p[1] - 16.0) < 0.005 for p in s["pts"])
            and any(abs(p[0] - to[0]) < 0.005 and abs(p[1] - to[1]) < 0.005 for p in s["pts"])
        )

    assert legs((14.5, 16.0)) == 1
    assert legs((16.0, 14.5)) == 1
    assert _marks_at(pdf, 6.0, 6.0) == []  # the top left corner of that label is inside
