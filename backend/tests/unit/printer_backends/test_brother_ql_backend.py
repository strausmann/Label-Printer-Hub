"""Phase 1i Sub-Task G: BrotherQLBackend tests."""

from __future__ import annotations

import logging

import pytest
from app.models.tape import TapeSpec
from app.printer_backends.brother_ql_backend import BrotherQLBackend
from app.services.status_block import MediaType
from PIL import Image


@pytest.fixture
def tape_spec_62() -> TapeSpec:
    """QL-Series 62mm continuous-length tape spec (DK-2205 etc.)."""
    return TapeSpec(
        width_mm=62,
        media_type=MediaType.CONTINUOUS_LENGTH_TAPE,
        print_area_pins=696,
        print_area_dots=696,
        bytes_per_raster=90,
        min_length_mm=0,
        max_length_mm=30480,
        cutter_min_length_mm=0,
    )


@pytest.fixture
def dummy_image() -> Image.Image:
    """Minimal 696x200 white image — matches QL-820NWB 62mm print width."""
    return Image.new("RGB", (696, 200), "white")


@pytest.mark.anyio
async def test_print_image_calls_brother_ql_send(
    monkeypatch: pytest.MonkeyPatch,
    dummy_image: Image.Image,
    tape_spec_62: TapeSpec,
) -> None:
    """Phase 1i G: print_image -> convert + helpers.send via asyncio.to_thread."""
    send_calls: list[tuple] = []

    def fake_send(data, identifier, **kwargs):
        send_calls.append((identifier, len(data), kwargs))

    monkeypatch.setattr("app.printer_backends.brother_ql_backend._helpers_send", fake_send)

    backend = BrotherQLBackend(host="172.16.51.213", port=9100, model_id="QL-820NWB")
    await backend.print_image(dummy_image, tape_spec_62, auto_cut=True, last_page=True)
    assert len(send_calls) == 1
    identifier, payload_len, _kwargs = send_calls[0]
    assert identifier == "tcp://172.16.51.213:9100"
    assert payload_len > 0


@pytest.mark.anyio
async def test_half_cut_ignored_on_ql_with_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    dummy_image: Image.Image,
    tape_spec_62: TapeSpec,
) -> None:
    """half_cut=True wird vom QL-Backend ignoriert + Warning geloggt."""
    monkeypatch.setattr(
        "app.printer_backends.brother_ql_backend._helpers_send",
        lambda *a, **k: None,
    )
    backend = BrotherQLBackend(host="x", port=9100, model_id="QL-820NWB")
    with caplog.at_level(logging.WARNING, logger="app.printer_backends.brother_ql_backend"):
        await backend.print_image(dummy_image, tape_spec_62, half_cut=True)
    assert any("half_cut" in rec.message.lower() for rec in caplog.records)


def test_half_cut_supported_is_false() -> None:
    assert BrotherQLBackend.half_cut_supported is False
