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


# ---------------------------------------------------------------------------
# Phase 1k.2 Task 6: print_images adapter + PR #100 bug-fix
# (half_cut / last_page forwarding)
# ---------------------------------------------------------------------------


async def test_ptp_queue_printer_print_image_forwards_half_cut_last_page() -> None:
    """REGRESSION: print_image (single) must forward half_cut + last_page to backend.

    PR #100 fix for last_page→feed landed in PTouchBackend, but the
    _PTPQueuePrinter adapter silently dropped both kwargs.  Phase 1i
    smoke-test 22.5mm pre-roll bug was caused by this silent drop.
    """
    from unittest.mock import AsyncMock, MagicMock

    stub_backend = MagicMock()
    stub_backend.print_image = AsyncMock()
    stub_backend.half_cut_supported = True
    # Make tape-registry lookup succeed for tape_mm=12, MediaType.LAMINATED
    stub_tape_registry = TapeRegistry()

    driver = PTP750WDriver(backend=stub_backend)
    qp = driver.make_queue_printer(stub_tape_registry, default_media_type=MediaType.LAMINATED)

    image = Image.new("1", (600, 70), color=1)
    await qp.print_image(
        image,
        tape_mm=12,
        auto_cut=True,
        high_resolution=False,
        half_cut=True,
        last_page=False,
    )

    stub_backend.print_image.assert_awaited_once()
    call = stub_backend.print_image.call_args
    assert call.kwargs["half_cut"] is True, "half_cut must be forwarded to backend"
    assert call.kwargs["last_page"] is False, "last_page must be forwarded to backend"


async def test_ptp_queue_printer_print_images_forwards_to_backend() -> None:
    """_PTPQueuePrinter.print_images calls backend.print_images with tape_spec + kwargs."""
    from unittest.mock import AsyncMock, MagicMock

    stub_backend = MagicMock()
    stub_backend.print_images = AsyncMock()
    stub_backend.half_cut_supported = True
    stub_tape_registry = TapeRegistry()

    driver = PTP750WDriver(backend=stub_backend)
    qp = driver.make_queue_printer(stub_tape_registry, default_media_type=MediaType.LAMINATED)

    images = [Image.new("1", (600, 70), color=1) for _ in range(3)]
    await qp.print_images(
        images,
        tape_mm=12,
        auto_cut=True,
        high_resolution=False,
        half_cut=True,
    )

    stub_backend.print_images.assert_awaited_once()
    call = stub_backend.print_images.call_args
    assert call.args[0] is images, "images list must be passed as first positional arg"
    assert call.args[1].width_mm == 12, "tape_spec.width_mm must match tape_mm"
    assert call.kwargs["auto_cut"] is True
    assert call.kwargs["half_cut"] is True
