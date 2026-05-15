from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from app.models.tape import TapeSpec
from app.printer_backends.base import PrinterBackend
from app.printer_backends.exceptions import (
    PrinterOfflineError,
    PrintFailedError,
    TapeEmptyError,
    TapeMismatchError,
)
from app.printer_backends.ptouch_backend import PTouchBackend
from app.services.status_block import MediaType
from PIL import Image

from tests._helpers.status import make_status_block


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


def test_satisfies_protocol() -> None:
    assert isinstance(PTouchBackend(host="1.2.3.4"), PrinterBackend)


def test_backend_id() -> None:
    assert PTouchBackend(host="x").backend_id == "ptouch"


def test_constructor_rejects_empty_host() -> None:
    with pytest.raises(ValueError):
        PTouchBackend(host="")


def test_constructor_rejects_unknown_model() -> None:
    with pytest.raises(ValueError):
        PTouchBackend(host="x", model_id="Imaginary-9000")


async def test_query_status_delegates_to_socket_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    healthy = make_status_block(loaded_tape_mm=24)

    async def fake_query(host: str, port: int, *, timeout_s: float):
        assert host == "10.0.0.5"
        assert port == 9100
        return healthy

    monkeypatch.setattr(
        "app.printer_backends.ptouch_backend.query_status_over_socket",
        fake_query,
    )
    backend = PTouchBackend(host="10.0.0.5")
    status = await backend.query_status()
    assert status is healthy


async def test_query_status_retries_on_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = {"n": 0}

    async def fake_query(*_a, **_kw):
        attempts["n"] += 1
        raise PrinterOfflineError("nope")

    async def fast_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr(
        "app.printer_backends.ptouch_backend.query_status_over_socket",
        fake_query,
    )
    monkeypatch.setattr("asyncio.sleep", fast_sleep)
    backend = PTouchBackend(host="x")
    with pytest.raises(PrinterOfflineError):
        await backend.query_status()
    assert attempts["n"] == 3


async def test_print_image_validates_status_first(
    monkeypatch: pytest.MonkeyPatch,
    img_128: Image.Image,
    tape_24: TapeSpec,
) -> None:
    bad = make_status_block(tape_empty=True, loaded_tape_mm=0)

    async def fake_query(*_a, **_kw):
        return bad

    monkeypatch.setattr(
        "app.printer_backends.ptouch_backend.query_status_over_socket",
        fake_query,
    )
    ptouch_print = MagicMock()
    monkeypatch.setattr(
        "app.printer_backends.ptouch_backend._ptouch_print",
        ptouch_print,
    )
    backend = PTouchBackend(host="x")
    with pytest.raises(TapeEmptyError):
        await backend.print_image(img_128, tape_24)
    ptouch_print.assert_not_called()


async def test_print_image_raises_tape_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    img_128: Image.Image,
    tape_24: TapeSpec,
) -> None:
    async def fake_query(*_a, **_kw):
        return make_status_block(loaded_tape_mm=12)

    monkeypatch.setattr(
        "app.printer_backends.ptouch_backend.query_status_over_socket",
        fake_query,
    )
    backend = PTouchBackend(host="x")
    with pytest.raises(TapeMismatchError) as exc:
        await backend.print_image(img_128, tape_24)
    assert exc.value.expected_mm == 24
    assert exc.value.loaded_mm == 12


async def test_print_image_invokes_ptouch_when_healthy(
    monkeypatch: pytest.MonkeyPatch,
    img_128: Image.Image,
    tape_24: TapeSpec,
) -> None:
    async def fake_query(*_a, **_kw):
        return make_status_block(loaded_tape_mm=24)

    monkeypatch.setattr(
        "app.printer_backends.ptouch_backend.query_status_over_socket",
        fake_query,
    )
    captured: dict[str, Any] = {}

    def fake_print(host, port, image, tape_mm, *, model_id, auto_cut, high_resolution):
        captured["host"] = host
        captured["port"] = port
        captured["tape_mm"] = tape_mm
        captured["model_id"] = model_id
        captured["auto_cut"] = auto_cut
        captured["high_resolution"] = high_resolution

    monkeypatch.setattr(
        "app.printer_backends.ptouch_backend._ptouch_print",
        fake_print,
    )
    backend = PTouchBackend(host="10.0.0.5")
    await backend.print_image(img_128, tape_24, auto_cut=True, high_resolution=False)
    assert captured["host"] == "10.0.0.5"
    assert captured["port"] == 9100
    assert captured["tape_mm"] == 24
    assert captured["model_id"] == "PT-P750W"
    assert captured["auto_cut"] is True


async def test_print_image_wraps_ptouch_exception(
    monkeypatch: pytest.MonkeyPatch,
    img_128: Image.Image,
    tape_24: TapeSpec,
) -> None:
    import ptouch as _ptouch

    async def fake_query(*_a, **_kw):
        return make_status_block(loaded_tape_mm=24)

    def fake_print(*_a, **_kw):
        raise _ptouch.PrinterWriteError("disk full")

    monkeypatch.setattr(
        "app.printer_backends.ptouch_backend.query_status_over_socket",
        fake_query,
    )
    monkeypatch.setattr(
        "app.printer_backends.ptouch_backend._ptouch_print",
        fake_print,
    )
    backend = PTouchBackend(host="x")
    with pytest.raises(PrintFailedError) as exc:
        await backend.print_image(img_128, tape_24)
    assert "disk full" in str(exc.value)


def test_from_settings_reads_pt750w_host() -> None:
    class S:
        pt750w_host = "10.0.0.5"
        pt750w_port = 9100
        printer_model = "PT-P750W"

    backend = PTouchBackend.from_settings(S())
    assert backend.host == "10.0.0.5"


def test_from_settings_empty_host_raises() -> None:
    class S:
        pt750w_host = ""
        pt750w_port = 9100
        printer_model = "PT-P750W"

    with pytest.raises(ValueError, match="pt750w_host"):
        PTouchBackend.from_settings(S())


def test_tape_class_map_uses_generic_ptouch_tape_classes() -> None:
    """Hardware smoke revealed PTP750W.get_tape_config() rejects LaminatedTape*mm
    subclasses (raises ValueError). Only the generic Tape*mm classes are
    whitelisted by the ptouch library. This test pins the dict to the
    generic flavour so the regression doesn't come back.
    """
    import ptouch
    from app.printer_backends.ptouch_backend import _PTOUCH_TAPE_CLASSES

    assert _PTOUCH_TAPE_CLASSES[12] is ptouch.Tape12mm
    assert _PTOUCH_TAPE_CLASSES[24] is ptouch.Tape24mm
    assert _PTOUCH_TAPE_CLASSES[18] is ptouch.Tape18mm
    # The whole set must be generic (no LaminatedTape subclass anywhere)
    for tape_mm, tape_cls in _PTOUCH_TAPE_CLASSES.items():
        assert "Laminated" not in tape_cls.__name__, (
            f"_PTOUCH_TAPE_CLASSES[{tape_mm}] = {tape_cls.__name__} — "
            "must be generic Tape*mm, ptouch's PT-Series whitelist rejects "
            "LaminatedTape*mm subclasses (verified on real hardware)."
        )
