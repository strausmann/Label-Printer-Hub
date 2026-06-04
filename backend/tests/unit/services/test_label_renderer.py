from unittest.mock import patch

import pytest
from app.schemas.label_data import LabelData
from app.schemas.template import LayoutElement, TemplateSchema
from app.services.label_renderer import (
    DEFAULT_LABEL_WIDTH_PX,
    TAPE_HEIGHT_PX,
    LabelRenderer,
)
from PIL import Image, ImageFont


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

    img = LabelRenderer().render(template, data)

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
    img = LabelRenderer().render(template, data)
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
        LabelRenderer().render(template, data)


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

    img = LabelRenderer().render(template, data)
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

    img = LabelRenderer().render(template, data)
    # The text region should not be entirely white (some pixels must be drawn).
    region = img.crop((10, 100, DEFAULT_LABEL_WIDTH_PX, 120))
    black_count = sum(1 for p in region.get_flattened_data() if p == 0)
    assert black_count > 0


def test_render_empty_template_produces_blank_image() -> None:
    """An empty template (no elements) must render a blank white canvas."""
    template = TemplateSchema(id="t", name="T", app="snipeit", tape_mm=24, elements=[])
    data = LabelData(title="X", primary_id="X", qr_payload="x", source_app="snipeit")
    img = LabelRenderer().render(template, data)
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
    img = LabelRenderer().render(template, data)
    assert img is not None


def test_font_loader_is_cached() -> None:
    """Same font_size returns the same font instance (LRU-cached)."""
    from app.services.label_renderer import _load_font_cached

    a = _load_font_cached(24)
    b = _load_font_cached(24)
    assert a is b


def test_load_font_calls_truetype_only_once_per_size() -> None:
    """ImageFont.truetype() must be called exactly once per (font, size) pair.

    The lru_cache on _load_font_cached memoises the result — repeated calls
    with the same size must not re-read the font file from disk.
    """
    from app.services.label_renderer import _load_font_cached

    # Clear the cache so we control how many truetype() calls happen in this test.
    _load_font_cached.cache_clear()
    call_count = 0
    original_truetype = ImageFont.truetype

    def counting_truetype(font: object, size: object, **kwargs: object) -> ImageFont.FreeTypeFont:
        nonlocal call_count
        call_count += 1
        return original_truetype(font, size, **kwargs)  # type: ignore[arg-type]

    with patch.object(ImageFont, "truetype", counting_truetype):
        _load_font_cached(16)
        _load_font_cached(16)
        _load_font_cached(16)

    assert call_count == 1, (
        f"Expected ImageFont.truetype to be called once for size=16 "
        f"(lru_cache should memoize), but it was called {call_count} time(s)"
    )


# ---------------------------------------------------------------------------
# Phase 1i smoke-test live-bug: DejaVuSans TTF verfügbar (font_size honored)
# ---------------------------------------------------------------------------


def test_label_renderer_uses_truetype_font() -> None:
    """font_size-Parameter muss tatsächlich die Textgröße skalieren (kein Bitmap-Fallback).

    Root Cause: Container ohne fonts-dejavu-core → ImageFont.truetype('DejaVuSans.ttf', N)
    schlägt mit OSError fehl → _load_font_cached fällt auf load_default() zurück.
    Pillow's load_default() ist eine fixe-Größe Bitmap-Font die size IGNORIERT.
    Fix: fonts-dejavu-core im Dockerfile installieren — siehe backend/Dockerfile.

    In CI/Container ist die TTF garantiert verfügbar (apt-get install im Dockerfile).
    Auf Dev-Rechnern (macOS/Windows ohne system-DejaVuSans) wird der Test übersprungen
    statt zu failen — damit lokaler TDD-Workflow nicht durch fehlende Host-Fonts gestört
    wird. (Gemini-Review PR #100)
    """
    import os
    from pathlib import Path

    from app.services.label_renderer import _load_font_cached
    from PIL import ImageFont

    # Cache leeren damit der Test sauber von Null startet
    _load_font_cached.cache_clear()

    in_ci = os.environ.get("CI") == "true" or Path("/.dockerenv").exists()
    try:
        probe = ImageFont.truetype("DejaVuSans.ttf", 12)
    except OSError:
        if in_ci:
            raise  # CI/Container MUSS die Font haben — apt-get-Fix verifizieren
        pytest.skip(
            "DejaVuSans.ttf nicht system-installiert — Dev-Maschine ohne fonts-dejavu. "
            "In CI/Container wird der Test ausgeführt (Dockerfile installiert die Font)."
        )
    del probe

    font = _load_font_cached(22)
    assert isinstance(font, ImageFont.FreeTypeFont), (
        f"Erwartet FreeTypeFont (TTF), bekommen {type(font).__name__}. "
        "Stelle sicher dass fonts-dejavu-core im Dockerfile installiert ist "
        "(/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf muss existieren)."
    )

    # Tatsächliche Skalierung verifizieren: größere font_size → größere Glyphen
    font10 = _load_font_cached(10)
    font22 = _load_font_cached(22)
    bbox10 = font10.getbbox("X")
    bbox22 = font22.getbbox("X")
    h10 = bbox10[3] - bbox10[1]
    h22 = bbox22[3] - bbox22[1]
    assert h22 > h10 * 1.5, (
        f"Font-Skalierung defekt: h10={h10}px, h22={h22}px (Faktor {h22 / h10:.1f}x < 1.5x). "
        "Bitmap-Fallback liefert immer dieselbe Höhe unabhängig von font_size."
    )


class TestWhitespaceTrim:
    """Cropping the inked content to save tape material on the length axis."""

    def test_qr_only_template_is_trimmed_to_content_plus_margin(self) -> None:
        template = TemplateSchema(
            schema_version=1,
            id="qr-only-12mm-test",
            name="QR only test",
            app=None,
            tape_mm=12,
            elements=(LayoutElement(type="qr", x=260, y=13, size=80, data_field="qr_payload"),),
        )
        data = LabelData(
            title="Smoke",
            primary_id="X",
            qr_payload="https://example.test/smoke",
            secondary=(),
            source_app="manual",
        )
        img = LabelRenderer().render(template, data)
        # The QR sits at x=260..340 with size=80; after trim with 6px margin,
        # width should be 80 + 2*6 = 92 px (give or take a pixel for QR rendering).
        assert img.width < 200, f"Expected compact label, got width={img.width}"
        # Height is pin-locked to ptouch Tape12mm print_pins (70px after DPI-Fix).
        assert img.height == TAPE_HEIGHT_PX[12], "Tape-axis height must stay fixed"

    def test_entirely_blank_template_returns_unchanged_canvas(self) -> None:
        template = TemplateSchema(
            schema_version=1,
            id="blank-test",
            name="Blank",
            app=None,
            tape_mm=12,
            elements=(),
        )
        data = LabelData(
            title="X",
            primary_id="X",
            qr_payload="X",
            secondary=(),
            source_app="manual",
        )
        img = LabelRenderer().render(template, data)
        # No ink → no trim → full default canvas
        assert img.width == 600
        # Height is pin-locked to ptouch Tape12mm print_pins (70px after DPI-Fix).
        assert img.height == TAPE_HEIGHT_PX[12]
