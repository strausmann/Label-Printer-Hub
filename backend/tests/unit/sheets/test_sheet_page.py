"""The ``sheet_page`` payload and its renderer (Plan 3, Task 4; spec 10.2, 11.4, 12, 13)."""

from __future__ import annotations

import io
from dataclasses import asdict
from typing import Any
from uuid import uuid4

import pytest
from app.page_render.pdf import PT_PER_MM
from app.page_render.transform import IDENTITY, Deviation, correction_pdf_matrix
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.services.page_jobs import CalibrationSnapshot, PagePayload, snapshot_to_deviation
from app.sheets import cell_render
from app.sheets.cell_render import DEFAULT_CELL_RENDERER, CellImage, content_box
from app.sheets.geometry import Geometry
from app.sheets.planner import BAND_CORNER, MarginBand, MarginPlacement, margin_qr_allowed
from app.sheets.sheet_page import (
    MarginIdPayload,
    SheetCellPayload,
    SheetPageDetail,
    margin_id_payload,
    render_preview_png,
    render_sheet_page,
)
from PIL import Image

from tests.helpers import pdf_inspect as pi

L4736 = Geometry("A4", 21000, 29700, 4570, 2120, 4, 12, 4820, 2120, 2130, 985, None, "rectangle")
V1_OTHER = Geometry("A4", 21000, 29700, 4570, 2120, 4, 12, 4900, 2200, 2000, 900, None, "rectangle")
L4731 = Geometry("A4", 21000, 29700, 2540, 1000, 7, 27, 2790, 1000, 1350, 860, 150, "rectangle")
# A4, 4 x 13 labels of 40 x 20 mm, 14 rows: the right margin is 20 mm wide.
WIDE_RIGHT = Geometry(
    "A4", 21000, 29700, 4000, 2000, 4, 14, 4600, 2050, 600, 600, None, "rectangle"
)
# A4, 3 x 14 labels of 40 x 20 mm: 39 mm left and right of the grid.
SIDES = Geometry("A4", 21000, 29700, 4000, 2000, 3, 14, 4600, 2050, 600, 3900, None, "rectangle")
SHEET_ID = uuid4()


def _cell(
    n: int, ct: ContentType = ContentType.QR_TWO_LINES, mapped: bool = False
) -> SheetCellPayload:
    data = LabelData(
        source_app="t", primary_id=f"A-{n}", title=f"Item {n}", qr_payload=f"https://h/{n}"
    )
    return SheetCellPayload(
        cell=n, content_type=ct, label_data=data.model_dump(mode="json"), mapped=mapped
    )


def _detail(
    g: Geometry = L4736,
    cells: tuple[int, ...] = (18, 26),
    *,
    allow_qr: bool = True,
    id_cell: SheetCellPayload | None = None,
    margin: MarginIdPayload | None = None,
    ct: ContentType = ContentType.QR_TWO_LINES,
    feed_mark: Any = None,
) -> SheetPageDetail:
    return SheetPageDetail(
        sheet_id=SHEET_ID,
        sheet_code="L4736-0001",
        type_key="l4736rev",
        type_version_id=uuid4(),
        geometry=asdict(g),
        allow_qr=allow_qr,
        cells=[_cell(n, ct, mapped=not allow_qr) for n in cells],
        id_cell=id_cell,
        margin_id=margin,
        feed_mark=feed_mark,
        job_summary={"sheet_code": "L4736-0001", "cell_count": len(cells)},
    )


def _payload(detail: SheetPageDetail, snap: CalibrationSnapshot | None = None) -> PagePayload:
    return PagePayload(
        kind="sheet_page",
        media="A4",
        tray="auto",
        render_dpi=300,
        job_name="Sheet L4736-0001",
        calibration=snap,
        detail=detail.model_dump(mode="json"),
    )


def _pdf(detail: SheetPageDetail, snap: CalibrationSnapshot | None = None, **kw: Any) -> bytes:
    return render_sheet_page(_payload(detail, snap), compress=False, **kw)


def _image_cms(pdf: bytes) -> list[tuple[float, ...]]:
    """The placement matrices of images (no shear, positive width and height)."""
    return [m for m in pi.cm_matrices(pdf) if m[1] == 0 and m[2] == 0 and m[0] > 0 and m[3] > 0]


def _expected_cm(g: Geometry, n: int) -> tuple[float, float, float, float]:
    b = content_box(g, n)
    k = PT_PER_MM / 100
    return (b.w * k, b.h * k, b.x * k, (g.page_h - b.y - b.h) * k)


# ---------------------------------------------------------------- placement


def test_cells_placed_at_boxes() -> None:
    cms = _image_cms(_pdf(_detail()))
    assert len(cms) == 2
    for n, m in zip((18, 26), cms, strict=True):
        w, h, x, y = _expected_cm(L4736, n)
        assert m == pytest.approx((w, 0, 0, h, x, y), abs=1e-3)


def test_sheet_page_uses_pinned_version() -> None:
    # The payload carries its own geometry; the renderer has no session and reads no database.
    for g in (L4736, V1_OTHER):
        cms = _image_cms(_pdf(_detail(g, cells=(5,))))
        w, h, x, y = _expected_cm(g, 5)
        assert cms[0] == pytest.approx((w, 0, 0, h, x, y), abs=1e-3)
    a = _image_cms(_pdf(_detail(L4736, cells=(5,))))[0]
    b = _image_cms(_pdf(_detail(V1_OTHER, cells=(5,))))[0]
    assert a[4:] != pytest.approx(b[4:], abs=1e-3)


