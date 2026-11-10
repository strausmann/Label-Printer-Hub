"""QL 62 mm labels are laid across the tape width with a fixed QR size per tape (#258).

These tests use only ``LayoutEngine.render(62, ...)`` without any layout option: the default
for 62 mm DK endless tape is the across-width "compact" preset. The golden images are the
references printed and approved on a QL-820NWB (branch ``docs/ql-layout-presets``).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.services.layout_engine import LayoutEngine
from PIL import Image, ImageChops

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ql_layout"
DOTS_PER_MM = 300 / 25.4
PRINTABLE_62 = 696

REFERENCE = LabelData(
    source_app="manual",
    primary_id="ST00019",
    title="DOCKER1",
    secondary=("Dell OptiPlex 3070 Micro", "S/N 72104Z2"),
    qr_payload="https://example.invalid/hardware/19",
)


def _render(data: LabelData, content_type: ContentType = ContentType.QR_TWO_LINES) -> Image.Image:
    return LayoutEngine().render(62, content_type, data)


def _black_box(image: Image.Image, x_max: int) -> tuple[int, int, int, int]:
    """Bounding box of black pixels left of ``x_max`` (the QR area)."""
    region = image.convert("L").crop((0, 0, x_max, image.height))
    inverted = region.point(lambda v: 255 if v == 0 else 0)
    box = inverted.getbbox()
    assert box is not None, "no black pixels in the QR area"
    return box


def _module_px(image: Image.Image, box: tuple[int, int, int, int]) -> int:
    """Module size of a version-3 QR (29 modules) whose black bounding box is ``box``."""
    left, top, right, bottom = box
    side = right - left
    assert side == bottom - top, "QR is not square"
    assert side % 29 == 0, f"QR side {side} px is not a whole number of modules"
    return side // 29


def test_qr_two_lines_62mm_is_696_wide_and_at_most_30mm_long() -> None:
    data = LabelData(
        source_app="manual",
        primary_id="ST00019",
        title="DOCKER1",
        qr_payload="https://example.invalid/hardware/19",
    )
    image = _render(data)
    assert image.width == PRINTABLE_62
    assert image.height <= round(30 * DOTS_PER_MM)


def test_long_title_wraps_or_truncates_without_growing_the_width() -> None:
    short = _render(
        LabelData(
            source_app="manual",
            primary_id="ST00019",
            title="DOCKER1",
            qr_payload="https://example.invalid/hardware/19",
        )
    )
    long_title = "A very long asset title that can never fit on one line of a 62 mm label " * 4
    long = _render(
        LabelData(
            source_app="manual",
            primary_id="ST00019",
            title=long_title,
            qr_payload="https://example.invalid/hardware/19",
        )
    )
    assert long.width == short.width == PRINTABLE_62
    assert long.height >= short.height
    # bounded: the label never runs away with the text
    assert long.height <= round(50 * DOTS_PER_MM)


def test_qr_modules_are_whole_pixels_and_the_quiet_zone_is_present() -> None:
    image = _render(REFERENCE, ContentType.QR_THREE_LINES)
    box = _black_box(image, x_max=230)
    module = _module_px(image, box)
    left, top, right, bottom = box
    assert module == 6  # compact: 6 px modules
    # quiet zone: 4 modules across the width, at least 2 modules along the feed (compact)
    assert left >= 4 * module
    assert top >= 2 * module
    assert image.height - bottom >= 2 * module
    gap = image.convert("L").crop((right, 0, right + 4 * module, image.height))
    assert gap.getextrema() == (255, 255), "text intrudes into the quiet zone"


def test_qr_has_the_same_size_and_position_for_any_payload_and_text() -> None:
    """Maintainer decision: one fixed QR per tape, the label grows instead (#258)."""
    small = _render(
        LabelData(
            source_app="manual",
            primary_id="A1",
            title="Box",
            qr_payload="https://example.invalid/1",
        )
    )
    large = _render(
        LabelData(
            source_app="manual",
            primary_id="ST00019-LONG-CODE",
            title="Network attached storage, rack 2, shelf 4, left side",
            secondary=("Synology DS1821+ with expansion unit", "S/N 1234ABCD5678", "MAC 00:11:32"),
            qr_payload="https://example.invalid/hardware/1234567",
        ),
        ContentType.QR_THREE_LINES,
    )
    medium = _render(
        LabelData(
            source_app="manual",
            primary_id="ST00019",
            title="DOCKER1",
            qr_payload="https://example.invalid/hardware/19",
        )
    )
    small_box = _black_box(small, x_max=222)
    medium_box = _black_box(medium, x_max=222)
    large_box = _black_box(large, x_max=222)
    # The finder patterns pin the code's corners, so the black bounding box is the code.
    # Controller ruling: the fixed thing is the QR *box* (code + quiet zone, 222 px across
    # for compact); the version follows the payload and the code is centred in the box.
    # Same version (both 35-40 bytes, version 3): identical pixels.
    assert (medium_box[0], medium_box[2]) == (large_box[0], large_box[2])
    assert medium_box[2] - medium_box[0] == large_box[2] - large_box[0] == 29 * 6
    # Any version: the code is centred in the fixed box across the width (x centre 111) ...
    for box in (small_box, medium_box, large_box):
        assert (box[0] + box[2]) / 2 == 111
    # ... and vertically centred on the label (integer centring: +-1 px)
    assert small.height == medium.height  # the box, not the code, sets the minimum length
    small_offset = small_box[1] + small_box[3] - small.height
    medium_offset = medium_box[1] + medium_box[3] - medium.height
    large_offset = large_box[1] + large_box[3] - large.height
    assert large.height > small.height
    assert abs(small_offset) <= 1 and abs(medium_offset) <= 1 and abs(large_offset) <= 1


@pytest.mark.parametrize("content_type", [ContentType.QR_ONLY, ContentType.QR_ONE_LINE])
def test_every_qr_content_type_is_laid_across(content_type: ContentType) -> None:
    image = _render(REFERENCE, content_type)
    assert image.width == PRINTABLE_62
    assert image.height < image.width


def test_default_62mm_label_equals_the_compact_reference() -> None:
    image = _render(REFERENCE, ContentType.QR_THREE_LINES)
    reference = Image.open(FIXTURES / "ql62-across-compact.png").convert("1")
    assert image.size == reference.size
    diff = ImageChops.difference(image.convert("L"), reference.convert("L"))
    assert diff.getbbox() is None, "rendered label differs from the approved compact reference"
