"""Cell renderer for sheet labels (Plan 3, Task 1; spec 12.1, 12.3, 12.5)."""

from __future__ import annotations

import math

import pytest
from app.page_render.pdf import resolve_font_path
from app.printer_backends.exceptions import ContentTypeDataMismatchError
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.schemas.label_data_item import LabelDataItem
from app.services.layout_engine import REQUIRED_FIELDS, LayoutEngine
from app.sheets.cell_render import (
    DEFAULT_CELL_RENDERER,
    MIN_CAP_HEIGHT_MM,
    BoxHmm,
    RasterCellRenderer,
    build_qr,
    cap_height_px,
    content_box,
    load_cell_font,
    map_content_type,
    min_font_px,
)
from app.sheets.geometry import Geometry
from PIL import Image, ImageFont


def _geometry(
    *,
    shape: str = "rectangle",
    radius: int | None = None,
    label_w: int = 4570,
    label_h: int = 2120,
) -> Geometry:
    return Geometry(
        page_size="A4",
        page_w=21000,
        page_h=29700,
        label_w=label_w,
        label_h=label_h,
        cols=4,
        rows=12,
        pitch_x=4750,
        pitch_y=2120,
        margin_top=2130,
        margin_left=985,
        corner_radius=radius,
        shape=shape,  # type: ignore[arg-type]
    )


def _data(**kw: object) -> LabelData:
    base: dict[str, object] = {"source_app": "test"}
    base.update(kw)
    return LabelData(**base)  # type: ignore[arg-type]


def _render(
    ct: ContentType,
    data: LabelData,
    *,
    w_mm: float = 42.5,
    h_mm: float = 18.0,
    dpi: int = 600,
):  # type: ignore[no-untyped-def]
    return DEFAULT_CELL_RENDERER.render(
        box_w_mm=w_mm, box_h_mm=h_mm, dpi=dpi, content_type=ct, data=data
    )


def test_content_box_l4736() -> None:
    assert content_box(_geometry(), 1) == BoxHmm(985 + 160, 2130 + 160, 4570 - 320, 2120 - 320)


def test_content_box_known_radius_l4731rev() -> None:
    g = _geometry(radius=150, label_w=4570, label_h=1000)
    assert content_box(g, 1) == BoxHmm(985 + 145, 2130 + 145, 4570 - 290, 1000 - 290)


def test_content_box_second_cell_uses_cell_origin() -> None:
    assert content_box(_geometry(), 2).x == 985 + 4750 + 160


def test_content_box_round_is_inscribed_square() -> None:
    g = _geometry(shape="round", label_w=4000, label_h=4000)
    side = round(4000 / math.sqrt(2)) - 200
    box = content_box(g, 1)
    assert (box.w, box.h) == (side, side)
    assert box.x == 985 + (4000 - side) // 2
    assert box.y == 2130 + (4000 - side) // 2


@pytest.mark.parametrize(
    ("ct", "mapped_to"),
    [
        (ContentType.QR_ONLY, ContentType.TEXT_ONE_LINE),
        (ContentType.QR_ONE_LINE, ContentType.TEXT_ONE_LINE),
        (ContentType.QR_TWO_LINES, ContentType.TEXT_TWO_LINES),
        (ContentType.QR_THREE_LINES, ContentType.TEXT_TWO_LINES),
        (ContentType.QR_WITH_LISTING, ContentType.TEXT_TWO_LINES),
    ],
)
def test_map_content_type_without_qr(ct: ContentType, mapped_to: ContentType) -> None:
    assert map_content_type(ct, allow_qr=False) == (mapped_to, True)
    assert map_content_type(ct, allow_qr=True) == (ct, False)


@pytest.mark.parametrize("ct", [ContentType.TEXT_ONE_LINE, ContentType.TEXT_TWO_LINES])
def test_map_content_type_text_types_never_mapped(ct: ContentType) -> None:
    assert map_content_type(ct, allow_qr=False) == (ct, False)
    assert map_content_type(ct, allow_qr=True) == (ct, False)


