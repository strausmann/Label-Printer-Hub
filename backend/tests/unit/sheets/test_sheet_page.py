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
from app.sheets.sheet_page import (
    MarginIdPayload,
    SheetCellPayload,
    SheetPageDetail,
    render_preview_png,
    render_sheet_page,
)
from PIL import Image

from tests.helpers import pdf_inspect as pi

L4736 = Geometry("A4", 21000, 29700, 4570, 2120, 4, 12, 4820, 2120, 2130, 985, None, "rectangle")
V1_OTHER = Geometry("A4", 21000, 29700, 4570, 2120, 4, 12, 4900, 2200, 2000, 900, None, "rectangle")
L4731 = Geometry("A4", 21000, 29700, 2540, 1000, 7, 27, 2790, 1000, 1350, 860, 150, "rectangle")
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
    from app.sheets.reservation import _active_sheet_page_carries_margin_id

    margin = MarginIdPayload(text="X", qr_payload=None, usable_hmm=700)
    with_id = _payload(_detail(margin=margin)).model_dump(mode="json")
    without = _payload(_detail()).model_dump(mode="json")
    assert _active_sheet_page_carries_margin_id([with_id], SHEET_ID)
    assert not _active_sheet_page_carries_margin_id([without], SHEET_ID)


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
    png = render_preview_png(L4736, [(18, _cell_image(L4736, 18))], None)
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
    png = render_preview_png(g, [], margin)
    im = Image.open(io.BytesIO(png))
    assert im.size == (1275, 1650)
    inv = Image.eval(im.convert("L"), lambda v: 255 - v)
    bbox = inv.getbbox()
    assert bbox is not None
    assert bbox[3] <= round(g.margin_top * 150 / 2540)  # only in the top margin


def test_preview_is_never_calibrated() -> None:
    a = render_preview_png(L4736, [(18, _cell_image(L4736, 18))], None)
    b = render_preview_png(L4736, [(18, _cell_image(L4736, 18))], None)
    assert a == b
