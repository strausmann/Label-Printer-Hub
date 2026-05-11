"""Series-neutral tape specification record.

Used by all printer model modules and the tape registry dispatch layer.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.status_block import MediaType


@dataclass(frozen=True, slots=True)
class TapeSpec:
    width_mm: int
    media_type: MediaType
    print_area_pins: int
    print_area_dots: int
    bytes_per_raster: int
    min_length_mm: float
    max_length_mm: int
    cutter_min_length_mm: float