def test_image_exact_size_and_mode() -> None:
    cell = _render(ContentType.QR_TWO_LINES, _data(qr_payload="x", primary_id="A", title="b"))
    assert cell.image.size == (1004, 425)
    assert cell.image.mode == "1"
    assert cell.truncated is False


def _ink_bbox(img: Image.Image) -> tuple[int, int, int, int]:
    box = Image.eval(img.convert("L"), lambda v: 255 - v).getbbox()
    assert box is not None
    return box


def _qr_flaws(area: Image.Image) -> list[str]:
    """Whole-pixel modules and a four-module quiet zone inside ``area``; [] when both hold."""
    left, top, right, bottom = _ink_bbox(area)
    gray = area.convert("L")
    run = 0
    while gray.getpixel((left + run, top)) == 0:
        run += 1
    flaws: list[str] = []
    if run % 7 != 0:  # the finder pattern is 7 modules wide
        flaws.append(f"finder run {run} is not 7 whole modules")
        return flaws
    module = run // 7
    if module < 1:
        flaws.append("module < 1 px")
        return flaws
    width, height = area.size
    for name, gap in (
        ("left", left),
        ("top", top),
        ("right", width - right),
        ("bottom", height - bottom),
    ):
        if gap < 4 * module:
            flaws.append(f"quiet zone {name} {gap} < 4 modules ({4 * module})")
    if (right - left) % module != 0:
        flaws.append("QR width is not a whole number of modules")
    return flaws


def test_qr_modules_whole_pixels_and_quiet_zone() -> None:
    cell = _render(
        ContentType.QR_TWO_LINES,
        _data(qr_payload="https://example.test/sheet/ABC123", primary_id="ID-1", title="Title"),
    )
    area = cell.image.crop((0, 0, 425, 425))  # QR edge = box height
    assert _qr_flaws(area) == []


def test_tape_qr_builder_violates_the_rules() -> None:
    """Counter-test: the tape builder (border 0, NEAREST resize) fails the same check."""
    tape = LayoutEngine._build_qr_image("https://example.test/sheet/ABC123", 425)
    canvas = Image.new("1", (425, 425), 1)
    canvas.paste(tape, (0, 0))
    assert _qr_flaws(canvas) != []


def test_build_qr_fit_and_none() -> None:
    img = build_qr("https://example.test/s/1", 425)
    assert img is not None
    assert img.size == (425, 425)
    assert img.mode == "1"
    assert build_qr("x" * 1000, 100) is None  # module would be < 1 px
    assert build_qr("x" * 3000, 5000) is None  # more data than the largest QR holds


def test_text_shrinks_then_truncates() -> None:
    # "W" has flat top and bottom: the ink height of its line is exactly the cap height.
    cell = _render(
        ContentType.TEXT_TWO_LINES,
        _data(primary_id="A1", title="W" * 200),
        w_mm=25.4,
        h_mm=10.0,
    )
    assert cell.truncated is True
    assert cell.image.size == (600, 236)
    min_cap = math.ceil(MIN_CAP_HEIGHT_MM / 25.4 * 600)
    em = min_font_px(600)
    assert cap_height_px(load_cell_font(em)) >= min_cap
    assert cap_height_px(load_cell_font(em - 1)) < min_cap  # em really is the minimum
    inverted = Image.eval(cell.image.convert("L"), lambda v: 255 - v)
    rows = [inverted.crop((0, y, 600, y + 1)).getbbox() is not None for y in range(236)]
    runs: list[tuple[int, int]] = []
    start = None
    for y, has in enumerate([*rows, False]):
        if has and start is None:
            start = y
        if not has and start is not None:
            runs.append((start, y))
            start = None
    title_height = runs[-1][1] - runs[-1][0]
    assert min_cap <= title_height <= min_cap + 2
    assert _ink_bbox(cell.image)[2] <= 600  # nothing outside the box


