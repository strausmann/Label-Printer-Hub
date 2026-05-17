from __future__ import annotations

from uuid import UUID

import pytest
from app.models.tape import TapeSpec
from app.printer_backends.mock_backend import MockPrinterBackend
from app.printer_models.pt import PTP750WDriver
from app.services.print_queue import _PrinterLike
from app.services.status_block import MediaType
from app.services.tape_registry import TapeRegistry
from PIL import Image


@pytest.fixture
def backend() -> MockPrinterBackend:
    return MockPrinterBackend(host="192.0.2.10")


@pytest.fixture
def tape_registry() -> TapeRegistry:
    return TapeRegistry()


def test_constants() -> None:
    assert PTP750WDriver.model_id == "PT-P750W"
    assert PTP750WDriver.dpi == (180, 180)
    assert PTP750WDriver.print_head_pins == 128
    assert "PT-P750W" in PTP750WDriver.pjl_signatures
    assert PTP750WDriver.snmp_model_oid_value_substr == "PT-P750W"


async def test_query_status_delegates_to_backend(backend: MockPrinterBackend) -> None:
    driver = PTP750WDriver(backend=backend)
    status = await driver.query_status(host="")
    assert status.loaded_tape_mm == 24


async def test_query_status_rejects_host_mismatch(backend: MockPrinterBackend) -> None:
    driver = PTP750WDriver(backend=backend)
    with pytest.raises(ValueError, match=r"bound to backend\.host"):
        await driver.query_status(host="999.999.999.999")


async def test_query_status_accepts_matching_host(backend: MockPrinterBackend) -> None:
    driver = PTP750WDriver(backend=backend)
    status = await driver.query_status(host=backend.host)
    assert status.loaded_tape_mm == 24


def test_width_to_pixels(backend: MockPrinterBackend) -> None:
    driver = PTP750WDriver(backend=backend)
    spec = TapeSpec(
        width_mm=24,
        media_type=MediaType.LAMINATED,
        print_area_pins=128,
        print_area_dots=128,
        bytes_per_raster=16,
        min_length_mm=4.4,
        max_length_mm=1000,
        cutter_min_length_mm=24.5,
    )
    assert driver.width_to_pixels(spec) == 128


def test_build_print_job_raises_not_implemented(backend: MockPrinterBackend) -> None:
    driver = PTP750WDriver(backend=backend)
    image = Image.new("1", (200, 128))
    spec = TapeSpec(
        width_mm=24,
        media_type=MediaType.LAMINATED,
        print_area_pins=128,
        print_area_dots=128,
        bytes_per_raster=16,
        min_length_mm=4.4,
        max_length_mm=1000,
        cutter_min_length_mm=24.5,
    )
    with pytest.raises(NotImplementedError):
        driver.build_print_job(image, spec)


def test_make_queue_printer_returns_printer_like(
    backend: MockPrinterBackend,
    tape_registry: TapeRegistry,
) -> None:
    driver = PTP750WDriver(backend=backend)
    qp = driver.make_queue_printer(tape_registry)
    assert isinstance(qp, _PrinterLike)
    assert isinstance(qp.id, UUID)


async def test_queue_printer_print_calls_backend(
    backend: MockPrinterBackend,
    tape_registry: TapeRegistry,
) -> None:
    driver = PTP750WDriver(backend=backend)
    qp = driver.make_queue_printer(tape_registry)
    image = Image.new("1", (200, 128))
    await qp.print_image(image, tape_mm=24)
    assert len(backend.printed_images) == 1


async def test_queue_printer_default_media_type_override(
    backend: MockPrinterBackend,
    tape_registry: TapeRegistry,
) -> None:
    """Default override path is plumbed (test only verifies no crash; mock
    only validates width, not media-type)."""
    driver = PTP750WDriver(backend=backend)
    qp = driver.make_queue_printer(tape_registry, default_media_type=MediaType.LAMINATED)
    image = Image.new("1", (200, 128))
    await qp.print_image(image, tape_mm=24)
