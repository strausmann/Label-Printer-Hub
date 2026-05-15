from __future__ import annotations

import pytest
from app.models.tape import TapeSpec
from app.printer_backends.base import PrinterBackend
from app.printer_backends.exceptions import (
    PrinterCoverOpenError,
    PrinterOfflineError,
    TapeEmptyError,
    TapeMismatchError,
)
from app.printer_backends.mock_backend import MockPrinterBackend
from app.services.status_block import MediaType, StatusBlock
from PIL import Image


@pytest.fixture
def tape_24() -> TapeSpec:
    return TapeSpec(
        width_mm=24,
        media_type=MediaType.LAMINATED,
        print_area_pins=128,
        print_area_dots=128,
        bytes_per_raster=16,
        min_length_mm=4.4,
        max_length_mm=1000,
        cutter_min_length_mm=24.5,
    )


@pytest.fixture
def img_128() -> Image.Image:
    return Image.new("1", (200, 128))


def test_mock_satisfies_protocol() -> None:
    assert isinstance(MockPrinterBackend(), PrinterBackend)


async def test_query_status_default() -> None:
    backend = MockPrinterBackend()
    status = await backend.query_status()
    assert status.tape_empty is False
    assert status.cover_open is False
    assert status.loaded_tape_mm == 24
    assert isinstance(status, StatusBlock)


async def test_print_records_image(img_128: Image.Image, tape_24: TapeSpec) -> None:
    backend = MockPrinterBackend()
    await backend.print_image(img_128, tape_24)
    assert len(backend.printed_images) == 1
    assert backend.printed_images[0].size == img_128.size


async def test_offline_raises(tape_24: TapeSpec) -> None:
    backend = MockPrinterBackend(offline=True)
    with pytest.raises(PrinterOfflineError):
        await backend.query_status()


async def test_tape_empty_raises(img_128: Image.Image, tape_24: TapeSpec) -> None:
    backend = MockPrinterBackend(tape_empty=True)
    with pytest.raises(TapeEmptyError):
        await backend.print_image(img_128, tape_24)


async def test_cover_open_raises(img_128: Image.Image, tape_24: TapeSpec) -> None:
    backend = MockPrinterBackend(cover_open=True)
    with pytest.raises(PrinterCoverOpenError):
        await backend.print_image(img_128, tape_24)


async def test_tape_mismatch_raises(img_128: Image.Image, tape_24: TapeSpec) -> None:
    backend = MockPrinterBackend(loaded_tape_mm=12)
    with pytest.raises(TapeMismatchError) as exc:
        await backend.print_image(img_128, tape_24)
    assert exc.value.expected_mm == 24
    assert exc.value.loaded_mm == 12
