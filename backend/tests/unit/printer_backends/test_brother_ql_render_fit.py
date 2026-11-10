"""Regression tests for issue #254: every QL print crashed with ``Image.ANTIALIAS``.

Root cause: the hub's LayoutEngine renders landscape (PT convention: height == print-head
pins, width == label length), but ``brother_ql.conversion.convert`` expects endless-label
images with width == ``dots_printable[0]``. A landscape image never matched, so ``convert``
took its resize branch, which uses ``Image.ANTIALIAS`` (removed in Pillow 10).

These tests run the real ``convert`` (no mock) and assert the resize branch is not taken.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from app.printer_backends import brother_ql_backend
from app.printer_backends.brother_ql_backend import BrotherQLBackend
from app.printer_models.ql import QL_DK_ENDLESS_TAPES
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.services.layout_engine import LayoutEngine
from brother_ql.labels import ALL_LABELS
from PIL import Image

_RESIZE_WARNING = "Need to resize the image"
_TAPES = {t.width_mm: t for t in QL_DK_ENDLESS_TAPES}


def _dots_printable(width_mm: int) -> int:
    (label,) = [x for x in ALL_LABELS if x.identifier == str(width_mm)]
    return int(label.dots_printable[0])


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
    out: list[bytes] = []
    monkeypatch.setattr(
        "app.printer_backends.brother_ql_backend._helpers_send",
        lambda data, identifier, **kw: out.append(bytes(data)),
    )
    return out


@pytest.fixture
def convert_inputs(monkeypatch: pytest.MonkeyPatch) -> list[Image.Image]:
    """Record the image handed to the REAL convert()."""
    seen: list[Image.Image] = []
    real = brother_ql_backend.convert

    def spy(qlr: Any, images: list[Image.Image], *args: Any, **kwargs: Any) -> Any:
        seen.extend(images)
        return real(qlr, images, *args, **kwargs)

    monkeypatch.setattr(brother_ql_backend, "convert", spy)
    return seen


def _no_resize(caplog: pytest.LogCaptureFixture) -> bool:
    return not any(_RESIZE_WARNING in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(
    "content_type",
    [
        ContentType.QR_ONLY,
        ContentType.QR_ONE_LINE,
        ContentType.QR_TWO_LINES,
        ContentType.QR_THREE_LINES,
        ContentType.TEXT_ONE_LINE,
        ContentType.TEXT_TWO_LINES,
    ],
)
async def test_hub_rendered_62mm_label_goes_through_real_convert_without_resize(
    content_type: ContentType,
    sent: list[bytes],
    convert_inputs: list[Image.Image],
    caplog: pytest.LogCaptureFixture,
) -> None:
    data = LabelData(
        source_app="manual",
        primary_id="ABC-0042",
        title="Resistor box",
        secondary=("shelf 3",),
        qr_payload="https://example.invalid/x/42",
    )
    image = LayoutEngine().render(62, content_type, data)
    backend = BrotherQLBackend(host="192.0.2.11")

    with caplog.at_level(logging.WARNING, logger="brother_ql"):
        await backend.print_image(image, _TAPES[62])

    assert _no_resize(caplog), "convert() took its resize branch: image size/orientation wrong"
    # length is preserved as height: short text labels (narrower than 696) must be rotated too
    assert convert_inputs[0].size == (696, image.size[0])
    assert sent, "nothing was sent"


@pytest.mark.parametrize("width_mm", sorted(_TAPES))
async def test_landscape_label_is_fitted_for_every_ql_width(
    width_mm: int,
    sent: list[bytes],
    convert_inputs: list[Image.Image],
    caplog: pytest.LogCaptureFixture,
) -> None:
    pins = _dots_printable(width_mm)
    assert _TAPES[width_mm].print_area_pins == pins  # hub spec == brother_ql spec
    image = Image.new("1", (pins * 2 + 37, pins), color=1)  # PT convention: height == pins
    backend = BrotherQLBackend(host="192.0.2.11")

    with caplog.at_level(logging.WARNING, logger="brother_ql"):
        await backend.print_image(image, _TAPES[width_mm])

    assert _no_resize(caplog)
    assert convert_inputs[0].size == (pins, pins * 2 + 37)


async def test_landscape_rotation_keeps_text_start_on_first_printed_row(
    sent: list[bytes], convert_inputs: list[Image.Image]
) -> None:
    """Left edge of the landscape image (text start) must be printed first (row 0)."""
    image = Image.new("1", (900, 696), color=1)
    image.putpixel((0, 0), 0)  # top-left marker
    await BrotherQLBackend(host="192.0.2.11").print_image(image, _TAPES[62])

    out = convert_inputs[0]
    assert out.size == (696, 900)
    assert out.getpixel((695, 0)) == 0  # marker in row 0 (clockwise rotation)
    assert out.histogram()[0] == 1  # exactly one black pixel: nothing duplicated or lost


async def test_image_already_at_printable_width_is_not_rotated(
    sent: list[bytes], convert_inputs: list[Image.Image], caplog: pytest.LogCaptureFixture
) -> None:
    image = Image.new("1", (696, 300), color=1)
    with caplog.at_level(logging.WARNING, logger="brother_ql"):
        await BrotherQLBackend(host="192.0.2.11").print_image(image, _TAPES[62])
    assert convert_inputs[0].size == (696, 300)
    assert _no_resize(caplog)


async def test_square_image_at_printable_width_is_left_alone(
    sent: list[bytes], convert_inputs: list[Image.Image]
) -> None:
    await BrotherQLBackend(host="192.0.2.11").print_image(
        Image.new("1", (696, 696), color=1), _TAPES[62]
    )
    assert convert_inputs[0].size == (696, 696)


# --- Pillow compatibility shim -------------------------------------------------------


def test_shim_maps_missing_antialias_to_lanczos(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.printer_backends._pillow_compat import ensure_antialias_alias

    # Register the attribute with monkeypatch first, so teardown restores "absent" instead of
    # leaking the alias into later tests (which would mask a missing import-time shim).
    monkeypatch.setattr(Image, "ANTIALIAS", None, raising=False)
    monkeypatch.delattr(Image, "ANTIALIAS")
    ensure_antialias_alias()
    assert Image.ANTIALIAS == Image.Resampling.LANCZOS  # type: ignore[attr-defined]


def test_shim_does_not_override_existing_attribute(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.printer_backends._pillow_compat import ensure_antialias_alias

    monkeypatch.setattr(Image, "ANTIALIAS", "sentinel", raising=False)
    ensure_antialias_alias()
    assert Image.ANTIALIAS == "sentinel"  # type: ignore[attr-defined]


async def test_mismatched_size_degrades_instead_of_crashing(
    sent: list[bytes], caplog: pytest.LogCaptureFixture
) -> None:
    """Too tall for the tape even after orientation: convert() must resize (and warn), not crash."""
    image = Image.new("1", (800, 1000), color=1)
    with caplog.at_level(logging.WARNING, logger="brother_ql"):
        await BrotherQLBackend(host="192.0.2.11").print_image(image, _TAPES[62])
    assert sent
    assert not _no_resize(caplog), "resize must stay visible in the log"


# --- Codex review of PR #257 ---------------------------------------------------------

_TEXT_LAYOUTS = [
    ContentType.QR_ONE_LINE,
    ContentType.QR_TWO_LINES,
    ContentType.QR_THREE_LINES,
    ContentType.TEXT_ONE_LINE,
    ContentType.TEXT_TWO_LINES,
]


@pytest.mark.parametrize("content_type", _TEXT_LAYOUTS)
async def test_hub_rendered_12mm_label_is_rotated_padded_and_not_resized(
    content_type: ContentType,
    sent: list[bytes],
    convert_inputs: list[Image.Image],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """P1: production LayoutEngine renders 12 mm at 70 px (PT geometry); QL wants 106."""
    data = LabelData(
        source_app="manual",
        primary_id="ABC-0042",
        title="Resistor box",
        secondary=("shelf 3",),
        qr_payload="https://example.invalid/x/42",
    )
    image = LayoutEngine().render(12, content_type, data)
    assert image.size[1] == 70 and image.size[0] > image.size[1]  # premise: landscape, 70 high

    with caplog.at_level(logging.WARNING, logger="brother_ql"):
        await BrotherQLBackend(host="192.0.2.11").print_image(image, _TAPES[12])

    assert _no_resize(caplog), "12 mm label was stretched by convert()"
    # rotated (length kept as height) and padded to the printable width, not scaled
    assert convert_inputs[0].size == (106, image.size[0])
    assert sent


async def test_narrow_label_is_centred_on_white_padding(
    sent: list[bytes], convert_inputs: list[Image.Image]
) -> None:
    image = Image.new("1", (300, 70), color=1)
    image.putpixel((0, 0), 0)  # start of text, top edge of the 70 px band
    await BrotherQLBackend(host="192.0.2.11").print_image(image, _TAPES[12])

    out = convert_inputs[0]
    assert out.size == (106, 300)
    # 70 px centred in 106 px -> 18 px padding on each side; marker (clockwise) -> x=18+69, y=0
    assert out.getpixel((18 + 69, 0)) == 0
    assert out.histogram()[0] == 1
    assert out.getpixel((0, 0)) == 255 and out.getpixel((105, 299)) == 255


@pytest.mark.parametrize("width_mm", sorted(_TAPES))
async def test_high_resolution_label_is_prepared_for_dpi_600(
    width_mm: int,
    sent: list[bytes],
    convert_inputs: list[Image.Image],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """P2: dpi_600 makes convert() halve the width, so the input must be 2x printable wide."""
    pins = _dots_printable(width_mm)
    image = Image.new("1", (pins + 41, pins), color=1)
    with caplog.at_level(logging.WARNING, logger="brother_ql"):
        await BrotherQLBackend(host="192.0.2.11").print_image(
            image, _TAPES[width_mm], high_resolution=True
        )

    assert _no_resize(caplog)
    # 300 dpi source doubled on both axes: same physical size at 600 dpi
    assert convert_inputs[0].size == (pins * 2, (pins + 41) * 2)
    assert sent


async def test_high_resolution_hub_rendered_62mm_label(
    sent: list[bytes], convert_inputs: list[Image.Image], caplog: pytest.LogCaptureFixture
) -> None:
    data = LabelData(
        source_app="manual",
        primary_id="ABC-0042",
        title="Box",
        qr_payload="https://example.invalid/1",
    )
    image = LayoutEngine().render(62, ContentType.QR_TWO_LINES, data)
    with caplog.at_level(logging.WARNING, logger="brother_ql"):
        await BrotherQLBackend(host="192.0.2.11").print_image(
            image, _TAPES[62], high_resolution=True
        )
    assert _no_resize(caplog)
    assert convert_inputs[0].size == (1392, image.size[0] * 2)
