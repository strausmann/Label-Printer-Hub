"""The calibration correction as pure geometry.

All maths here is in millimetres with y pointing down (the page as it is seen), unless a
function says "pdf". A printer's measured deviation maps the point the hub asked for onto the
point the printer actually marks; the correction is its inverse, applied once to the whole page.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, NamedTuple

PageName = Literal["A4", "Letter"]

#: Page sizes in millimetres (width, height).
PAGE_SIZE_MM: dict[str, tuple[float, float]] = {
    "A4": (210.0, 297.0),
    "Letter": (215.9, 279.4),
}

#: Points per millimetre.
PT_PER_MM = 72.0 / 25.4

_HMM_PER_MM = 100.0
_PPM = 1_000_000.0
_UDEG = 1_000_000.0


class Affine(NamedTuple):
    """A 2-D affine map in PDF order: ``x' = a*x + c*y + e``, ``y' = b*x + d*y + f``."""

    a: float
    b: float
    c: float
    d: float
    e: float
    f: float

    def apply(self, p: tuple[float, float]) -> tuple[float, float]:
        x, y = p
        return (self.a * x + self.c * y + self.e, self.b * x + self.d * y + self.f)

    def then(self, other: Affine) -> Affine:
        """Return the map that applies ``self`` first and ``other`` second (``other ∘ self``)."""
        return Affine(
            other.a * self.a + other.c * self.b,
            other.b * self.a + other.d * self.b,
            other.a * self.c + other.c * self.d,
            other.b * self.c + other.d * self.d,
            other.a * self.e + other.c * self.f + other.e,
            other.b * self.e + other.d * self.f + other.f,
        )

    def inverse(self) -> Affine:
        det = self.a * self.d - self.b * self.c
        if det == 0.0:
            raise ValueError("affine map is singular")
        ia, ib, ic, id_ = self.d / det, -self.b / det, -self.c / det, self.a / det
        return Affine(
            ia,
            ib,
            ic,
            id_,
            -(ia * self.e + ic * self.f),
            -(ib * self.e + id_ * self.f),
        )


@dataclass(frozen=True)
class Deviation:
    """How a printer misplaces ink, in integer units so it stores and compares exactly.

    Offsets are hundredths of a millimetre, scales are parts per million around 1.0, rotation
    is millionths of a degree. With y pointing down, a positive rotation is clockwise as seen.
    """

    offset_x_hmm: int = 0
    offset_y_hmm: int = 0
    scale_x_ppm: int = 1_000_000
    scale_y_ppm: int = 1_000_000
    rotation_udeg: int = 0


IDENTITY = Deviation()


def page_size_mm(page: str) -> tuple[float, float]:
    try:
        return PAGE_SIZE_MM[page]
    except KeyError:
        raise ValueError(
            f"unknown page size {page!r}; expected one of {sorted(PAGE_SIZE_MM)}"
        ) from None


def page_height_pt(page: str) -> float:
    return page_size_mm(page)[1] * PT_PER_MM


def _deviation_affine(dev: Deviation, page: str) -> Affine:
    """``C + R(θ)·diag(sx, sy)·(p - C) + d`` as an affine map in mm, y down."""
    w, h = page_size_mm(page)
    cx, cy = w / 2.0, h / 2.0
    sx, sy = dev.scale_x_ppm / _PPM, dev.scale_y_ppm / _PPM
    theta = math.radians(dev.rotation_udeg / _UDEG)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    m00, m01 = cos_t * sx, -sin_t * sy
    m10, m11 = sin_t * sx, cos_t * sy
    dx, dy = dev.offset_x_hmm / _HMM_PER_MM, dev.offset_y_hmm / _HMM_PER_MM
    return Affine(
        m00,
        m10,
        m01,
        m11,
        cx - (m00 * cx + m01 * cy) + dx,
        cy - (m10 * cx + m11 * cy) + dy,
    )


def apply_deviation(
    dev: Deviation, page: PageName, p_mm: tuple[float, float]
) -> tuple[float, float]:
    """Where the printer puts ink that was meant for ``p_mm`` (mm, y down)."""
    return _deviation_affine(dev, page).apply(p_mm)


def correction_mm(dev: Deviation, page: PageName) -> Affine:
    """The inverse of the deviation, in mm with y down."""
    return _deviation_affine(dev, page).inverse()


def _mm_to_pdf(page: str) -> Affine:
    """``F(x, y) = (k·x, H_pt - k·y)``: mm with y down to PDF points with y up."""
    return Affine(PT_PER_MM, 0.0, 0.0, -PT_PER_MM, 0.0, page_height_pt(page))


def correction_pdf_matrix(
    dev: Deviation, page: PageName
) -> tuple[float, float, float, float, float, float]:
    """The correction as a PDF ``cm`` matrix: ``F ∘ inverse(deviation) ∘ F⁻¹``."""
    f = _mm_to_pdf(page)
    return tuple(f.inverse().then(correction_mm(dev, page)).then(f))  # type: ignore[return-value]