def test_id_cell_is_drawn_like_any_cell() -> None:
    d = _detail(cells=(18,), id_cell=_cell(1))
    cms = _image_cms(_pdf(d))
    assert len(cms) == 2
    assert cms[1] == pytest.approx(
        (_expected_cm(L4736, 1)[0], 0, 0, _expected_cm(L4736, 1)[1], *_expected_cm(L4736, 1)[2:]),
        abs=1e-3,
    )


# ---------------------------------------------------------------- correction


def test_snapshot_to_deviation() -> None:
    assert snapshot_to_deviation(None) == IDENTITY
    assert snapshot_to_deviation(CalibrationSnapshot(method="none")) == IDENTITY
    snap = CalibrationSnapshot(
        method="manual", dx_hmm=150, dy_hmm=-80, sx_ppm=1_001_000, sy_ppm=999_000, rotation_udeg=500
    )
    assert snapshot_to_deviation(snap) == Deviation(150, -80, 1_001_000, 999_000, 500)


def test_correction_applied_from_snapshot() -> None:
    snap = CalibrationSnapshot(method="manual", dx_hmm=150, dy_hmm=-80)
    pdf = _pdf(_detail(), snap)
    assert pi.cm_matrices(pdf)[0] == pytest.approx((1, 0, 0, 1, -4.252, -2.268), abs=1e-3)
    assert pi.cm_matrices(pdf)[0] == pytest.approx(
        correction_pdf_matrix(Deviation(150, -80), "A4"), abs=1e-6
    )


def test_no_correction_matrix_without_calibration_or_with_identity_snapshot() -> None:
    for snap in (None, CalibrationSnapshot(method="none")):
        pdf = _pdf(_detail(), snap)
        assert all(m[:4] != (1, 0, 0, 1) for m in pi.cm_matrices(pdf))
        assert len(pi.cm_matrices(pdf)) == 2  # only the two image placements


# ---------------------------------------------------------------- margin ID


def test_margin_id_drawn_only_when_in_payload() -> None:
    margin = MarginIdPayload(text="L4736-0001 · L4736REV", qr_payload=None, usable_hmm=700)
    with_id = _pdf(_detail(margin=margin))
    assert pi.texts(with_id) == ["L4736-0001 · L4736REV"]
    assert len(_image_cms(with_id)) == 2  # no QR, only the cells
    assert pi.texts(_pdf(_detail())) == []


def test_margin_id_geometry_and_qr() -> None:
    margin = MarginIdPayload(
        text="L4736-0001", qr_payload="https://h/sheet/L4736-0001", usable_hmm=1530
    )
    pdf = _pdf(_detail(cells=(), margin=margin))
    cms = _image_cms(pdf)
    assert len(cms) == 1  # the QR
    k = PT_PER_MM / 100
    bottom = L4736.margin_top - 100  # 1 mm safety above the grid
    top = bottom - 1530
    assert cms[0] == pytest.approx(
        (1530 * k, 0, 0, 1530 * k, L4736.margin_left * k, (L4736.page_h - bottom) * k), abs=1e-3
    )
    (x_pt, y_pt) = pi.text_positions(pdf)[0]
    assert x_pt / PT_PER_MM > (L4736.margin_left + 1530) / 100  # right of the QR
    y_mm = L4736.page_h / 100 - y_pt / PT_PER_MM
    assert top / 100 < y_mm < bottom / 100  # inside the usable band


# ---------------------------------------------------------------- content


