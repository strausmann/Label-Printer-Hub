import pytest
from app.services.status_block import MediaType
from app.services.tape_registry import TapeRegistry, UnknownTapeError


def test_lookup_pt_series_12mm_laminated() -> None:
    spec = TapeRegistry.lookup_pt(width_mm=12, media_type=MediaType.LAMINATED)
    assert spec.width_mm == 12
    assert spec.print_area_pins == 70
    assert spec.print_area_dots == 70
    assert spec.bytes_per_raster == 16
    assert spec.min_length_mm == pytest.approx(4.4)
    assert spec.max_length_mm == 1000
    assert spec.cutter_min_length_mm == pytest.approx(24.5)


def test_lookup_pt_series_24mm() -> None:
    spec = TapeRegistry.lookup_pt(width_mm=24, media_type=MediaType.LAMINATED)
    assert spec.print_area_pins == 128


def test_lookup_pt_unknown_width_raises() -> None:
    with pytest.raises(UnknownTapeError):
        TapeRegistry.lookup_pt(width_mm=15, media_type=MediaType.LAMINATED)


def test_lookup_pt_heat_shrink_2_1() -> None:
    spec = TapeRegistry.lookup_pt(width_mm=12, media_type=MediaType.HEAT_SHRINK_2_1)
    # 12mm HS 2:1 (~11.7mm tape) — 66 print pins per Brother spec
    assert spec.print_area_pins == 66
