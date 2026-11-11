"""Explicit orientation and the three QL 62 mm presets (#258)."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.printer_backends.exceptions import QrPayloadTooLongError, UnsupportedTapeError
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.schemas.label_layout import LabelOrientation, LayoutDefault, QlLayoutPreset
from app.services.layout_engine import LayoutEngine
from app.services.ql_layout import resolve_layout
from PIL import Image, ImageChops

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ql_layout"

REFERENCE = LabelData(
    source_app="manual",
    primary_id="ST00019",
    title="DOCKER1",
    secondary=("Dell OptiPlex 3070 Micro", "S/N 72104Z2"),
    qr_payload="https://example.invalid/hardware/19",
)


def _qr_box(image: Image.Image, x_max: int, y_max: int | None = None) -> tuple[int, int, int, int]:
    region = image.convert("L").crop((0, 0, x_max, y_max or image.height))
    box = region.point(lambda v: 255 if v == 0 else 0).getbbox()
    assert box is not None
    return box


@pytest.mark.parametrize(
    ("preset", "fixture"),
    [
        (QlLayoutPreset.COMPACT, "ql62-across-compact.png"),
        (QlLayoutPreset.SMALL_QR, "ql62-across-small-qr.png"),
        (QlLayoutPreset.STANDARD, "ql62-across-standard.png"),
    ],
)
def test_preset_renders_the_approved_reference_pixel_exact(
    preset: QlLayoutPreset, fixture: str
) -> None:
    image = LayoutEngine().render(
        62,
        ContentType.QR_THREE_LINES,
        REFERENCE,
        orientation=LabelOrientation.ACROSS,
        preset=preset,
    )
    reference = Image.open(FIXTURES / fixture).convert("1")
    assert image.size == reference.size
    assert ImageChops.difference(image.convert("L"), reference.convert("L")).getbbox() is None


@pytest.mark.parametrize(
    ("preset", "module_px", "quiet_along_modules", "margin_px"),
    [
        (QlLayoutPreset.COMPACT, 6, 2, 0),
        (QlLayoutPreset.SMALL_QR, 6, 4, 6),
        (QlLayoutPreset.STANDARD, 7, 4, 24),
    ],
)
def test_preset_geometry_matches_the_readme_table(
    preset: QlLayoutPreset, module_px: int, quiet_along_modules: int, margin_px: int
) -> None:
    """QR-only: label length is exactly QR + quiet zone along the feed + layout margins."""
    image = LayoutEngine().render(
        62, ContentType.QR_ONLY, REFERENCE, orientation=LabelOrientation.ACROSS, preset=preset
    )
    left, _top, right, _bottom = _qr_box(image, x_max=image.width)
    assert right - left == 29 * module_px
    assert left == 4 * module_px  # 4-module quiet zone across the width
    assert image.height == (29 + 2 * quiet_along_modules) * module_px + 2 * margin_px


def test_along_62mm_uses_the_full_width_qr_and_grows_with_the_text() -> None:
    short = LayoutEngine().render(
        62,
        ContentType.QR_TWO_LINES,
        LabelData(
            source_app="manual", primary_id="C1", title="A", qr_payload="https://e.invalid/1"
        ),
        orientation=LabelOrientation.ALONG,
    )
    long = LayoutEngine().render(
        62,
        ContentType.QR_TWO_LINES,
        LabelData(
            source_app="manual",
            primary_id="CABLE-0042",
            title="Patch cable from rack 2 port 14 to the office switch",
            qr_payload="https://example.invalid/hardware/19",
        ),
        orientation=LabelOrientation.ALONG,
    )
    # along: the band across the tape is the printable width, the length grows with the text
    assert short.height == long.height == 696
    assert long.width > short.width
    box = 37 * 18  # the fixed QR box along: printable width minus the tape remainder
    short_box = _qr_box(short, x_max=box)  # the text starts after the box
    long_box = _qr_box(long, x_max=box)
    # the reference-length payload is version 3 at 18 px modules, 4-module quiet zone
    assert long_box[2] - long_box[0] == 29 * 18
    assert long_box[:2] == (4 * 18, (696 - box) // 2 + 4 * 18)
    # a shorter payload (version 2) sits centred in the identical fixed box
    assert _centre(short_box) == _centre(long_box) == (box / 2, 696 / 2)


def _centre(box: tuple[int, int, int, int]) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def test_payload_too_long_for_4px_modules_is_refused() -> None:
    """Compact's fixed box (222 px) holds at most version 7 at 4 px modules: 122 bytes at M."""
    data = LabelData(
        source_app="manual",
        primary_id="X",
        title="Y",
        qr_payload="https://example.invalid/" + "a" * 120,
    )
    with pytest.raises(QrPayloadTooLongError) as excinfo:
        LayoutEngine().render(62, ContentType.QR_TWO_LINES, data)
    assert excinfo.value.max_bytes == 122
    assert excinfo.value.length == len(data.qr_payload or "")


