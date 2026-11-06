from __future__ import annotations

import re
from pathlib import Path

import pytest
from app.page_render import pdf as pdf_module
from app.page_render.pdf import (
    FontNotFoundError,
    PageImage,
    PageText,
    VectorPen,
    resolve_font_path,
    write_pdf,
)
from app.page_render.transform import (
    IDENTITY,
    PT_PER_MM,
    Deviation,
    apply_deviation,
    correction_pdf_matrix,
    page_height_pt,
)
from PIL import Image
from reportlab.pdfgen.canvas import Canvas

from tests.helpers import pdf_inspect as inspect

K = PT_PER_MM


def _bilevel(w: int = 64, h: int = 32) -> Image.Image:
    im = Image.new("1", (w, h), 1)
    for x in range(0, w, 3):
        im.putpixel((x, x % h), 0)
    return im


def _draw_all(pen: VectorPen) -> None:
    pen.line(10, 10, 100, 10, width_mm=0.2)
    pen.line(10, 20, 100, 20, width_mm=0.3, dash=(2.0, 1.0))
    pen.rect(10, 30, 40, 20, width_mm=0.25)
    pen.text(10, 60, "label", size_pt=8)
    pen.text(100, 60, "right", size_pt=8, anchor="end")
    pen.text(50, 70, "mid", size_pt=8, anchor="middle")


def _render(**kw: object) -> bytes:
    kw.setdefault("compress", False)
    return write_pdf("A4", **kw)  # type: ignore[arg-type]


# --- geometry of the page and of what is placed on it -----------------------------------------


def test_media_box_exact() -> None:
    assert inspect.media_box(_render()) == pytest.approx((0, 0, 595.2756, 841.8898), abs=1e-3)
    assert inspect.media_box(write_pdf("Letter", compress=False)) == pytest.approx(
        (0, 0, 612, 792), abs=1e-3
    )


def test_image_placed_at_mm_rect() -> None:
    h = page_height_pt("A4")
    pdf = _render(images=[PageImage(985, 6370, 4570, 2120, _bilevel())])
    (matrix,) = inspect.cm_matrices(pdf)
    expected = (
        4570 * K / 100,
        0,
        0,
        2120 * K / 100,
        985 * K / 100,
        h - (6370 + 2120) * K / 100,
    )
    assert matrix == pytest.approx(expected, abs=1e-3)


def test_text_placed_at_baseline() -> None:
    h = page_height_pt("A4")
    pdf = _render(texts=[PageText(2000, 5000, 9.0, "baseline")])
    (pos,) = inspect.text_positions(pdf)
    assert pos == pytest.approx((2000 * K / 100, h - 5000 * K / 100), abs=1e-3)


def test_text_position_follows_the_correction() -> None:
    dev = Deviation(150, -80)
    h = page_height_pt("A4")
    pdf = _render(texts=[PageText(2000, 5000, 9.0, "baseline")], correction=dev)
    (pos,) = inspect.text_positions(pdf)
    m = correction_pdf_matrix(dev, "A4")
    assert pos == pytest.approx((2000 * K / 100 + m[4], h - 5000 * K / 100 + m[5]), abs=1e-3)


# --- the correction transform in the stream ---------------------------------------------------


def test_transform_applied_once_first() -> None:
    dev = Deviation(150, -80)
    pdf = _render(
        images=[PageImage(985, 6370, 4570, 2120, _bilevel())],
        texts=[PageText(2000, 5000, 9.0, "x")],
        vector=_draw_all,
        correction=dev,
    )
    matrices = inspect.cm_matrices(pdf)
    assert matrices[0] == pytest.approx(correction_pdf_matrix(dev, "A4"), abs=1e-4)
    assert sum(1 for m in matrices if m == matrices[0]) == 1  # not applied a second time
    # the correction precedes everything else that is drawn
    ops = inspect.operators(pdf)
    assert ops.index("cm") < min(ops.index(o) for o in ("Do", "l", "re", "Tj"))


