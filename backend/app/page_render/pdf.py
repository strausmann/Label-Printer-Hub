"""One-page, DeviceGray-only PDFs for page printers.

Everything printed is gray: true 1-bit images, gray strokes, gray text. There is deliberately no
colour parameter anywhere in this module, so a colour operator cannot reach the page. Output is
deterministic (spec 11.4): identical input gives identical bytes, and no wall-clock value is
written into the file.
"""

from __future__ import annotations

import hashlib
import io
import os
import zlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from PIL import Image
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfdoc import PDFImageXObject
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from app.page_render.transform import (
    IDENTITY,
    PT_PER_MM,
    Deviation,
    PageName,
    correction_pdf_matrix,
    page_size_mm,
)

#: The font shipped inside the package (DejaVu Sans, Bitstream Vera licence, see fonts/).
BUNDLED_FONT = Path(__file__).parent / "fonts" / "DejaVuSans.ttf"
FONT_ENV = "PRINTHUB_PDF_FONT"

_Anchor = Literal["start", "middle", "end"]


class FontNotFoundError(RuntimeError):
    """The PDF font file does not exist."""


def resolve_font_path() -> Path:
    """The font file used for all PDF text.

    ``PRINTHUB_PDF_FONT`` (a path) overrides the bundled DejaVu Sans. A missing file is an
    error that names the path and the remedy; there is no search path and no silent fallback,
    so the output never depends on which fonts the machine happens to have.
    """
    override = os.environ.get(FONT_ENV)
    if override:
        path = Path(override)
        if not path.is_file():
            raise FontNotFoundError(
                f"PDF font not found at {path}; fix or unset {FONT_ENV} "
                f"(unset uses the bundled {BUNDLED_FONT.name})"
            )
        return path
    if not BUNDLED_FONT.is_file():
        raise FontNotFoundError(
            f"bundled PDF font not found at {BUNDLED_FONT}; reinstall the package "
            f"or set {FONT_ENV} to a TrueType file"
        )
    return BUNDLED_FONT


def _register_font(path: Path) -> str:
    """Register the font once per distinct file and return its reportlab name."""
    # The font is registered once per path per process; replacing the file at the same path
    # while the process runs keeps the old registration.
    digest = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:12]
    name = f"PrintHubPdf-{digest}"
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(name, str(path)))
    return name


def text_width_mm(s: str, size_pt: float) -> float:
    """Width of ``s`` in the embedded font at ``size_pt``: what ``VectorPen.text`` really draws."""
    width: float = pdfmetrics.stringWidth(s, _register_font(resolve_font_path()), size_pt)
    return width / PT_PER_MM


@dataclass
class PageImage:
    """A bilevel image placed on the page; the rectangle is in hundredths of a millimetre."""

    x_hmm: int
    y_hmm: int
    w_hmm: int
    h_hmm: int
    image: Image.Image

    def __post_init__(self) -> None:
        if self.image.mode != "1":
            raise ValueError(f"page images must be 1-bit (mode '1'), got mode {self.image.mode!r}")
        if self.w_hmm <= 0 or self.h_hmm <= 0:
            raise ValueError("page image width and height must be positive")


@dataclass
class PageText:
    """A single line of literal text; ``baseline_y_hmm`` is measured from the top of the page.

    ``rotation`` 90 turns the line a quarter turn clockwise as seen on the page, about the text
    origin ``(x_hmm, baseline_y_hmm)``: it then reads from top to bottom.
    """

    x_hmm: int
    baseline_y_hmm: int
    size_pt: float
    text: str
    rotation: Literal[0, 90] = 0


class VectorPen:
    """Draw in millimetres with y pointing down, in gray only (no colour parameters exist)."""

    def __init__(self, canvas: Canvas, page_height_pt: float, font_name: Callable[[], str]) -> None:
        self._c = canvas
        self._h = page_height_pt
        self._font_name = font_name

    def _y(self, y_mm: float) -> float:
        return self._h - y_mm * PT_PER_MM

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        width_mm: float,
        dash: tuple[float, ...] | None = None,
    ) -> None:
        c = self._c
        c.saveState()
        c.setStrokeGray(0)
        c.setLineWidth(width_mm * PT_PER_MM)
        if dash:
            c.setDash([d * PT_PER_MM for d in dash])
        c.line(x1 * PT_PER_MM, self._y(y1), x2 * PT_PER_MM, self._y(y2))
        c.restoreState()

    def rect(self, x: float, y: float, w: float, h: float, *, width_mm: float) -> None:
        c = self._c
        c.saveState()
        c.setStrokeGray(0)
        c.setLineWidth(width_mm * PT_PER_MM)
        c.rect(x * PT_PER_MM, self._y(y + h), w * PT_PER_MM, h * PT_PER_MM, stroke=1, fill=0)
        c.restoreState()

    def text(
        self, x: float, y: float, s: str, *, size_pt: float, anchor: _Anchor = "start"
    ) -> None:
        c = self._c
        c.saveState()
        c.setFillGray(0)
        c.setFont(self._font_name(), size_pt)
        px, py = x * PT_PER_MM, self._y(y)
        # drawString and friends show the string as-is: no markup is interpreted.
        if anchor == "middle":
            c.drawCentredString(px, py, s)
        elif anchor == "end":
            c.drawRightString(px, py, s)
        else:
            c.drawString(px, py, s)
        c.restoreState()


