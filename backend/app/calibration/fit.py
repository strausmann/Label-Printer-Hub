# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Fit the deviation of a printer from readings taken on a printed test page.

A reading says how far the ink landed from the nominal crossing between four labels
(``across_mm`` to the right, ``down_mm`` downwards). The fit solves the affine map that sends
each nominal crossing to the printed one in the least-squares sense, then reads the offset,
the two scales and the rotation from it. Plain Python: two 3x3 systems do not need numpy.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from app.calibration.model import out_of_range_fields
from app.page_render.transform import Deviation, page_size_mm
from app.sheets.errors import InvalidFieldError, ReadingsInsufficientError
from app.sheets.geometry import Geometry

#: A reading further than this from the fitted map is reported as probably misread.
RESIDUAL_FLAG_MM = 0.3
#: Below this the readings do not span two directions (all on one line).
_DEGENERATE = 1e-9


@dataclass(frozen=True)
class Reading:
    """Gap indices are 1-based: S1..S(cols-1) across, Z1..Z(rows-1) down."""

    col_gap: int
    row_gap: int
    across_mm: float
    down_mm: float


@dataclass(frozen=True)
class FitResult:
    dev: Deviation
    residuals_mm: list[float]
    flagged: list[int]
    out_of_range: list[str]


def crossing_point(g: Geometry, col_gap: int, row_gap: int) -> tuple[float, float]:
    """The nominal crossing between four labels, in mm from the page's top left (y down)."""
    if not 1 <= col_gap <= g.cols - 1:
        raise InvalidFieldError("col_gap", "outside the sheet")
    if not 1 <= row_gap <= g.rows - 1:
        raise InvalidFieldError("row_gap", "outside the sheet")
    x = (g.margin_left + (col_gap - 1) * g.pitch_x + g.label_w + (g.pitch_x - g.label_w) / 2) / 100
    y = (g.margin_top + (row_gap - 1) * g.pitch_y + g.label_h + (g.pitch_y - g.label_h) / 2) / 100
    return x, y


def _solve_axis(
    u: list[float], v: list[float], p: list[float], su: float, sv: float, suv: float
) -> tuple[float, float, float]:
    """Least-squares ``p = m_u*u + m_v*v + d`` from centred sums; returns (m_u, m_v, d)."""
    n = len(u)
    mu, mv, mp = sum(u) / n, sum(v) / n, sum(p) / n
    spu = sum((pi - mp) * (ui - mu) for pi, ui in zip(p, u, strict=True))
    spv = sum((pi - mp) * (vi - mv) for pi, vi in zip(p, v, strict=True))
    det = su * sv - suv * suv
    m_u = (spu * sv - spv * suv) / det
    m_v = (spv * su - spu * suv) / det
    return m_u, m_v, mp - m_u * mu - m_v * mv


def fit(g: Geometry, page: str, readings: Sequence[Reading]) -> FitResult:
    """Fit the printer's deviation around the page centre (D17)."""
    if len(readings) < 3:
        raise ReadingsInsufficientError("fewer_than_three_readings")
    w, h = page_size_mm(page)
    cx, cy = w / 2.0, h / 2.0
    u: list[float] = []
    v: list[float] = []
    px: list[float] = []
    py: list[float] = []
    for index, r in enumerate(readings):
        try:
            qx, qy = crossing_point(g, r.col_gap, r.row_gap)
        except InvalidFieldError as exc:
            # Name the reading (0-based) so a client can point at the bad one.
            err = InvalidFieldError(
                f"readings[{index}].{(exc.detail or {})['field']}",
                str((exc.detail or {})["reason"]),
            )
            err.detail = {**(exc.detail or {}), "reading": index}
            raise err from None
        u.append(qx - cx)
        v.append(qy - cy)
        px.append(qx + r.across_mm - cx)
        py.append(qy + r.down_mm - cy)
    n = len(u)
    mu, mv = sum(u) / n, sum(v) / n
    su = sum((x - mu) ** 2 for x in u)
    sv = sum((y - mv) ** 2 for y in v)
    suv = sum((x - mu) * (y - mv) for x, y in zip(u, v, strict=True))
    if su * sv - suv * suv < _DEGENERATE:
        raise ReadingsInsufficientError("readings_on_one_line")
    a, b, dx = _solve_axis(u, v, px, su, sv, suv)
    c, e, dy = _solve_axis(u, v, py, su, sv, suv)
    sx, sy = math.hypot(a, c), math.hypot(b, e)
    theta = math.atan2(c, a)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    residuals = []
    for ui, vi, pxi, pyi in zip(u, v, px, py, strict=True):
        mx = cos_t * sx * ui - sin_t * sy * vi + dx
        my = sin_t * sx * ui + cos_t * sy * vi + dy
        residuals.append(math.hypot(pxi - mx, pyi - my))
    try:
        dev = Deviation(
            round(dx * 100),
            round(dy * 100),
            round(sx * 1_000_000),
            round(sy * 1_000_000),
            round(math.degrees(theta) * 1_000_000),
        )
    except ValueError:  # a collapsed map: the readings describe no printable page
        raise ReadingsInsufficientError("degenerate_fit") from None
    return FitResult(
        dev=dev,
        residuals_mm=residuals,
        flagged=[i for i, r in enumerate(residuals) if r > RESIDUAL_FLAG_MM],
        out_of_range=out_of_range_fields(dev),
    )
