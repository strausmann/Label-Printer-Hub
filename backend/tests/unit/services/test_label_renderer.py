import pytest
from app.schemas.label_data import LabelData
from app.schemas.template import LayoutElement, TemplateSchema
from app.services.label_renderer import (
    DEFAULT_LABEL_WIDTH_PX,
    TAPE_HEIGHT_PX,
    LabelRenderer,
)
from PIL import Image


def test_render_produces_image_with_correct_height_24mm() -> None:
    template = TemplateSchema(
        id="t1",
        name="Test",
        app="snipeit",
        tape_mm=24,
        elements=[
            LayoutElement(type="text", x=10, y=10, field="title", font_size=24),
        ],
    )
    data = LabelData(
        title="Hello",
        primary_id="ID-1",
        qr_payload="x",
        source_app="snipeit",
    )

    img = LabelRenderer().render(data, template)

    assert isinstance(img, Image.Image)
    assert img.height == TAPE_HEIGHT_PX[24]
    assert img.mode == "1"


def test_render_produces_image_with_correct_height_12mm() -> None:
    template = TemplateSchema(
        id="t1",
        name="Test",
        app="snipeit",
        tape_mm=12,
        elements=[LayoutElement(type="text", x=5, y=5, field="title", font_size=16)],
    )
    data = LabelData(title="x", primary_id="x", qr_payload="x", source_app="snipeit")
    img = LabelRenderer().render(data, template)
    assert img.height == TAPE_HEIGHT_PX[12]


def test_render_rejects_unsupported_tape_mm() -> None:
    template = TemplateSchema(
        id="t1",
        name="Test",
        app="snipeit",
        tape_mm=99,
        elements=[],
    )
    data = LabelData(title="x", primary_id="x", qr_payload="x", source_app="snipeit")
    with pytest.raises(ValueError, match="99"):
        LabelRenderer().render(data, template)


def test_render_with_qr_element_includes_black_pixels() -> None:
    """A QR element must produce a non-trivial number of black pixels in its bbox."""
    template = TemplateSchema(
        id="t1",
        name="Test",
        app="snipeit",
        tape_mm=24,
        elements=[
            LayoutElement(type="qr", x=0, y=0, size=200, data_field="qr_payload"),
        ],
    )
    data = LabelData(
        title="X",
        primary_id="X",
        qr_payload="https://example.com",
        source_app="snipeit",
    )

    img = LabelRenderer().render(data, template)
    qr_region = img.crop((0, 0, 200, 200))
    black_count = sum(1 for p in qr_region.get_flattened_data() if p == 0)
    assert black_count > 100, f"Expected QR to produce many black pixels, got {black_count}"


def test_render_resolves_secondary_tuple_field() -> None:
    """secondary is a tuple — renderer must join the entries when used as a text field."""
    template = TemplateSchema(
        id="t1",
        name="Test",
        app="snipeit",
        tape_mm=24,
        elements=[
            LayoutElement(type="text", x=10, y=100, field="secondary", font_size=16),
        ],
    )
    data = LabelData(
        title="X",
        primary_id="X",
        qr_payload="x",
        source_app="snipeit",
        secondary=("Color: Black", "Weight: 850g"),
    )

    img = LabelRenderer().render(data, template)
    # The text region should not be entirely white (some pixels must be drawn).
    region = img.crop((10, 100, DEFAULT_LABEL_WIDTH_PX, 120))
    black_count = sum(1 for p in region.get_flattened_data() if p == 0)
    assert black_count > 0


def test_render_empty_template_produces_blank_image() -> None:
    """An empty template (no elements) must render a blank white canvas."""
    template = TemplateSchema(id="t", name="T", app="snipeit", tape_mm=24, elements=[])
    data = LabelData(title="X", primary_id="X", qr_payload="x", source_app="snipeit")
    img = LabelRenderer().render(data, template)
    # All pixels should be 1 (white background).
    assert all(p == 1 for p in img.get_flattened_data())


def test_render_with_missing_data_field_renders_empty_string() -> None:
    """If a template references a field LabelData doesn't have, render empty (no crash)."""
    template = TemplateSchema(
        id="t1",
        name="Test",
        app="snipeit",
        tape_mm=24,
        elements=[
            LayoutElement(type="text", x=10, y=10, field="nonexistent_field", font_size=16),
        ],
    )
    data = LabelData(title="X", primary_id="X", qr_payload="x", source_app="snipeit")
    # Must NOT raise — missing fields render as empty strings.
    img = LabelRenderer().render(data, template)
    assert img is not None


def test_font_loader_is_cached() -> None:
    """Same font_size returns the same font instance (LRU-cached)."""
    from app.services.label_renderer import _load_font_cached

    a = _load_font_cached(24)
    b = _load_font_cached(24)
    assert a is b
