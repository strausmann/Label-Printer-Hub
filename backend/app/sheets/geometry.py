"""Pure label sheet geometry: units, validation, canonical hash, cell positions.

All lengths are integer hundredths of a millimetre (``hmm``).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from decimal import Decimal, InvalidOperation
from typing import Literal

from app.sheets.errors import CellOutOfRangeError, InvalidGeometryError

PAGE_SIZES: dict[str, tuple[int, int]] = {"A4": (21000, 29700), "Letter": (21590, 27940)}
MAX_CELLS = 400
_ASYMMETRY_HINT_HMM = 50  # 0.5 mm


def mm_to_hmm(value: float | int | str | Decimal, *, field: str) -> int:  # D16
    """Convert millimetres (at most two decimals) to hundredths of a millimetre."""
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        raise InvalidGeometryError(field, "not a number") from None
    if not d.is_finite():
        raise InvalidGeometryError(field, "not a finite number")
    if d < 0:
        raise InvalidGeometryError(field, "must not be negative")
    scaled = d * 100
    if scaled != scaled.to_integral_value():
        raise InvalidGeometryError(field, "at most two decimals allowed")
    return int(scaled)


def hmm_to_mm(value: int) -> float:
    """Convert hundredths of a millimetre to millimetres (exact to two decimals)."""
    return value / 100


@dataclass(frozen=True)
class Geometry:
    page_size: Literal["A4", "Letter"]
    page_w: int
    page_h: int
    label_w: int
    label_h: int
    cols: int
    rows: int
    pitch_x: int
    pitch_y: int
    margin_top: int
    margin_left: int
    corner_radius: int | None
    shape: Literal["rectangle", "round"]


def normalise(g: Geometry) -> Geometry:
    """Canonical form: page size from the table, no radius on round labels."""
    page_w, page_h = PAGE_SIZES.get(g.page_size, (g.page_w, g.page_h))
    radius = None if g.shape == "round" else g.corner_radius
    return replace(g, page_w=page_w, page_h=page_h, corner_radius=radius)


def cell_count(g: Geometry) -> int:
    return g.cols * g.rows


def remaining_margins(g: Geometry) -> tuple[int, int]:
    """Return the (right, bottom) margin left after the grid."""
    right = g.page_w - (g.margin_left + (g.cols - 1) * g.pitch_x + g.label_w)
    bottom = g.page_h - (g.margin_top + (g.rows - 1) * g.pitch_y + g.label_h)
    return right, bottom


def validate_geometry(g: Geometry) -> list[str]:
    """Raise ``InvalidGeometryError`` on a rule failure; return hint codes otherwise."""
    if g.page_size not in PAGE_SIZES:
        raise InvalidGeometryError("page_size", "must be A4 or Letter")
    if (g.page_w, g.page_h) != PAGE_SIZES[g.page_size]:
        raise InvalidGeometryError("page_w", "does not match the page size")
    if g.shape not in ("rectangle", "round"):
        raise InvalidGeometryError("shape", "must be rectangle or round")
    for name in ("label_w", "label_h", "pitch_x", "pitch_y"):
        if getattr(g, name) <= 0:
            raise InvalidGeometryError(name, "must be greater than zero")
    for name in ("margin_top", "margin_left"):
        if getattr(g, name) < 0:
            raise InvalidGeometryError(name, "must not be negative")
    if g.cols < 1:
        raise InvalidGeometryError("cols", "must be at least 1")
    if g.rows < 1:
        raise InvalidGeometryError("rows", "must be at least 1")
    if cell_count(g) > MAX_CELLS:
        raise InvalidGeometryError("cols", f"cols x rows must not exceed {MAX_CELLS}")
    if g.pitch_x < g.label_w:
        raise InvalidGeometryError("pitch_x", "must not be smaller than label_w")
    if g.pitch_y < g.label_h:
        raise InvalidGeometryError("pitch_y", "must not be smaller than label_h")
    if g.shape == "round" and g.label_w != g.label_h:
        raise InvalidGeometryError("label_h", "round labels need label_w equal to label_h")
    if (
        g.corner_radius is not None
        and g.shape == "rectangle"
        and (g.corner_radius < 0 or g.corner_radius * 2 > min(g.label_w, g.label_h))
    ):
        raise InvalidGeometryError("corner_radius", "must fit inside the label")
    right, bottom = remaining_margins(g)
    if right < 0:
        raise InvalidGeometryError("cols", "grid is wider than the page")
    if bottom < 0:
        raise InvalidGeometryError("rows", "grid is taller than the page")
    hints: list[str] = []
    if abs(right - g.margin_left) > _ASYMMETRY_HINT_HMM:
        hints.append("margins_asymmetric_x")
    if abs(bottom - g.margin_top) > _ASYMMETRY_HINT_HMM:
        hints.append("margins_asymmetric_y")
    return hints


def geometry_hash(g: Geometry) -> str:  # D14
    """sha256 over the canonical JSON form of the normalised geometry."""
    payload = json.dumps(asdict(normalise(g)), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cell_origin(g: Geometry, n: int) -> tuple[int, int]:
    """Top-left corner (x, y) of the 1-based cell ``n``, counted row by row."""
    count = cell_count(g)
    if n < 1 or n > count:
        raise CellOutOfRangeError([n], count)
    row, col = divmod(n - 1, g.cols)
    return g.margin_left + col * g.pitch_x, g.margin_top + row * g.pitch_y