@pytest.mark.parametrize("payload_len", [19, 35, 73, 122])
@pytest.mark.parametrize("preset", list(QlLayoutPreset))
def test_any_fitting_payload_keeps_the_fixed_qr_box(
    payload_len: int, preset: QlLayoutPreset
) -> None:
    """The QR box (code + quiet zone) is fixed per preset; the code is centred in it, whole
    pixels per module (at least 4), quiet zone at least 4 modules across the width."""
    payload = ("https://example.invalid/" + "x" * 200)[:payload_len]
    ref = LayoutEngine().render(
        62, ContentType.QR_ONLY, REFERENCE, orientation=LabelOrientation.ACROSS, preset=preset
    )
    image = LayoutEngine().render(
        62,
        ContentType.QR_ONLY,
        REFERENCE.model_copy(update={"qr_payload": payload}),
        orientation=LabelOrientation.ACROSS,
        preset=preset,
    )
    assert image.size == ref.size  # same label: the box decides its length, not the payload
    ref_box = _qr_box(ref, ref.width)
    box = _qr_box(image, image.width)
    assert abs(_centre(box)[0] - _centre(ref_box)[0]) <= 0.5
    assert abs(_centre(box)[1] - _centre(ref_box)[1]) <= 0.5
    side = box[2] - box[0]
    module = next(m for m in range(12, 3, -1) if side % m == 0 and (side // m - 17) % 4 == 0)
    assert module >= 4
    assert box[0] >= 4 * module


def test_hub_test_label_payload_prints_on_62mm_across_and_along() -> None:
    """The hub's own test label QR (``{public_url}/printers/{uuid}``) is >= 67 bytes."""
    data = LabelData(
        source_app="manual",
        primary_id="QL-820NWB office",
        title="62 mm · 2026-11-10 12:00",
        secondary=("Printer Hub 1.5.0",),
        qr_payload="https://printhub.example.com/printers/0f8fad5b-d9cb-469f-a165-70867728950e",
    )
    assert len(data.qr_payload or "") >= 67
    across = LayoutEngine().render(62, ContentType.QR_THREE_LINES, data)
    along = LayoutEngine().render(
        62, ContentType.QR_THREE_LINES, data, orientation=LabelOrientation.ALONG
    )
    assert across.width == 696
    assert along.height == 696


@pytest.mark.parametrize("tape_mm", [12, 24])
def test_across_is_refused_for_other_widths(tape_mm: int) -> None:
    with pytest.raises(UnsupportedTapeError):
        LayoutEngine().render(
            tape_mm, ContentType.QR_TWO_LINES, REFERENCE, orientation=LabelOrientation.ACROSS
        )


def test_along_on_12mm_keeps_the_existing_band_layout() -> None:
    explicit = LayoutEngine().render(
        12, ContentType.QR_TWO_LINES, REFERENCE, orientation=LabelOrientation.ALONG
    )
    default = LayoutEngine().render(12, ContentType.QR_TWO_LINES, REFERENCE)
    assert explicit.size == default.size
    assert explicit.height == 70
    assert ImageChops.difference(explicit.convert("L"), default.convert("L")).getbbox() is None


# --- resolve_layout ---------------------------------------------------------------------


def test_resolve_defaults_to_across_compact_on_62mm() -> None:
    assert resolve_layout(62, None, None, None) == (LabelOrientation.ACROSS, QlLayoutPreset.COMPACT)


def test_resolve_takes_the_stored_default_when_the_request_has_none() -> None:
    stored = LayoutDefault(orientation=LabelOrientation.ACROSS, preset=QlLayoutPreset.STANDARD)
    assert resolve_layout(62, None, None, stored) == (
        LabelOrientation.ACROSS,
        QlLayoutPreset.STANDARD,
    )
    along = LayoutDefault(orientation=LabelOrientation.ALONG)
    assert resolve_layout(62, None, None, along)[0] is LabelOrientation.ALONG


def test_resolve_request_overrides_the_stored_default() -> None:
    stored = LayoutDefault(orientation=LabelOrientation.ALONG, preset=QlLayoutPreset.STANDARD)
    assert resolve_layout(62, LabelOrientation.ACROSS, QlLayoutPreset.SMALL_QR, stored) == (
        LabelOrientation.ACROSS,
        QlLayoutPreset.SMALL_QR,
    )


def test_resolve_other_widths_are_along_and_refuse_across() -> None:
    assert resolve_layout(12, None, None, None) == (LabelOrientation.ALONG, None)
    with pytest.raises(UnsupportedTapeError):
        resolve_layout(12, LabelOrientation.ACROSS, None, None)