def test_identity_correction_emits_no_correction_matrix() -> None:
    pdf = _render(images=[PageImage(985, 6370, 4570, 2120, _bilevel())], correction=IDENTITY)
    assert len(inspect.cm_matrices(pdf)) == 1  # only the image placement


def test_scale_and_rotation_matrix() -> None:
    dev = Deviation(scale_x_ppm=1_010_000, scale_y_ppm=990_000, rotation_udeg=500_000)
    pdf = _render(vector=_draw_all, correction=dev)
    first = inspect.cm_matrices(pdf)[0]
    expected = correction_pdf_matrix(dev, "A4")
    assert first == pytest.approx(expected, abs=1e-4)

    h = page_height_pt("A4")
    w = 210.0 * K
    a, b, c, d, e, f = first
    for corner in ((0.0, 0.0), (w, 0.0), (0.0, h), (w, h)):
        # what the page does to the corner ...
        cx, cy = a * corner[0] + c * corner[1] + e, b * corner[0] + d * corner[1] + f
        # ... followed by the printer's deviation, taken in points
        mm = (cx / K, (h - cy) / K)
        dx, dy = apply_deviation(dev, "A4", mm)
        back = (dx * K, h - dy * K)
        assert back == pytest.approx(corner, abs=1e-3)


# --- gray only, 1 bit -------------------------------------------------------------------------


def test_gray_only() -> None:
    pdf = _render(
        images=[PageImage(985, 6370, 4570, 2120, _bilevel())],
        texts=[PageText(2000, 5000, 9.0, "x")],
        vector=_draw_all,
        correction=Deviation(150, -80),
    )
    ops = inspect.operators(pdf)
    assert not set(ops) & inspect.COLOUR_OPERATORS
    assert {"g", "G"} <= set(ops)  # the gray operators are really in use
    assert b"DeviceRGB" not in pdf
    assert b"DeviceCMYK" not in pdf
    imgs = inspect.images(pdf)
    assert imgs
    for img in imgs:
        assert img["BitsPerComponent"] == 1
        assert img["ColorSpace"] == "/DeviceGray" or img["ImageMask"]
        assert (img["Width"], img["Height"]) == (64, 32)  # never resampled


def test_inspector_flags_an_rgb_control() -> None:
    """The colour check is only worth anything if it can fail: a red page must be flagged."""
    import io

    buf = io.BytesIO()
    c = Canvas(buf, pageCompression=0, invariant=True)
    c.setFillColorRGB(1, 0, 0)
    c.setStrokeColorRGB(0, 0, 1)
    c.rect(10, 10, 50, 50, fill=1, stroke=1)
    c.showPage()
    c.save()
    assert inspect.colour_operators(buf.getvalue()) == {"rg", "RG"}


def test_image_pixels_are_not_resampled_or_inverted() -> None:
    import re
    import zlib

    im = _bilevel(13, 5)  # width not a multiple of 8
    pdf = _render(images=[PageImage(0, 0, 1000, 500, im)])
    match = re.search(
        rb"/Filter \[ /FlateDecode \].*?stream\r?\n(.*?)\r?\nendstream", pdf, re.DOTALL
    )
    assert match is not None
    assert zlib.decompress(match.group(1)) == im.tobytes()


def test_rejects_non_positive_image_size() -> None:
    for w, h in ((0, 100), (100, 0), (-5, 100), (100, -5)):
        with pytest.raises(ValueError, match="positive"):
            PageImage(0, 0, w, h, _bilevel())


def test_same_image_twice_shares_one_xobject_drawn_twice() -> None:
    im = _bilevel()
    pdf = _render(
        images=[PageImage(1000, 1000, 2000, 1000, im), PageImage(5000, 3000, 2000, 1000, im)]
    )
    assert len(inspect.images(pdf)) == 1
    ops = inspect.operations(pdf)
    assert [op for op, _ in ops].count("Do") == 2
    first, second = inspect.cm_matrices(pdf)
    assert first[4] != second[4]  # drawn at two different places
    assert (first[0], first[3]) == (second[0], second[3])


