"""Brother printer tape geometry — pixel dimensions per supported tape width.

Each TapeGeometry entry describes the printable area and layout parameters for
a single tape width. The renderer (LayoutEngine) consumes these to position
QR codes and text deterministically, independent of which ContentType is used.

The 12mm values are empirically validated (Phase 1i V4-Winner, scan-verified).
Other tape widths are extrapolated via pixel-ratio from 12mm and require
post-deploy smoke-test validation.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TapeGeometry(BaseModel):
    """Render parameters for one supported tape width (all values in pixels).

    Formulas (enforced by TAPE_GEOMETRY entries):
        qr_max_px = printable_px - 2 * qr_padding_px
        text_start_x = printable_px + qr_padding_px
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    printable_px: int = Field(gt=0)
    """Print-pin count per tape (Brother spec)."""

    qr_max_px: int = Field(gt=0)
    """Square QR-code edge length: printable_px - 2 * qr_padding_px."""

    qr_padding_px: int = Field(ge=0)
    """Padding around the QR-code (also separator gap before text column)."""

    text_start_x: int = Field(ge=0)
    """Absolute X-position where text rendering starts (after QR + gap)."""

    line_spacing_px: int = Field(ge=0)
    """Vertical gap between adjacent text lines."""

    font_xl: int = Field(gt=0)
    """primary_id font size."""

    font_l: int = Field(gt=0)
    """title font size."""

    font_m: int = Field(gt=0)
    """listing item / secondary content font size."""

    font_s: int = Field(gt=0)
    """secondary line font size."""


TAPE_GEOMETRY: dict[int, TapeGeometry] = {
    4: TapeGeometry(
        printable_px=24,
        qr_max_px=20,
        qr_padding_px=2,
        text_start_x=26,
        line_spacing_px=1,
        font_xl=8,
        font_l=7,
        font_m=6,
        font_s=5,
    ),
    6: TapeGeometry(
        printable_px=32,
        qr_max_px=28,
        qr_padding_px=2,
        text_start_x=34,
        line_spacing_px=2,
        font_xl=10,
        font_l=9,
        font_m=7,
        font_s=6,
    ),
    9: TapeGeometry(
        printable_px=50,
        qr_max_px=46,
        qr_padding_px=2,
        text_start_x=52,
        line_spacing_px=3,
        font_xl=14,
        font_l=12,
        font_m=10,
        font_s=8,
    ),
    12: TapeGeometry(
        printable_px=70,
        qr_max_px=66,
        qr_padding_px=2,
        text_start_x=72,
        line_spacing_px=4,
        font_xl=22,
        font_l=18,
        font_m=14,
        font_s=10,
    ),
    18: TapeGeometry(
        printable_px=112,
        qr_max_px=108,
        qr_padding_px=2,
        text_start_x=114,
        line_spacing_px=6,
        font_xl=32,
        font_l=26,
        font_m=20,
        font_s=14,
    ),
    24: TapeGeometry(
        printable_px=128,
        qr_max_px=124,
        qr_padding_px=2,
        text_start_x=130,
        line_spacing_px=8,
        font_xl=36,
        font_l=30,
        font_m=24,
        font_s=18,
    ),
    62: TapeGeometry(
        printable_px=696,
        qr_max_px=688,
        qr_padding_px=4,
        text_start_x=700,
        line_spacing_px=20,
        font_xl=120,
        font_l=96,
        font_m=72,
        font_s=48,
    ),
}
"""Map int(tape_mm) -> TapeGeometry. 12mm scan-verified, others extrapolated."""
