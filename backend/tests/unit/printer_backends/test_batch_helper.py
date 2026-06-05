"""Unit tests for default_print_images_loop helper."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from app.models.tape import TapeSpec
from app.printer_backends.batch_helper import default_print_images_loop
from app.services.status_block import MediaType
from PIL import Image


@pytest.fixture
def tape_spec_12() -> TapeSpec:
    return TapeSpec(
        width_mm=12,
        media_type=MediaType.LAMINATED,
        print_area_pins=70,
        print_area_dots=70,
        bytes_per_raster=9,
        min_length_mm=4.4,
        max_length_mm=1000,
        cutter_min_length_mm=24.5,
    )


@pytest.fixture
def three_images() -> list[Image.Image]:
    return [Image.new("1", (600, 70), color=1) for _ in range(3)]


@pytest.mark.anyio
async def test_loops_print_image_for_each(three_images, tape_spec_12):
    """default_print_images_loop calls print_image once per image."""
    backend = AsyncMock()
    backend.print_image = AsyncMock()

    await default_print_images_loop(
        backend,
        three_images,
        tape_spec_12,
        auto_cut=True,
        high_resolution=False,
        half_cut=True,
    )

    assert backend.print_image.call_count == 3


@pytest.mark.anyio
async def test_intermediate_items_get_half_cut_true_last_page_false(three_images, tape_spec_12):
    """Items 0 and 1 (non-last): half_cut=True, last_page=False."""
    backend = AsyncMock()
    backend.print_image = AsyncMock()

    await default_print_images_loop(
        backend,
        three_images,
        tape_spec_12,
        auto_cut=True,
        high_resolution=False,
        half_cut=True,
    )

    # Inspect kwargs of calls
    calls = backend.print_image.call_args_list
    assert calls[0].kwargs["half_cut"] is True
    assert calls[0].kwargs["last_page"] is False
    assert calls[1].kwargs["half_cut"] is True
    assert calls[1].kwargs["last_page"] is False


@pytest.mark.anyio
async def test_last_item_gets_half_cut_false_last_page_true(three_images, tape_spec_12):
    """Last item: half_cut=False (full cut), last_page=True."""
    backend = AsyncMock()
    backend.print_image = AsyncMock()

    await default_print_images_loop(
        backend,
        three_images,
        tape_spec_12,
        auto_cut=True,
        high_resolution=False,
        half_cut=True,
    )

    calls = backend.print_image.call_args_list
    assert calls[-1].kwargs["half_cut"] is False
    assert calls[-1].kwargs["last_page"] is True


@pytest.mark.anyio
async def test_half_cut_false_disables_half_cut_globally(three_images, tape_spec_12):
    """If caller passes half_cut=False, no intermediate item gets half_cut=True."""
    backend = AsyncMock()
    backend.print_image = AsyncMock()

    await default_print_images_loop(
        backend,
        three_images,
        tape_spec_12,
        auto_cut=True,
        high_resolution=False,
        half_cut=False,
    )

    for call in backend.print_image.call_args_list:
        assert call.kwargs["half_cut"] is False


@pytest.mark.anyio
async def test_single_image_gets_last_page_true(tape_spec_12):
    """Single-item batch: 1 print_image call with last_page=True."""
    backend = AsyncMock()
    backend.print_image = AsyncMock()
    one_image = [Image.new("1", (600, 70), color=1)]

    await default_print_images_loop(
        backend,
        one_image,
        tape_spec_12,
        auto_cut=True,
        high_resolution=False,
        half_cut=True,
    )

    assert backend.print_image.call_count == 1
    assert backend.print_image.call_args.kwargs["last_page"] is True
    assert backend.print_image.call_args.kwargs["half_cut"] is False


@pytest.mark.anyio
async def test_propagates_first_print_image_exception(three_images, tape_spec_12):
    """If print_image raises on item N, no further items are attempted."""
    backend = AsyncMock()
    backend.print_image = AsyncMock(side_effect=[None, RuntimeError("printer offline"), None])

    with pytest.raises(RuntimeError, match="printer offline"):
        await default_print_images_loop(
            backend,
            three_images,
            tape_spec_12,
            auto_cut=True,
            high_resolution=False,
            half_cut=True,
        )

    # Only the first two were attempted; third was not.
    assert backend.print_image.call_count == 2