def _draw_bilevel_image(
    c: Canvas, im: Image.Image, x_pt: float, y_pt: float, w_pt: float, h_pt: float
) -> None:
    """Place ``im`` (mode "1") as a true 1-bit ``/DeviceGray`` image, pixel for pixel.

    reportlab has no public way to do this: ``drawImage`` always expands to 8-bit RGB. This
    function therefore builds the image XObject itself and mirrors the body of
    ``Canvas.drawImage``, which means it touches reportlab internals (``_doc``, ``_code``,
    ``_formsinuse``, ``_setXObjects``, ``_currentPageHasImages``). That is why ``pyproject.toml``
    pins reportlab to one minor release, and why ``tests/unit/page_render/test_pdf.py`` asserts
    ``/BitsPerComponent 1`` and the exact pixel bytes: an upgrade that breaks this fails loudly.

    Fallback, if the internals move: ``c.drawImage(ImageReader(im.convert("L")), x, y, w, h)``.
    That is still DeviceGray and still not resampled, but it is 8 bits per pixel (it compresses
    to almost nothing for a bilevel image), so the 1-bit assertions would have to be relaxed.
    """
    raw = im.tobytes()  # packed rows, 1 = white, rows padded to whole bytes
    name = hashlib.sha256(raw + repr(im.size).encode()).hexdigest()[:32]
    doc: Any = c._doc
    reg = doc.getXObjectName(name)
    if not doc.idToObject.get(reg):
        xobj = PDFImageXObject(name, None)  # source=None: skip reportlab's RGB conversion
        xobj.name = name
        xobj.width, xobj.height = im.size
        xobj.colorSpace, xobj.bitsPerComponent, xobj.mask = "DeviceGray", 1, None
        xobj.streamContent = zlib.compress(raw, 9)
        xobj._filters = ("FlateDecode",)
        c._setXObjects(xobj)
        doc.Reference(xobj, reg)
        doc.addForm(name, xobj)
    c.saveState()
    c.transform(w_pt, 0, 0, h_pt, x_pt, y_pt)  # one cm: the placement rectangle
    c._code.append(f"/{reg} Do")
    c.restoreState()
    c._formsinuse.append(name)
    c._currentPageHasImages = 1


def write_pdf(
    page: PageName,
    *,
    images: Sequence[PageImage] = (),
    texts: Sequence[PageText] = (),
    vector: Callable[[VectorPen], None] | None = None,
    correction: Deviation = IDENTITY,
    compress: bool = True,
    title: str = "",
) -> bytes:
    """Render one page and return the PDF bytes.

    The canvas is always ``invariant=True``, so equal input gives equal bytes. ``correction`` is
    the printer's measured deviation; its inverse is applied as a single ``cm`` before any
    content, so nothing else on the page needs to know about it.
    """
    w_mm, h_mm = page_size_mm(page)
    w_pt, h_pt = w_mm * PT_PER_MM, h_mm * PT_PER_MM
    buf = io.BytesIO()
    c = Canvas(
        buf,
        pagesize=(w_pt, h_pt),
        pageCompression=1 if compress else 0,
        invariant=True,
    )
    c.setTitle(title)

    font: list[str] = []

    def font_name() -> str:
        if not font:
            font.append(_register_font(resolve_font_path()))
        return font[0]

    if correction != IDENTITY:
        c.transform(*correction_pdf_matrix(correction, page))

    for item in images:
        _draw_bilevel_image(
            c,
            item.image,
            item.x_hmm * PT_PER_MM / 100,
            h_pt - (item.y_hmm + item.h_hmm) * PT_PER_MM / 100,
            item.w_hmm * PT_PER_MM / 100,
            item.h_hmm * PT_PER_MM / 100,
        )
    if vector is not None:
        vector(VectorPen(c, h_pt, font_name))
    for t in texts:
        c.saveState()
        c.setFillGray(0)
        c.setFont(font_name(), t.size_pt)
        x_pt = t.x_hmm * PT_PER_MM / 100
        y_pt = h_pt - t.baseline_y_hmm * PT_PER_MM / 100
        if t.rotation == 90:
            # One matrix (translate and rotate by -90 degrees in PDF space): a separate
            # translate would look like an image placement to anything counting ``cm``.
            c.transform(0, -1, 1, 0, x_pt, y_pt)
            c.drawString(0, 0, t.text)
        else:
            c.drawString(x_pt, y_pt, t.text)
        c.restoreState()
    c.showPage()
    c.save()
    return buf.getvalue()
