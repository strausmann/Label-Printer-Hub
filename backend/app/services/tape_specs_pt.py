"""Tape specifications for Brother PT-Series printers (180 DPI, 128-pin head).

Source: Brother Raster Command Reference (PT-E550W / PT-P710BT / PT-P750W) v1.02.
The numbers here come straight from the manufacturer's printable-area tables.
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


# TZe laminated tapes. The non-laminated TZe-N* variants share the same
# print-area geometry — only the material differs — so we reuse this list
# for MediaType.NON_LAMINATED in the registry.
PT_TZE_TAPES: tuple[TapeSpec, ...] = (
    TapeSpec(
        width_mm=4,
        media_type=MediaType.LAMINATED,
        print_area_pins=24,
        print_area_dots=24,
        bytes_per_raster=16,
        min_length_mm=4.4,
        max_length_mm=1000,
        cutter_min_length_mm=24.5,
    ),
    TapeSpec(
        width_mm=6,
        media_type=MediaType.LAMINATED,
        print_area_pins=32,
        print_area_dots=32,
        bytes_per_raster=16,
        min_length_mm=4.4,
        max_length_mm=1000,
        cutter_min_length_mm=24.5,
    ),
    TapeSpec(
        width_mm=9,
        media_type=MediaType.LAMINATED,
        print_area_pins=50,
        print_area_dots=50,
        bytes_per_raster=16,
        min_length_mm=4.4,
        max_length_mm=1000,
        cutter_min_length_mm=24.5,
    ),
    TapeSpec(
        width_mm=12,
        media_type=MediaType.LAMINATED,
        print_area_pins=70,
        print_area_dots=70,
        bytes_per_raster=16,
        min_length_mm=4.4,
        max_length_mm=1000,
        cutter_min_length_mm=24.5,
    ),
    TapeSpec(
        width_mm=18,
        media_type=MediaType.LAMINATED,
        print_area_pins=112,
        print_area_dots=112,
        bytes_per_raster=16,
        min_length_mm=4.4,
        max_length_mm=1000,
        cutter_min_length_mm=24.5,
    ),
    TapeSpec(
        width_mm=24,
        media_type=MediaType.LAMINATED,
        print_area_pins=128,
        print_area_dots=128,
        bytes_per_raster=16,
        min_length_mm=4.4,
        max_length_mm=1000,
        cutter_min_length_mm=24.5,
    ),
)

# Heat-shrink tubing 2:1 (status-block media-type byte = 0x11).
# Widths are nominal — actual tape is slightly narrower (e.g. 12mm HS = ~11.7mm).
# Pin counts are the Brother-published values.
PT_HS_2_1_TAPES: tuple[TapeSpec, ...] = (
    TapeSpec(
        width_mm=6,
        media_type=MediaType.HEAT_SHRINK_2_1,
        print_area_pins=28,
        print_area_dots=28,
        bytes_per_raster=16,
        min_length_mm=4.4,
        max_length_mm=500,
        cutter_min_length_mm=24.5,
    ),
    TapeSpec(
        width_mm=9,
        media_type=MediaType.HEAT_SHRINK_2_1,
        print_area_pins=48,
        print_area_dots=48,
        bytes_per_raster=16,
        min_length_mm=4.4,
        max_length_mm=500,
        cutter_min_length_mm=24.5,
    ),
    TapeSpec(
        width_mm=12,
        media_type=MediaType.HEAT_SHRINK_2_1,
        print_area_pins=66,
        print_area_dots=66,
        bytes_per_raster=16,
        min_length_mm=4.4,
        max_length_mm=500,
        cutter_min_length_mm=24.5,
    ),
    TapeSpec(
        width_mm=18,
        media_type=MediaType.HEAT_SHRINK_2_1,
        print_area_pins=106,
        print_area_dots=106,
        bytes_per_raster=16,
        min_length_mm=4.4,
        max_length_mm=500,
        cutter_min_length_mm=24.5,
    ),
    TapeSpec(
        width_mm=24,
        media_type=MediaType.HEAT_SHRINK_2_1,
        print_area_pins=128,
        print_area_dots=128,
        bytes_per_raster=16,
        min_length_mm=4.4,
        max_length_mm=500,
        cutter_min_length_mm=24.5,
    ),
)
