"""The QL backend orients images on the explicit ``orientation`` flag (#258).

The 1.4.1 size heuristic (rotate when height <= printable width) is ambiguous for images
narrower than the tape; with the flag the backend rotates only for ``along``. The heuristic
stays as a safety net for images that arrive without a flag (see test_brother_ql_render_fit).
All tests run the real ``brother_ql`` ``convert()`` and assert its resize branch is not taken.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock

import pytest
from app.printer_backends import brother_ql_backend
from app.printer_backends.brother_ql_backend import BrotherQLBackend
from app.printer_models.ql import QL_DK_ENDLESS_TAPES, QL820NWBDriver
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.schemas.label_layout import LabelOrientation, QlLayoutPreset
from app.services.layout_engine import LayoutEngine
from app.services.status_block import MediaType
from PIL import Image

_RESIZE_WARNING = "Need to resize the image"
_TAPES = {t.width_mm: t for t in QL_DK_ENDLESS_TAPES}
_PRINTABLE = {12: 106, 62: 696}

DATA = LabelData(
    source_app="manual",
    primary_id="ST00019",
    title="DOCKER1",
    secondary=("Dell OptiPlex 3070 Micro", "S/N 72104Z2"),
    qr_payload="https://example.invalid/hardware/19",
)


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
    seen: list[Image.Image] = []
    real = brother_ql_backend.convert

    def spy(qlr: Any, images: list[Image.Image], *args: Any, **kwargs: Any) -> Any:
        seen.extend(images)
        return real(qlr, images, *args, **kwargs)

    monkeypatch.setattr(brother_ql_backend, "convert", spy)
    return seen


def _no_resize(caplog: pytest.LogCaptureFixture) -> bool:
    return not any(_RESIZE_WARNING in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("preset", list(QlLayoutPreset))
async def test_across_label_goes_through_convert_unrotated_and_unresized(
    preset: QlLayoutPreset,
    sent: list[bytes],
    convert_inputs: list[Image.Image],
    caplog: pytest.LogCaptureFixture,
) -> None:
    image = LayoutEngine().render(
        62, ContentType.QR_THREE_LINES, DATA, orientation=LabelOrientation.ACROSS, preset=preset
    )
    with caplog.at_level(logging.WARNING, logger="brother_ql"):
        await BrotherQLBackend(host="192.0.2.11").print_image(
            image, _TAPES[62], orientation=LabelOrientation.ACROSS
        )
    assert _no_resize(caplog)
    assert convert_inputs[0].size == image.size == (696, image.height)
    assert convert_inputs[0].convert("1").tobytes() == image.tobytes()
    assert sent


async def test_along_label_is_rotated_on_the_flag_and_not_resized(
    sent: list[bytes], convert_inputs: list[Image.Image], caplog: pytest.LogCaptureFixture
) -> None:
    image = LayoutEngine().render(
        62, ContentType.QR_TWO_LINES, DATA, orientation=LabelOrientation.ALONG
    )
    assert image.height == 696  # landscape band
    with caplog.at_level(logging.WARNING, logger="brother_ql"):
        await BrotherQLBackend(host="192.0.2.11").print_image(
            image, _TAPES[62], orientation=LabelOrientation.ALONG
        )
    assert _no_resize(caplog)
    assert convert_inputs[0].size == (696, image.width)


async def test_across_label_at_600_dpi_is_doubled_not_resized(
    sent: list[bytes], convert_inputs: list[Image.Image], caplog: pytest.LogCaptureFixture
) -> None:
    image = LayoutEngine().render(62, ContentType.QR_TWO_LINES, DATA)
    with caplog.at_level(logging.WARNING, logger="brother_ql"):
        await BrotherQLBackend(host="192.0.2.11").print_image(
            image, _TAPES[62], high_resolution=True, orientation=LabelOrientation.ACROSS
        )
    assert _no_resize(caplog)
    assert convert_inputs[0].size == (1392, image.height * 2)


# The ambiguous cases from the PR #257 review: the heuristic guesses, the flag decides.
_AMBIGUOUS = [
    # (tape, image size, orientation, expected convert input size, marker position after)
    (62, (500, 300), LabelOrientation.ACROSS, (696, 300), ((696 - 500) // 2, 0)),
    (62, (500, 300), LabelOrientation.ALONG, (696, 500), ((696 - 300) // 2 + 299, 0)),
    (12, (70, 80), LabelOrientation.ACROSS, (106, 80), ((106 - 70) // 2, 0)),
    (12, (70, 80), LabelOrientation.ALONG, (106, 70), ((106 - 80) // 2 + 79, 0)),
    (12, (106, 70), LabelOrientation.ACROSS, (106, 70), (0, 0)),
    (12, (106, 70), LabelOrientation.ALONG, (106, 106), ((106 - 70) // 2 + 69, 0)),
]


@pytest.mark.parametrize(("tape_mm", "size", "orientation", "expected", "marker"), _AMBIGUOUS)
async def test_ambiguous_sizes_follow_the_flag(
    tape_mm: int,
    size: tuple[int, int],
    orientation: LabelOrientation,
    expected: tuple[int, int],
    marker: tuple[int, int],
    sent: list[bytes],
    convert_inputs: list[Image.Image],
    caplog: pytest.LogCaptureFixture,
) -> None:
    image = Image.new("1", size, color=1)
    image.putpixel((0, 0), 0)  # top-left: start of the content
    with caplog.at_level(logging.WARNING, logger="brother_ql"):
        await BrotherQLBackend(host="192.0.2.11").print_image(
            image, _TAPES[tape_mm], orientation=orientation
        )
    out = convert_inputs[0]
    assert _no_resize(caplog)
    assert out.size == expected
    assert out.getpixel(marker) == 0
    assert out.histogram()[0] == 1  # one black pixel: nothing duplicated or lost


async def test_print_images_forwards_the_orientation(
    sent: list[bytes], convert_inputs: list[Image.Image]
) -> None:
    images = [Image.new("1", (500, 300), color=1) for _ in range(2)]
    await BrotherQLBackend(host="192.0.2.11").print_images(
        images, _TAPES[62], orientation=LabelOrientation.ACROSS
    )
    assert [im.size for im in convert_inputs] == [(696, 300), (696, 300)]


# --- queue adapter ----------------------------------------------------------------------


class _Registry:
    def lookup_ql(self, tape_mm: int, media_type: MediaType) -> Any:
        return _TAPES[tape_mm]


async def test_queue_printer_forwards_orientation_and_never_half_cut() -> None:
    """QL has no half-cut: the adapter drops it, as before #258; orientation passes through."""
    backend = AsyncMock()
    backend.host = "192.0.2.11"
    printer = QL820NWBDriver(backend=backend).make_queue_printer(_Registry())  # type: ignore[arg-type]
    image = Image.new("1", (696, 200), color=1)

    await printer.print_image(image, tape_mm=62, half_cut=True, orientation="across")
    kwargs = backend.print_image.await_args.kwargs
    assert kwargs["orientation"] is LabelOrientation.ACROSS
    assert kwargs.get("half_cut", False) is False

    await printer.print_images([image], tape_mm=62, half_cut=True, orientation="along")
    kwargs = backend.print_images.await_args.kwargs
    assert kwargs["orientation"] is LabelOrientation.ALONG
    assert kwargs["half_cut"] is False


async def test_queue_printer_without_orientation_keeps_the_heuristic() -> None:
    backend = AsyncMock()
    backend.host = "192.0.2.11"
    printer = QL820NWBDriver(backend=backend).make_queue_printer(_Registry())  # type: ignore[arg-type]
    await printer.print_image(Image.new("1", (696, 200), color=1), tape_mm=62)
    assert backend.print_image.await_args.kwargs["orientation"] is None
