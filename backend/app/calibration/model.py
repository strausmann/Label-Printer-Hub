"""Calibration values as the API sees them, and their conversion to the integer ``Deviation``.

The stored row and ``Deviation`` use integers (hundredths of a millimetre, parts per million,
micro-degrees). The API speaks millimetres, a scale factor and degrees.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, Field

from app.models.printer_calibration import PrinterCalibration
from app.page_render.transform import IDENTITY, Deviation
from app.sheets.errors import CalibrationOutOfRangeError

#: field -> (minimum, maximum, decimals)
BOUNDS: dict[str, tuple[float, float, int]] = {
    "offset_x_mm": (-10.0, 10.0, 2),
    "offset_y_mm": (-10.0, 10.0, 2),
    "scale_x": (0.95, 1.05, 6),
    "scale_y": (0.95, 1.05, 6),
    "rotation_deg": (-2.0, 2.0, 6),
}

#: field -> factor from the API unit to the stored integer
_FACTOR: dict[str, int] = {
    "offset_x_mm": 100,
    "offset_y_mm": 100,
    "scale_x": 1_000_000,
    "scale_y": 1_000_000,
    "rotation_deg": 1_000_000,
}


class CalibrationIn(BaseModel):
    """A printer's measured deviation; the hub applies the inverse when it renders (D17).

    Offsets are millimetres (±10, at most 2 decimals), scales are factors (0.95 to 1.05, at
    most 6 decimals), rotation is degrees (±2, at most 6 decimals, positive is clockwise).
    The bounds are checked by the service and reported as ``calibration_out_of_range``; the
    fit endpoint returns values of this shape even when they are outside the bounds.
    """

    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    rotation_deg: float = 0.0


class MeasuredOn(BaseModel):
    type_key: str
    version: int


class CalibrationPut(CalibrationIn):
    measured_on: MeasuredOn | None = Field(
        default=None, description="The sheet type version the page was measured on (optional)."
    )


class CalibrationRead(BaseModel):
    """One enabled tray; the values are ``None`` while the tray has no calibration (identity)."""

    tray: str
    method: str | None = None
    offset_x_mm: float | None = None
    offset_y_mm: float | None = None
    scale_x: float | None = None
    scale_y: float | None = None
    rotation_deg: float | None = None
    measured_on: MeasuredOn | None = None
    updated_at: datetime | None = None
    updated_by: str | None = None


def _to_int(field: str, value: float) -> int:
    lo, hi, _ = BOUNDS[field]
    try:
        d = Decimal(str(value))
        if not d.is_finite():
            raise CalibrationOutOfRangeError(field, minimum=lo, maximum=hi)
    except InvalidOperation:
        raise CalibrationOutOfRangeError(field, minimum=lo, maximum=hi) from None
    if not Decimal(str(lo)) <= d <= Decimal(str(hi)):
        raise CalibrationOutOfRangeError(field, minimum=lo, maximum=hi)
    scaled = d * _FACTOR[field]
    if scaled != scaled.to_integral_value():
        raise CalibrationOutOfRangeError(field, minimum=lo, maximum=hi, reason="too_many_decimals")
    return int(scaled)


def to_deviation(source: PrinterCalibration | CalibrationIn | None) -> Deviation:
    """The deviation of a stored row or of submitted values; ``None`` is the identity."""
    if source is None:
        return IDENTITY
    if isinstance(source, PrinterCalibration):
        return Deviation(
            source.offset_x_hmm,
            source.offset_y_hmm,
            source.scale_x_ppm,
            source.scale_y_ppm,
            source.rotation_udeg,
        )
    return Deviation(
        _to_int("offset_x_mm", source.offset_x_mm),  # D16
        _to_int("offset_y_mm", source.offset_y_mm),  # D16
        _to_int("scale_x", source.scale_x),
        _to_int("scale_y", source.scale_y),
        _to_int("rotation_deg", source.rotation_deg),
    )


def deviation_to_values(dev: Deviation) -> CalibrationIn:
    """API units from a deviation; the integers give exactly 2 and 6 decimals."""
    return CalibrationIn(
        offset_x_mm=dev.offset_x_hmm / 100,
        offset_y_mm=dev.offset_y_hmm / 100,
        scale_x=dev.scale_x_ppm / 1_000_000,
        scale_y=dev.scale_y_ppm / 1_000_000,
        rotation_deg=dev.rotation_udeg / 1_000_000,
    )


def out_of_range_fields(dev: Deviation) -> list[str]:
    """Names of the values of ``dev`` that lie outside their bounds."""
    values = deviation_to_values(dev).model_dump()
    return [
        name
        for name, (lo, hi, _) in BOUNDS.items()
        if not Decimal(str(lo)) <= Decimal(str(values[name])) <= Decimal(str(hi))
    ]
