"""Phase 1k.2 Task 7: _QLQueuePrinter.print_images adapter tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.printer_models.ql import QL820NWBDriver
from app.services.tape_registry import TapeRegistry
from PIL import Image

# ---------------------------------------------------------------------------
# Phase 1k.2 Task 7: print_images adapter
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_ql_queue_printer_print_images_forwards_to_backend() -> None:
    """_QLQueuePrinter.print_images calls backend.print_images with tape_spec.

    Gemini-Review G-R2-1: lookup_ql benoetigt tape_mm UND media_type.
    QL erzwingt half_cut=False intern (kein half_cut in QL-Series Spec).
    """
    stub_backend = MagicMock()
    stub_backend.print_images = AsyncMock()
    stub_backend.half_cut_supported = False
    stub_tape_registry = TapeRegistry()

    driver = QL820NWBDriver(backend=stub_backend)
    adapter = driver.make_queue_printer(
        stub_tape_registry,
        printer_id=uuid4(),
    )

    images = [Image.new("1", (696, 200), color=1) for _ in range(2)]
    await adapter.print_images(
        images,
        tape_mm=62,
        auto_cut=True,
        high_resolution=False,
        half_cut=False,
    )

    stub_backend.print_images.assert_awaited_once()
    call = stub_backend.print_images.call_args
    assert call.args[0] is images, "images list must be passed as first positional arg"
    assert call.args[1].width_mm == 62, "tape_spec.width_mm must match tape_mm"
    assert call.kwargs["auto_cut"] is True
    # QL erzwingt half_cut=False (QL-Series hat kein half_cut)
    assert call.kwargs["half_cut"] is False, "QL must enforce half_cut=False"


@pytest.mark.anyio
async def test_ql_queue_printer_print_images_ignores_caller_half_cut_true() -> None:
    """half_cut=True vom Caller wird auf False erzwungen (QL-Series-Einschraenkung)."""
    stub_backend = MagicMock()
    stub_backend.print_images = AsyncMock()
    stub_backend.half_cut_supported = False
    stub_tape_registry = TapeRegistry()

    driver = QL820NWBDriver(backend=stub_backend)
    adapter = driver.make_queue_printer(stub_tape_registry)

    images = [Image.new("1", (696, 100), color=1)]
    await adapter.print_images(
        images,
        tape_mm=62,
        auto_cut=False,
        high_resolution=True,
        half_cut=True,  # Caller sendet True — Adapter muss False erzwingen
    )

    call = stub_backend.print_images.call_args
    assert call.kwargs["half_cut"] is False, "half_cut=True from caller must be coerced to False"
    assert call.kwargs["auto_cut"] is False
    assert call.kwargs["high_resolution"] is True