def test_rejects_non_1bit_image() -> None:
    for mode in ("L", "RGB", "P"):
        with pytest.raises(ValueError, match="1"):
            PageImage(0, 0, 100, 100, Image.new(mode, (8, 8)))


# --- text -------------------------------------------------------------------------------------


def test_text_is_literal() -> None:
    raw = "(a)\\ <b>"
    pdf = _render(texts=[PageText(1000, 2000, 10.0, raw)])
    assert inspect.texts(pdf) == [raw]


def test_vector_text_is_literal_and_anchored() -> None:
    def draw(pen: VectorPen) -> None:
        pen.text(100, 50, "<i>x</i> & (y)", size_pt=8)

    pdf = _render(vector=draw)
    assert inspect.texts(pdf) == ["<i>x</i> & (y)"]


def test_non_ascii_text_round_trips() -> None:
    pdf = _render(texts=[PageText(1000, 2000, 10.0, "Größe é")])
    assert inspect.texts(pdf) == ["Größe é"]


def test_text_outside_the_bmp_does_not_break_the_inspector() -> None:
    # reportlab writes <1F600> (odd length) into the CMap; the helper must skip that entry
    pdf = _render(texts=[PageText(1000, 2000, 10.0, "a\U0001f600b")])
    assert inspect.texts(pdf) == ["a\ufffdb"]


def test_vector_pen_has_no_colour_parameter() -> None:
    import inspect as py_inspect

    for name in ("line", "text", "rect"):
        params = py_inspect.signature(getattr(VectorPen, name)).parameters
        assert not any("col" in p or "rgb" in p or "fill" in p for p in params)


def test_pen_converts_mm_to_points_for_widths_and_dashes() -> None:
    def draw(pen: VectorPen) -> None:
        pen.line(10, 10, 100, 10, width_mm=0.3, dash=(2.0, 1.0))
        pen.rect(10, 30, 40, 20, width_mm=0.25)

    ops = inspect.operations(_render(vector=draw))
    widths = [a[0] for op, a in ops if op == "w"]
    assert widths == pytest.approx([0.3 * K, 0.25 * K], abs=1e-4)
    (dash,) = [a for op, a in ops if op == "d"]
    assert dash[:2] == pytest.approx([2.0 * K, 1.0 * K], abs=1e-4)
    # y is measured from the top: the line at y = 10 mm sits 10 mm below the page top
    (move,) = [a for op, a in ops if op == "m"]
    assert move == pytest.approx([10 * K, page_height_pt("A4") - 10 * K], abs=1e-3)
    (rect,) = [a for op, a in ops if op == "re"]
    assert rect == pytest.approx([10 * K, page_height_pt("A4") - 50 * K, 40 * K, 20 * K], abs=1e-3)


def test_a_dash_does_not_leak_into_the_next_line() -> None:
    def draw(pen: VectorPen) -> None:
        pen.line(10, 10, 100, 10, width_mm=0.3, dash=(2.0, 1.0))
        pen.line(10, 20, 100, 20, width_mm=0.3)

    ops = [op for op, _ in inspect.operations(_render(vector=draw))]
    # the dash is set inside q ... Q, so it is restored before the second line
    assert "Q" in ops, "the dash must be scoped by q ... Q"
    assert ops.index("d") < ops.index("Q") < ops.index("l", ops.index("Q"))


def test_text_anchors() -> None:
    xs = {}
    for anchor in ("start", "middle", "end"):

        def draw(pen: VectorPen, anchor: str = anchor) -> None:
            pen.text(100, 50, "anchored", size_pt=10, anchor=anchor)  # type: ignore[arg-type]

        (pos,) = inspect.text_positions(_render(vector=draw))
        xs[anchor] = pos[0]
    assert xs["start"] == pytest.approx(100 * K, abs=1e-3)
    assert xs["end"] < xs["middle"] < xs["start"]
    assert xs["start"] - xs["middle"] == pytest.approx(xs["middle"] - xs["end"], abs=1e-3)