def test_short_text_is_not_truncated() -> None:
    assert _render(ContentType.TEXT_ONE_LINE, _data(primary_id="SHORT")).truncated is False


def test_missing_fields_raise_mismatch() -> None:
    with pytest.raises(ContentTypeDataMismatchError) as exc:
        _render(ContentType.QR_TWO_LINES, _data(qr_payload="x", primary_id="A"))
    assert exc.value.missing_fields == ("title",)


def test_required_fields_exported_and_shared_with_tape() -> None:
    assert REQUIRED_FIELDS[ContentType.QR_ONLY] == ("qr_payload",)
    assert set(REQUIRED_FIELDS) == set(ContentType)


def test_uses_bundled_font() -> None:
    font = load_cell_font(40)
    assert isinstance(font, ImageFont.FreeTypeFont)
    assert font.path == str(resolve_font_path())
    assert load_cell_font(40) is font  # cached per size


@pytest.mark.parametrize(
    "ct",
    [
        ContentType.QR_ONLY,
        ContentType.QR_ONE_LINE,
        ContentType.QR_TWO_LINES,
        ContentType.QR_THREE_LINES,
        ContentType.TEXT_ONE_LINE,
        ContentType.TEXT_TWO_LINES,
        ContentType.QR_WITH_LISTING,
    ],
)
def test_every_content_type_renders_ink(ct: ContentType) -> None:
    data = _data(
        qr_payload="https://example.test/x",
        primary_id="ID-7",
        title="Title",
        secondary=("second",),
        items=tuple(LabelDataItem(item=f"item {i}") for i in range(12)),
    )
    cell = _render(ct, data)
    assert cell.image.size == (1004, 425)
    assert cell.image.convert("L").getextrema()[0] == 0  # some black


def test_listing_overflow_is_flagged_truncated() -> None:
    data = _data(
        qr_payload="x",
        primary_id="H",
        items=tuple(LabelDataItem(item=f"item {i}") for i in range(40)),
    )
    assert _render(ContentType.QR_WITH_LISTING, data).truncated is True


@pytest.mark.parametrize(
    ("ct", "data"),
    [
        (ContentType.TEXT_TWO_LINES, _data(primary_id="ID", title="T" * 10_000)),
        (ContentType.TEXT_TWO_LINES, _data(primary_id="ID", title="a‮bc\x07d" * 5)),
        (ContentType.TEXT_TWO_LINES, _data(primary_id="ID", title="\U0001f600\U0001f680" * 20)),
    ],
    ids=["10000-chars", "bidi-and-bell", "emoji-only"],
)
def test_render_edge_data(ct: ContentType, data: LabelData) -> None:
    cell = _render(ct, data, w_mm=25.4, h_mm=10.0)
    assert cell.image.size == (600, 236)
    assert cell.image.mode == "1"


def test_control_characters_are_not_drawn() -> None:
    plain = _render(ContentType.TEXT_ONE_LINE, _data(primary_id="abcd"))
    dirty = _render(ContentType.TEXT_ONE_LINE, _data(primary_id="ab\x07‮cd"))
    assert plain.image.tobytes() == dirty.image.tobytes()


def test_qr_payload_too_long_for_box_is_mismatch_on_qr_payload() -> None:
    with pytest.raises(ContentTypeDataMismatchError) as exc:
        _render(
            ContentType.QR_ONLY,
            _data(qr_payload="x" * 3000),
            w_mm=10.0,
            h_mm=10.0,
        )
    assert exc.value.missing_fields == ("qr_payload",)
    assert "qr_payload" in str(exc.value)


def test_text_one_line_empty_primary_id_is_mismatch() -> None:
    with pytest.raises(ContentTypeDataMismatchError):
        _render(ContentType.TEXT_ONE_LINE, _data(primary_id=""))


def test_default_renderer_is_the_raster_renderer() -> None:
    assert isinstance(DEFAULT_CELL_RENDERER, RasterCellRenderer)