def test_mapped_content_has_no_qr(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[ContentType] = []

    class Spy:
        def render(self, **kw: Any) -> CellImage:
            seen.append(kw["content_type"])
            return DEFAULT_CELL_RENDERER.render(**kw)

    def boom(*a: Any, **k: Any) -> None:
        raise AssertionError("build_qr called for an allow_qr=false payload")

    monkeypatch.setattr(cell_render, "build_qr", boom)
    d = _detail(L4731, cells=(1, 2), allow_qr=False, ct=ContentType.TEXT_TWO_LINES)
    render_sheet_page(_payload(d), renderer=Spy(), compress=False)
    assert seen == [ContentType.TEXT_TWO_LINES] * 2


def test_renderer_receives_box_and_render_dpi() -> None:
    calls: list[dict[str, Any]] = []

    class Spy:
        def render(self, **kw: Any) -> CellImage:
            calls.append(kw)
            return DEFAULT_CELL_RENDERER.render(**kw)

    render_sheet_page(_payload(_detail(cells=(18,))), renderer=Spy(), compress=False)
    b = content_box(L4736, 18)
    assert calls[0]["dpi"] == 300
    assert calls[0]["box_w_mm"] == pytest.approx(b.w / 100)
    assert calls[0]["box_h_mm"] == pytest.approx(b.h / 100)


def test_gray_only() -> None:
    margin = MarginIdPayload(text="X", qr_payload="https://h/x", usable_hmm=1530)
    pdf = _pdf(
        _detail(id_cell=_cell(1), margin=margin), CalibrationSnapshot(method="manual", dx_hmm=50)
    )
    assert pi.colour_operators(pdf) == set()
    assert all(
        i["ColorSpace"] == "/DeviceGray" and i["BitsPerComponent"] == 1 for i in pi.images(pdf)
    )


def test_determinism() -> None:
    margin = MarginIdPayload(text="X", qr_payload="https://h/x", usable_hmm=1530)
    p = _payload(
        _detail(id_cell=_cell(1), margin=margin), CalibrationSnapshot(method="manual", dx_hmm=50)
    )
    assert render_sheet_page(p) == render_sheet_page(p)


# ---------------------------------------------------------------- stored contract


def test_detail_field_names_for_in_flight_check() -> None:
    margin = MarginIdPayload(text="X", qr_payload=None, usable_hmm=700)
    stored = _payload(_detail(id_cell=_cell(1), margin=margin)).detail
    # Task 3's margin_id_in_flight reads these two keys from stored jobs; sheet_id as a string.
    assert stored["sheet_id"] == str(SHEET_ID)
    assert isinstance(stored["margin_id"], dict) and stored["margin_id"]
    assert _payload(_detail()).detail["margin_id"] is None
    # Task 8 asserts the ID cell on the stored payload: the PDF cannot tell QR from text.
    assert stored["id_cell"]["content_type"] == "qr_two_lines"
    assert stored["id_cell"]["label_data"]["qr_payload"] == "https://h/1"


def test_margin_id_in_flight_reads_what_this_module_stores() -> None:
    from app.sheets.reservation import _active_sheet_page_carries

    margin = MarginIdPayload(text="X", qr_payload=None, usable_hmm=700)
    with_id = _payload(_detail(margin=margin)).model_dump(mode="json")
    without = _payload(_detail()).model_dump(mode="json")
    assert _active_sheet_page_carries([with_id], SHEET_ID, "margin_id")
    assert not _active_sheet_page_carries([without], SHEET_ID, "margin_id")
    # the same helper, keyed on the feed mark (Task 5c): what this module stores is found
    with_mark = _payload(_detail(feed_mark=_mark())).model_dump(mode="json")
    assert _active_sheet_page_carries([with_mark], SHEET_ID, "feed_mark")
    assert not _active_sheet_page_carries([with_id], SHEET_ID, "feed_mark")
    assert not _active_sheet_page_carries([with_mark], SHEET_ID, "margin_id")


# ---------------------------------------------------------------- preview


def _cell_image(g: Geometry, n: int, dpi: int = 150) -> CellImage:
    b = content_box(g, n)
    data = LabelData(source_app="t", primary_id=f"A-{n}", title="T", qr_payload="https://h/1")
    return DEFAULT_CELL_RENDERER.render(
        box_w_mm=b.w / 100,
        box_h_mm=b.h / 100,
        dpi=dpi,
        content_type=ContentType.QR_TWO_LINES,
        data=data,
    )


def test_preview_png_size_and_mode() -> None:
    png = render_preview_png(L4736, [(18, _cell_image(L4736, 18))], None, render_dpi=600)
    im = Image.open(io.BytesIO(png))
    assert im.size == (1240, 1754)
    assert im.mode == "1"
    # Only the given cell is non-white, and inside its content box.
    b = content_box(L4736, 18)
    px = 150 / 2540
    x0, y0, x1, y1 = (
        round(b.x * px),
        round(b.y * px),
        round((b.x + b.w) * px),
        round((b.y + b.h) * px),
    )
    inv = Image.eval(im.convert("L"), lambda v: 255 - v)
    bbox = inv.getbbox()
    assert bbox is not None
    assert x0 <= bbox[0] and y0 <= bbox[1] and bbox[2] <= x1 + 1 and bbox[3] <= y1 + 1


def test_preview_letter_size_and_margin_id() -> None:
    g = Geometry(
        "Letter", 21590, 27940, 4570, 2120, 4, 12, 4820, 2120, 2130, 985, None, "rectangle"
    )
    margin = MarginIdPayload(text="L-1", qr_payload="https://h/s/L-1", usable_hmm=1530)
    png = render_preview_png(g, [], margin, render_dpi=600)
    im = Image.open(io.BytesIO(png))
    assert im.size == (1275, 1650)
    inv = Image.eval(im.convert("L"), lambda v: 255 - v)
    bbox = inv.getbbox()
    assert bbox is not None
    assert bbox[3] <= round(g.margin_top * 150 / 2540)  # only in the top margin


def test_preview_is_never_calibrated() -> None:
    a = render_preview_png(L4736, [(18, _cell_image(L4736, 18))], None, render_dpi=600)
    b = render_preview_png(L4736, [(18, _cell_image(L4736, 18))], None, render_dpi=600)
    assert a == b


# ---------------------------------------------------------------- margin QR rule (T4-1)

_URL = "https://hub.example/sheet/L4736-0001"
_URL33 = "x" * 46  # a 33-module symbol (version 4)


def _margin_pdf(usable: int, qr: str | None, dpi: int) -> bytes:
    margin = MarginIdPayload(text="L4736-0001", qr_payload=qr, usable_hmm=usable)
    p = _payload(_detail(cells=(), margin=margin)).model_copy(update={"render_dpi": dpi})
    return render_sheet_page(p, compress=False)


def _drawn_module_px(edge_px: int, payload: str) -> int:
    """Module size of the symbol ``build_qr`` makes: the first dark run is a finder (7 modules)."""
    qr = cell_render.build_qr(payload, edge_px)
    assert qr is not None
    row = qr.convert("L")
    for y in range(qr.height):
        run = 0
        for x in range(qr.width):
            if row.getpixel((x, y)) == 0:
                run += 1
            elif run:
                break
        if run:
            return run // 7
    raise AssertionError("no dark pixel")


@pytest.mark.parametrize("usable", [400, 600, 899])
def test_margin_qr_never_below_nine_mm(usable: int) -> None:
    pdf = _margin_pdf(usable, _URL, 600)
    assert _image_cms(pdf) == []
    assert pi.texts(pdf) == ["L4736-0001"]


def test_margin_qr_not_drawn_when_pixel_module_is_too_small() -> None:
    # 33 modules + quiet zone = 41; 10.3 mm at 300 dpi is 122 px -> 2 px modules = 0.169 mm.
    pdf = _margin_pdf(1030, _URL33, 300)
    assert _image_cms(pdf) == []
    assert pi.texts(pdf) == ["L4736-0001"]


def test_margin_qr_drawn_with_module_of_a_quarter_mm() -> None:
    pdf = _margin_pdf(1530, _URL, 300)
    assert len(_image_cms(pdf)) == 1
    edge = pi.images(pdf)[0]["Width"]
    assert _drawn_module_px(edge, _URL) * 25.4 / 300 >= 0.25


@pytest.mark.parametrize("dpi", [150, 300, 600])
@pytest.mark.parametrize("usable", [800, 900, 1030, 1200, 1530])
@pytest.mark.parametrize("payload", [_URL, _URL33])
def test_planner_and_renderer_agree_on_margin_qr(payload: str, usable: int, dpi: int) -> None:
    allowed = margin_qr_allowed(usable, payload, dpi)
    pdf = _margin_pdf(usable, payload, dpi)
    drawn = len(_image_cms(pdf)) == 1
    assert drawn == allowed
    edge = round(usable / 100 / 25.4 * dpi)
    module_mm = _drawn_module_px(edge, payload) * 25.4 / dpi
    if drawn:
        assert module_mm >= 0.25
    else:
        assert usable < 900 or module_mm < 0.25  # independent of margin_qr_allowed


# ---------------------------------------------------------------- review minors


def test_text_only_margin_id_is_left_aligned_with_the_grid() -> None:
    pdf = _pdf(_detail(cells=(), margin=MarginIdPayload(text="X", usable_hmm=700)))
    assert pi.text_positions(pdf)[0][0] / PT_PER_MM == pytest.approx(
        L4736.margin_left / 100, abs=0.01
    )


def test_long_margin_text_shrinks_then_is_shortened_inside_the_grid() -> None:
    from app.page_render.pdf import text_width_mm

    long = "L4736-0001 · " + "very long sheet type name " * 8
    pdf = _pdf(_detail(cells=(), margin=MarginIdPayload(text=long, usable_hmm=700)))
    (shown,) = pi.texts(pdf)
    assert shown.endswith("…") and len(shown) < len(long)
    grid_w = ((L4736.cols - 1) * L4736.pitch_x + L4736.label_w) / 100
    assert text_width_mm(shown, 6.0) <= grid_w
    mid = "L4736-0001 · Avery Zweckform"
    (kept,) = pi.texts(_pdf(_detail(cells=(), margin=MarginIdPayload(text=mid, usable_hmm=700))))
    assert kept == mid


def test_preview_text_only_margin_id_draws_inside_the_top_margin() -> None:
    png = render_preview_png(
        L4736, [], MarginIdPayload(text="L4736-0001", usable_hmm=700), render_dpi=600
    )
    inv = Image.eval(Image.open(io.BytesIO(png)).convert("L"), lambda v: 255 - v)
    bbox = inv.getbbox()
    assert bbox is not None
    assert bbox[0] >= round(L4736.margin_left * 150 / 2540) - 1
    assert bbox[3] <= round(L4736.margin_top * 150 / 2540)


def test_detail_rejects_bad_cell_numbers_and_ignores_unknown_keys() -> None:
    base = _detail().model_dump(mode="json")
    with pytest.raises(ValueError, match=r"1\.\.48"):
        SheetPageDetail.model_validate({**base, "cells": [_cell(49).model_dump(mode="json")]})
    dup = [_cell(5).model_dump(mode="json")] * 2
    with pytest.raises(ValueError, match="unique"):
        SheetPageDetail.model_validate({**base, "cells": dup})
    assert SheetPageDetail.model_validate({**base, "from_the_future": 1}).sheet_id == SHEET_ID


# ---------------------------------------------------------------- one decision, stored (T4-2)


def _preview_has_qr(margin: MarginIdPayload, g: Geometry = L4736) -> bool:
    """A QR moves the text next to it and fills the square: the page differs from the same
    margin ID without a payload."""
    text_only = margin.model_copy(update={"qr_payload": None, "qr_allowed": None})
    return render_preview_png(g, [], margin, render_dpi=600) != render_preview_png(
        g, [], text_only, render_dpi=600
    )


def test_preview_and_pdf_agree_for_eleven_mm_at_600_dpi() -> None:
    margin = MarginIdPayload(text="L4736-0001", qr_payload=_URL, usable_hmm=1100)
    assert len(_image_cms(_margin_pdf(1100, _URL, 600))) == 1  # the job prints a QR
    assert _preview_has_qr(margin)  # and the preview shows one


def _band_rect(g: Geometry, band: MarginBand, d: int) -> tuple[int, int, int, int]:
    """(x, y, w, h) of the band's QR square or text strip, written out from the layout table."""
    safety = 100
    grid_right = g.margin_left + (g.cols - 1) * g.pitch_x + g.label_w
    grid_bottom = g.margin_top + (g.rows - 1) * g.pitch_y + g.label_h
    width = grid_right - g.margin_left
    height = grid_bottom - g.margin_top
    return {
        "top": (g.margin_left, g.margin_top - safety - d, width, d),
        "bottom": (g.margin_left, grid_bottom + safety, width, d),
        "right": (grid_right + safety, g.margin_top, d, height),
        "left": (g.margin_left - safety - d, g.margin_top, d, height),
    }[band]


def _band_pdf(g: Geometry, margin: MarginIdPayload, dpi: int) -> bytes:
    p = _payload(_detail(g, cells=(), margin=margin)).model_copy(update={"render_dpi": dpi})
    return render_sheet_page(p, compress=False)


def _ink_box(png: bytes) -> tuple[int, int, int, int]:
    inv = Image.eval(Image.open(io.BytesIO(png)).convert("L"), lambda v: 255 - v)
    bbox = inv.getbbox()
    assert bbox is not None
    return bbox


@pytest.mark.parametrize("band", ["top", "bottom", "right", "left"])
@pytest.mark.parametrize("dpi", [150, 200, 300, 600])
@pytest.mark.parametrize("usable", [800, 950, 1100, 1300, 1530])
@pytest.mark.parametrize("payload", [_URL, _URL33])
def test_preview_matches_job_on_margin_band_and_qr(
    payload: str, usable: int, dpi: int, band: MarginBand
) -> None:
    g = L4736 if band in ("top", "bottom") else SIDES
    placement = MarginPlacement(
        band, BAND_CORNER[band], usable, margin_qr_allowed(usable, payload, dpi)
    )
    margin = margin_id_payload("L4736-0001", payload, placement)
    assert margin.band == band
    assert margin.corner == BAND_CORNER[band]
    assert margin.usable_hmm == usable
    assert margin.qr_allowed == placement.qr

    cms = _image_cms(_band_pdf(g, margin, dpi))
    assert (len(cms) == 1) == placement.qr
    x, y, w, h = _band_rect(g, band, usable)
    k = PT_PER_MM / 100
    if placement.qr:
        assert cms[0] == pytest.approx(
            (usable * k, 0, 0, usable * k, x * k, (g.page_h - y - usable) * k), abs=1e-3
        )
    assert _preview_has_qr(margin, g) == placement.qr

    left, top, right, bottom = _ink_box(render_preview_png(g, [], margin, render_dpi=600))
    s = 150 / 2540
    assert left >= round(x * s) - 1 and right <= round((x + w) * s) + 1
    assert top >= round(y * s) - 1 and bottom <= round((y + h) * s) + 1


def test_flag_is_what_both_renderers_obey() -> None:
    # The flag, not the rule, decides: a stored False wins over a payload the rule would allow.
    margin = MarginIdPayload(text="X", qr_payload=_URL, usable_hmm=1530, qr_allowed=False)
    assert _image_cms(_margin_pdf_of(margin, 600)) == []
    assert not _preview_has_qr(margin)


def test_payload_without_flag_falls_back_to_the_rule_at_render_dpi() -> None:
    old = MarginIdPayload.model_validate(
        {"text": "X", "qr_payload": _URL, "usable_hmm": 1100}  # as stored before the flag
    )
    assert old.qr_allowed is None
    assert len(_image_cms(_margin_pdf_of(old, 600))) == 1
    assert _image_cms(_margin_pdf_of(old, 150)) == []


def _margin_pdf_of(margin: MarginIdPayload, dpi: int) -> bytes:
    p = _payload(_detail(cells=(), margin=margin)).model_copy(update={"render_dpi": dpi})
    return render_sheet_page(p, compress=False)


# ---------------------------------------------------------------- the four bands (Task 5b)


def test_margin_id_payload_takes_planner_decision() -> None:
    url = "https://h/sheet/L4736-0001"
    off = margin_id_payload("X", url, MarginPlacement("bottom", "bottom_left", 1530, False))
    assert off.qr_payload is None
    assert off.qr_allowed is False
    assert (off.band, off.corner, off.usable_hmm) == ("bottom", "bottom_left", 1530)
    on = margin_id_payload("X", url, MarginPlacement("bottom", "bottom_left", 1530, True))
    assert on.qr_payload == url
    assert on.qr_allowed is True


def _text_origin_mm(pdf: bytes) -> tuple[float, float]:
    """The text origin as (x, y from the top of the page) in millimetres."""
    x, y = pi.text_positions(pdf)[0]
    return x / PT_PER_MM, L4736.page_h / 100 - y / PT_PER_MM


def test_margin_id_bottom_band_geometry() -> None:
    margin = MarginIdPayload(
        text="L4736-0001", qr_payload=_URL, usable_hmm=1530, qr_allowed=True, band="bottom"
    )
    pdf = _band_pdf(L4736, margin, 300)
    k = PT_PER_MM / 100
    assert _image_cms(pdf) == [
        pytest.approx((1530 * k, 0, 0, 1530 * k, 985 * k, 500 * k), abs=1e-3)
    ]
    x, y = _text_origin_mm(pdf)
    assert x > (985 + 1530) / 100
    assert 276.70 < y < 292.00


def test_margin_id_right_band_rotated() -> None:
    margin = MarginIdPayload(
        text="L4736-0001",
        qr_payload=_URL,
        usable_hmm=2000,
        qr_allowed=True,
        band="right",
        corner="top_right",
    )
    pdf = _band_pdf(WIDE_RIGHT, margin, 300)
    k = PT_PER_MM / 100
    assert _image_cms(pdf) == [
        pytest.approx((2000 * k, 0, 0, 2000 * k, 18500 * k, (29700 - 600 - 2000) * k), abs=1e-3)
    ]
    (rotated,) = [m for m in pi.cm_matrices(pdf) if m[1] == -1]
    assert rotated[:4] == (0, -1, 1, 0)
    x_pt, y_pt = pi.text_positions(pdf)[0]
    assert (rotated[4], rotated[5]) == pytest.approx((x_pt, y_pt), abs=1e-6)
    assert 185.0 < x_pt / PT_PER_MM < 205.0
    assert 297.0 - y_pt / PT_PER_MM == pytest.approx(28.0, abs=0.01)


def test_margin_id_left_band_text_only() -> None:
    margin = MarginIdPayload(text="L4736-0001", usable_hmm=585, band="left", corner="top_left")
    pdf = _band_pdf(L4736, margin, 300)
    assert pi.texts(pdf) == ["L4736-0001"]
    assert len([m for m in pi.cm_matrices(pdf) if m[1] == -1]) == 1
    x, y = _text_origin_mm(pdf)
    assert 3.0 < x < 8.85
    assert y == pytest.approx(21.3, abs=0.01)


def test_stored_band_wins() -> None:
    # Top and bottom are equally deep here; the renderer reads no hardware margins and makes
    # no choice of its own, it draws where the payload says.
    margin = margin_id_payload(
        "L4736-0001", _URL, MarginPlacement("bottom", "bottom_left", 1530, True)
    )
    (cm,) = _image_cms(_band_pdf(L4736, margin, 600))
    k = PT_PER_MM / 100
    assert cm == pytest.approx((1530 * k, 0, 0, 1530 * k, 985 * k, 500 * k), abs=1e-3)


def test_preview_draws_stored_band() -> None:
    s = 150 / 2540
    bottom = margin_id_payload(
        "L4736-0001", _URL, MarginPlacement("bottom", "bottom_left", 1530, True)
    )
    _, top, _, low = _ink_box(render_preview_png(L4736, [], bottom, render_dpi=600))
    assert top >= round(27670 * s) - 1 and low <= round(29200 * s) + 1
    right = margin_id_payload("L4736-0001", _URL, MarginPlacement("right", "top_right", 2000, True))
    left, _, edge, _ = _ink_box(render_preview_png(WIDE_RIGHT, [], right, render_dpi=600))
    assert left >= round(18500 * s) - 1 and edge <= round(20500 * s) + 1


# ---------------------------------------------------------------- feed-direction mark (Task 5c)

EN_MARK = "▲ Top \u2013 this edge first"
DE_MARK = "▲ Oben \u2013 diese Kante zuerst"


def _mark(**kw: Any) -> Any:
    from app.sheets import sheet_page

    fields: dict[str, Any] = {
        "text": EN_MARK, "x_hmm": 17300, "baseline_y_hmm": 1354, "size_pt": 7.0,
    }  # fmt: skip
    fields.update(kw)
    return sheet_page.FeedMarkPayload(**fields)


def _ink(png: bytes) -> Image.Image:
    return Image.eval(Image.open(io.BytesIO(png)).convert("L"), lambda v: 255 - v)


def test_feed_mark_drawn_from_payload() -> None:
    pdf = _pdf(_detail(cells=(), feed_mark=_mark()))
    assert pi.texts(pdf) == [EN_MARK]
    x, y = pi.text_positions(pdf)[0]
    assert (x, y) == pytest.approx((173.00 * PT_PER_MM, (297.00 - 13.54) * PT_PER_MM), abs=1e-3)
    assert _image_cms(pdf) == []
    # The renderer does not place it again: a payload at 10 mm is drawn at 10 mm.
    moved = _pdf(_detail(cells=(), feed_mark=_mark(x_hmm=1000)))
    assert pi.text_positions(moved)[0][0] == pytest.approx(10.00 * PT_PER_MM, abs=1e-3)


def test_old_payload_has_no_feed_mark() -> None:
    d = SheetPageDetail.model_validate(
        {k: v for k, v in _detail().model_dump(mode="json").items() if k != "feed_mark"}
    )
    assert d.feed_mark is None


def test_feed_mark_payload_copies_the_placement() -> None:
    from app.sheets import planner, sheet_page

    placement = planner.FeedMarkPlacement(DE_MARK, 16508, 1354, 7.0, 3507)
    got = sheet_page.feed_mark_payload(placement)
    assert (got.text, got.x_hmm, got.baseline_y_hmm, got.size_pt) == (DE_MARK, 16508, 1354, 7.0)
    assert (got.band, got.anchor) == ("top", "top_right")


def test_id_text_ends_before_the_mark() -> None:
    from app.page_render.pdf import text_width_mm

    long = "L4736-0001 · " + "very long sheet type name " * 8
    base = MarginIdPayload(text=long, usable_hmm=700)
    limited = base.model_copy(update={"text_end_hmm": 17100})
    (cut,) = pi.texts(_pdf(_detail(cells=(), margin=limited)))
    (free,) = pi.texts(_pdf(_detail(cells=(), margin=base)))
    text_x = L4736.margin_left
    assert text_width_mm(cut.removesuffix("…"), 6.0) <= (17100 - text_x) / 100
    assert text_width_mm(free.removesuffix("…"), 6.0) <= (20015 - text_x) / 100  # grid_right
    assert len(cut) < len(free)


def test_margin_id_payload_takes_text_end() -> None:
    m = margin_id_payload(
        "L4736-0001", _URL, MarginPlacement("top", "top_left", 1530, True), text_end_hmm=17100
    )
    assert m.text_end_hmm == 17100
    assert (
        margin_id_payload("x", None, MarginPlacement("top", "top_left", 700, False)).text_end_hmm
        is None
    )


def test_text_end_applies_to_the_top_band_only() -> None:
    from app.page_render.pdf import text_width_mm

    long = "L4736-0001 · " + "very long sheet type name " * 8
    bottom = MarginIdPayload(text=long, usable_hmm=700, band="bottom", text_end_hmm=5000)
    (shown,) = pi.texts(_pdf(_detail(cells=(), margin=bottom)))
    assert text_width_mm(shown.removesuffix("…"), 6.0) > (5000 - L4736.margin_left) / 100


def test_preview_draws_feed_mark() -> None:
    from app.sheets import sheet_page

    png = render_preview_png(L4736, [], None, feed_mark=_mark(), render_dpi=600)
    ink = _ink(png)
    bbox = ink.getbbox()
    assert bbox is not None
    assert bbox[0] >= round(17300 * 150 / 2540) - 1
    assert bbox[2] <= round(20015 * 150 / 2540) + 1
    assert bbox[3] <= round(2030 * 150 / 2540)
    assert sheet_page.PREVIEW_DPI == 150


def _black(png: bytes) -> set[tuple[int, int]]:
    im = _ink(png)
    w, h = im.size
    px = im.load()
    assert px is not None
    return {(x, y) for y in range(h) for x in range(w) if px[x, y] > 127}


def test_id_strips_never_cover_the_feed_mark_in_the_preview() -> None:
    """Review 5b, Minor 1: the mark's ink must survive whatever the ID draws around it."""
    # (a) both share the top band, the case the planner produces for L4736REV
    top = margin_id_payload("L4736-0001", _URL, MarginPlacement("top", "top_left", 1530, True),
                            text_end_hmm=17100)  # fmt: skip
    alone = _black(render_preview_png(L4736, [], None, feed_mark=_mark(), render_dpi=600))
    both = _black(render_preview_png(L4736, [], top, feed_mark=_mark(), render_dpi=600))
    assert alone and alone <= both
    # (b) a rotated ID, with a stored mark placed where the rotated text's paste would land:
    # the mark's ink must stay even though the turned text is a separate image
    right = margin_id_payload("L4736-0001-" + "x" * 30, _URL,
                              MarginPlacement("right", "top_right", 2000, False))  # fmt: skip
    under = _mark(x_hmm=18600, baseline_y_hmm=WIDE_RIGHT.margin_top + 1500)
    only_mark = _black(render_preview_png(WIDE_RIGHT, [], None, feed_mark=under, render_dpi=600))
    with_id = _black(render_preview_png(WIDE_RIGHT, [], right, feed_mark=under, render_dpi=600))
    assert only_mark and only_mark <= with_id


async def test_stored_mark_text_wins(
    async_session_factory: Any,
) -> None:
    """The renderers take no language: the stored text is drawn whatever the setting says."""
    from app.settings_store import SettingsStore

    store = SettingsStore()
    async with async_session_factory() as s:
        await store.load(s)
        await store.set_many(s, {"general.language": "de"})
    detail = _detail(cells=(), feed_mark=_mark(text=DE_MARK, x_hmm=16508))
    before_pdf = _pdf(detail)
    before_png = render_preview_png(
        L4736, [], None, feed_mark=_mark(text=DE_MARK, x_hmm=16508), render_dpi=600
    )
    async with async_session_factory() as s:
        await store.set_many(s, {"general.language": "en"})
    assert store.get("general.language") == "en"
    assert pi.texts(_pdf(detail)) == [DE_MARK] == pi.texts(before_pdf)
    again = render_preview_png(
        L4736, [], None, feed_mark=_mark(text=DE_MARK, x_hmm=16508), render_dpi=600
    )
    assert again == before_png


def test_turned_text_paste_never_erases_ink() -> None:
    """Whatever is on the page stays: the strip contributes its ink only (5b Minor 1)."""
    from app.sheets import sheet_page

    page = Image.new("1", (300, 300), 0)  # a page that is black everywhere
    lay = sheet_page._MarginLayout(None, "L4736-0001", 10, 10, 8.0, 90)
    font = cell_render.load_cell_font(20)
    sheet_page._paste_turned_text(page, lay, font, (150, 20))
    assert page.getextrema() == (0, 0)  # an opaque white strip would leave white pixels


# ---------------------------------------------------------------- narrow top band (fix round 1, I1)


def _narrow(page_w: int) -> Geometry:
    """A 1-column page ``page_w`` wide; the grid starts 5 mm in and ends 5 mm before the edge."""
    return Geometry(
        "A4", page_w, 29700, page_w - 1000, 2600, 1, 10, page_w - 1000, 2700, 1700, 500, None,
        "rectangle",
    )  # fmt: skip


def _decide(g: Geometry) -> tuple[Any, Any]:
    from app.page_render.transform import Deviation
    from app.sheets.planner import MarginContext, PlacementIn, SheetView, plan

    view = SheetView(
        code="L4736-0001", type_key="t", type_version_id=uuid4(), geometry=g, allow_qr=True,
        non_free={}, id_placement="margin", id_printed=False, has_hub_cell=False,
        margin_id_in_flight=False, state="active",
    )  # fmt: skip
    ctx = MarginContext(Deviation(), lambda c: f"https://hub.example/sheet/{c}", 600, None)
    page = plan([PlacementIn(view, "first_free", count=1)], 1, hw_margins_hmm=None, margin=ctx)
    return page.pages[0].margin_placement, page.pages[0].feed_mark


def _id_payload(placement: Any, mark: Any) -> MarginIdPayload:
    from app.sheets.planner import MARGIN_TEXT_GAP_HMM

    return margin_id_payload(
        "L4736-0001 · Avery L4736REV-25 · sheet ID",
        "https://hub.example/sheet/L4736-0001",
        placement,
        text_end_hmm=None if mark is None else mark.x_hmm - MARGIN_TEXT_GAP_HMM,
    )


def _detail_for(g: Geometry, mid: Any, mark: Any) -> SheetPageDetail:
    return SheetPageDetail(
        sheet_id=SHEET_ID, sheet_code="L4736-0001", type_key="t", type_version_id=uuid4(),
        geometry=asdict(g), allow_qr=True, cells=[], margin_id=mid, feed_mark=mark,
        job_summary={},
    )  # fmt: skip


def test_narrow_top_band_collapsed_ellipsis_is_not_drawn_over_the_mark() -> None:
    """The reviewer's repro: 40 mm page, default hardware margins. The mark starts at 685; the
    ID text used to collapse to an ellipsis drawn from 500 to 712."""
    from app.sheets.sheet_page import feed_mark_payload

    g = _narrow(4000)
    placement, mark = _decide(g)
    assert mark is not None and mark.x_hmm == 685
    # Spec 10.2a: the ID chooses with the shorter band like any other; the top has no room left.
    assert placement is None or placement.band != "top"
    # Whatever a stored payload says, the text never passes text_end_hmm.
    forced = MarginIdPayload(
        text="L4736-0001 · Avery", usable_hmm=1100, text_end_hmm=mark.x_hmm - 200
    )
    pdf = _pdf(_detail_for(g, forced, feed_mark_payload(mark)))
    from app.page_render.pdf import text_width_mm

    drawn = [
        (x / PT_PER_MM * 100, t)
        for (x, _), t in zip(pi.text_positions(pdf), pi.texts(pdf), strict=True)
    ]
    for x, t in drawn:
        if t != mark.text:
            assert x + text_width_mm(t, 6.0) * 100 <= mark.x_hmm - 200 + 1


def test_id_and_mark_never_overlap_over_a_sweep_of_narrow_widths() -> None:
    from app.page_render.pdf import text_width_mm
    from app.sheets.sheet_page import feed_mark_payload

    for page_w in range(1500, 6100, 100):
        g = _narrow(page_w)
        placement, mark = _decide(g)
        if mark is None:
            continue
        mp = feed_mark_payload(mark)
        mid = _id_payload(placement, mark) if placement is not None else None
        # PDF: no ID text reaches past the gap in front of the mark
        pdf = _pdf(_detail_for(g, mid, mp))
        for (x, _), t in zip(pi.text_positions(pdf), pi.texts(pdf), strict=True):
            if t == mark.text or placement is None or placement.band != "top":
                continue
            assert x / PT_PER_MM * 100 + text_width_mm(t, 6.0) * 100 <= mark.x_hmm - 200 + 1, page_w
        # Preview: the ID's ink and the mark's ink share no pixel
        only_mark = _black(render_preview_png(g, [], None, feed_mark=mp, render_dpi=600))
        only_id = _black(render_preview_png(g, [], mid, feed_mark=None, render_dpi=600))
        both = _black(render_preview_png(g, [], mid, feed_mark=mp, render_dpi=600))
        assert only_mark and not (only_mark & only_id), page_w
        assert both == only_mark | only_id, page_w


# ------------------------------------------------------------------ 266-02, 266-03, 266-05


def test_preview_without_qr_draws_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """266-03: a margin ID whose QR cannot be built after all is drawn as text, no crash."""
    from app.sheets import sheet_page

    margin = MarginIdPayload(text="L4736-0001", qr_payload=_URL, usable_hmm=1100)
    monkeypatch.setattr(sheet_page, "build_qr_preview", lambda *a, **k: None)
    png = render_preview_png(L4736, [], margin, render_dpi=600)
    text_only = MarginIdPayload(text="L4736-0001", usable_hmm=1100)
    assert png == render_preview_png(L4736, [], text_only, render_dpi=600)
    left, _, right, bottom = _ink_box(png)
    assert right - left > 20  # the code is drawn
    assert bottom <= round(L4736.margin_top * 150 / 2540)


def test_preview_margin_text_width_matches_pdf() -> None:
    """266-05: the preview's margin ID is as long as the PDF's (within 0.2 mm), because the
    preview uses the fractional font size the PDF uses, not a whole-pixel one.

    The PDF draws the bundled font's outlines at ``size_pt``; their ink is measured from the
    same font rasterised at 2400 dpi, so side bearings do not count against either side."""
    from app.page_render.pdf import resolve_font_path
    from app.sheets.sheet_page import _margin_layout
    from PIL import ImageDraw, ImageFont

    def pdf_ink_mm(text: str, size_pt: float, dpi: int = 2400) -> float:
        font = ImageFont.truetype(str(resolve_font_path()), size_pt * dpi / 72)
        strip = Image.new("L", (round(font.getlength(text)) + 40, round(font.size * 3)), 255)
        ImageDraw.Draw(strip).text((20, round(font.size * 2)), text, font=font, fill=0, anchor="ls")
        box = Image.eval(strip, lambda v: 255 - v).getbbox()
        assert box is not None
        return (box[2] - box[0]) * 25.4 / dpi

    text = "L4736-0001 · Avery Zweckform L4736REV"
    for usable in (500, 700, 1100, 1530):
        margin = MarginIdPayload(text=text, usable_hmm=usable)
        lay = _margin_layout(L4736, margin, with_qr=False)
        want_mm = pdf_ink_mm(lay.text, lay.size_pt)
        left, _, right, _ = _ink_box(render_preview_png(L4736, [], margin, render_dpi=600))
        got_mm = (right - left) * 25.4 / 150
        assert abs(got_mm - want_mm) <= 0.2, (usable, lay.size_pt, got_mm, want_mm)


def test_render_preview_png_needs_the_render_dpi() -> None:
    """266-02: no default dpi, so a stored payload is never previewed at a guessed one."""
    import inspect

    param = inspect.signature(render_preview_png).parameters["render_dpi"]
    assert param.default is inspect.Parameter.empty
    assert param.kind is inspect.Parameter.KEYWORD_ONLY


def test_the_preview_font_is_read_from_disk_once_per_size(monkeypatch: pytest.MonkeyPatch) -> None:
    """T11 M4: the margin ID and the feed mark no longer load the font file on every preview."""
    from app.sheets import sheet_page
    from PIL import ImageFont

    real = ImageFont.truetype
    loads: list[float] = []

    def counting(path: str, size: float) -> ImageFont.FreeTypeFont:
        loads.append(size)
        return real(path, size)

    sheet_page._preview_font.cache_clear()
    monkeypatch.setattr(sheet_page.ImageFont, "truetype", counting)
    first = sheet_page._preview_font(12.5)
    assert sheet_page._preview_font(12.5) is first
    sheet_page._preview_font(20.0)
    assert loads == [12.5, 20.0]
    sheet_page._preview_font.cache_clear()