# --- determinism ------------------------------------------------------------------------------


def test_pdf_is_deterministic() -> None:
    """Equal input gives equal bytes, in both compression modes.

    One 1.1 s sleep between the two rounds is kept on purpose: without ``invariant=True``
    reportlab embeds the wall clock to the second, so two renders in the same second would be
    equal anyway and the test could not fail.
    """
    import time

    def render(compress: bool) -> bytes:
        return write_pdf(
            "A4",
            images=[PageImage(985, 6370, 4570, 2120, _bilevel())],
            texts=[PageText(2000, 5000, 9.0, "x")],
            vector=_draw_all,
            correction=Deviation(150, -80),
            compress=compress,
            title="Sheet 1",
        )

    first = {c: render(c) for c in (True, False)}
    time.sleep(1.1)
    for compress in (True, False):
        assert render(compress) == first[compress]


def test_no_wall_clock_in_the_pdf() -> None:
    import datetime

    pdf = _render(title="T")
    year = str(datetime.datetime.now(tz=datetime.UTC).year).encode()
    assert re.search(rb"/CreationDate \(D:" + year, pdf) is None
    assert b"/Title (T)" in pdf


def test_title_is_taken_from_the_caller() -> None:
    assert b"/Title (Calibration page)" in _render(title="Calibration page")


# --- the font ---------------------------------------------------------------------------------


def test_default_font_is_the_bundled_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PRINTHUB_PDF_FONT", raising=False)
    path = resolve_font_path()
    assert path == Path(pdf_module.__file__).parent / "fonts" / "DejaVuSans.ttf"
    assert path.is_file()
    assert (path.parent / "LICENSE-DejaVu.txt").is_file()


def test_font_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    other = tmp_path / "Other.ttf"
    other.write_bytes(resolve_font_path().read_bytes())
    monkeypatch.setenv("PRINTHUB_PDF_FONT", str(other))
    assert resolve_font_path() == other


def test_missing_font_names_both_remedies(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    missing = tmp_path / "nope.ttf"
    monkeypatch.setenv("PRINTHUB_PDF_FONT", str(missing))
    with pytest.raises(FontNotFoundError) as err:
        resolve_font_path()
    assert str(missing) in str(err.value)
    assert "PRINTHUB_PDF_FONT" in str(err.value)


def test_missing_bundled_font_is_a_clear_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("PRINTHUB_PDF_FONT", raising=False)
    monkeypatch.setattr(pdf_module, "BUNDLED_FONT", tmp_path / "gone.ttf")
    with pytest.raises(FontNotFoundError, match=r"gone\.ttf"):
        resolve_font_path()


def test_font_is_embedded_so_the_viewer_needs_none() -> None:
    pdf = _render(texts=[PageText(1000, 2000, 10.0, "x")])
    assert b"/FontFile2" in pdf
    assert re.search(rb"/BaseFont /[A-Z]{6}\+DejaVuSans", pdf)


def test_override_font_is_used_when_rendering(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    other = tmp_path / "Copy.ttf"
    other.write_bytes(resolve_font_path().read_bytes())
    monkeypatch.setenv("PRINTHUB_PDF_FONT", str(other))
    assert inspect.texts(_render(texts=[PageText(1000, 2000, 10.0, "ok")])) == ["ok"]
    monkeypatch.setenv("PRINTHUB_PDF_FONT", str(tmp_path / "missing.ttf"))
    with pytest.raises(FontNotFoundError):
        _render(texts=[PageText(1000, 2000, 10.0, "ok")])


def test_unknown_page_size() -> None:
    with pytest.raises(ValueError, match="A5"):
        write_pdf("A5")  # type: ignore[arg-type]
