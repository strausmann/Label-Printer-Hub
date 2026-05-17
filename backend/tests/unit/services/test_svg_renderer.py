"""Unit tests for app.services.svg_renderer.

Verifies that the SVG renderer produces valid XML with correct structure,
pure-vector ``<text>`` elements, a QR ``<path>`` element, a viewBox that
matches the tape dimensions, and a title annotation strip above the tape
outline.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest
from app.services.label_renderer import TAPE_HEIGHT_PX
from app.services.svg_renderer import (
    _ANNOTATION_HEIGHT_PX,
    render_template_svg,
)

SVG_NS = "http://www.w3.org/2000/svg"


def _findall(root: ET.Element, local_tag: str) -> list[ET.Element]:
    """Find all descendant elements matching a local tag name (ignoring namespace)."""
    return root.findall(f".//{{{SVG_NS}}}{local_tag}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_definition(
    tape_mm: int = 12,
    *,
    include_qr: bool = True,
    include_text: bool = True,
) -> dict[str, object]:
    elements: list[dict[str, object]] = []
    if include_qr:
        elements.append({"type": "qr", "x": 8, "y": 13, "size": 60, "data_field": "qr_payload"})
    if include_text:
        elements.append({"type": "text", "x": 80, "y": 18, "font_size": 20, "field": "primary_id"})
    return {
        "id": f"test-{tape_mm}mm",
        "tape_mm": tape_mm,
        "elements": elements,
    }


def _sample() -> dict[str, object]:
    return {"primary_id": "TestValue", "qr_payload": "https://example.com/"}


# ---------------------------------------------------------------------------
# Core contract
# ---------------------------------------------------------------------------


def test_svg_renderer_produces_valid_xml_with_text_elements() -> None:
    definition = _minimal_definition()
    svg = render_template_svg(definition, _sample())

    assert "<svg" in svg
    assert "</svg>" in svg
    assert "TestValue" in svg  # text element rendered as pure <text>
    assert "viewBox" in svg

    # Must parse as valid XML without exceptions.
    root = ET.fromstring(svg)
    assert root.tag == f"{{{SVG_NS}}}svg"


def test_svg_contains_no_base64_image_embeds() -> None:
    """Text and QR must be pure-vector — no raster embeds allowed."""
    definition = _minimal_definition()
    svg = render_template_svg(definition, _sample())

    assert "data:image/png;base64" not in svg
    assert "data:image/jpeg;base64" not in svg


def test_svg_viewbox_matches_tape_dimensions() -> None:
    """viewBox width=600, height=TAPE_HEIGHT_PX[tape_mm] + annotation strip."""
    for tape_mm in (12, 18, 24):
        definition = _minimal_definition(tape_mm)
        svg = render_template_svg(definition, _sample())
        root = ET.fromstring(svg)

        expected_h = TAPE_HEIGHT_PX[tape_mm] + _ANNOTATION_HEIGHT_PX
        vb = root.attrib.get("viewBox", "")
        parts = vb.split()
        assert len(parts) == 4, f"Unexpected viewBox for tape_mm={tape_mm}: {vb!r}"
        assert int(parts[2]) == 600, f"viewBox width should be 600 for tape_mm={tape_mm}"
        assert int(parts[3]) == expected_h, (
            f"viewBox height should be {expected_h} for tape_mm={tape_mm}, got {parts[3]}"
        )


def test_svg_contains_tape_outline_rect() -> None:
    """A gray <rect> must mark the printable tape area."""
    definition = _minimal_definition()
    svg = render_template_svg(definition, _sample())
    root = ET.fromstring(svg)

    rects = _findall(root, "rect")
    assert rects, "No <rect> element found — tape outline is missing"
    # The rect should have a gray stroke.
    strokes = [el.attrib.get("stroke", "") for el in rects]
    assert any(s == "#aaa" for s in strokes), f"Expected gray stroke #aaa on rect, got {strokes}"


def test_svg_contains_qr_path_element() -> None:
    """QR codes must be rendered as a pure-vector <path>, not <image>."""
    definition = _minimal_definition(include_text=False)
    svg = render_template_svg(definition, _sample())
    root = ET.fromstring(svg)

    paths = _findall(root, "path")
    assert paths, "No <path> element found — QR code is not rendered as vector"

    images = _findall(root, "image")
    assert not images, f"Found unexpected <image> elements: {images}"


def test_svg_text_value_is_present() -> None:
    """The sample field value must appear verbatim in a <text> element."""
    definition = _minimal_definition(include_qr=False)
    svg = render_template_svg(definition, _sample())
    root = ET.fromstring(svg)

    texts = _findall(root, "text")
    # Filter out the annotation strip (which has fill="#666") — look for user data.
    user_texts = [el for el in texts if el.attrib.get("fill") == "black"]
    values = [el.text or "" for el in user_texts]
    assert any("TestValue" in v for v in values), (
        f"Expected 'TestValue' in a <text fill='black'> element, got: {values}"
    )


def test_svg_annotation_strip_shows_template_key() -> None:
    """The annotation strip above the tape must show the template id."""
    definition = _minimal_definition()
    svg = render_template_svg(definition, _sample())

    assert "test-12mm" in svg  # the template id from _minimal_definition


def test_svg_list_secondary_field_joined_with_pipe() -> None:
    """List values (e.g. 'secondary') must be joined with ' | '."""
    definition: dict[str, object] = {
        "id": "test-list",
        "tape_mm": 18,
        "elements": [{"type": "text", "x": 10, "y": 20, "font_size": 14, "field": "secondary"}],
    }
    sample: dict[str, object] = {"secondary": ["Alpha", "Beta"], "qr_payload": "x"}
    svg = render_template_svg(definition, sample)
    assert "Alpha | Beta" in svg


def test_svg_xml_special_chars_escaped() -> None:
    """Ampersands and angle brackets in sample data must be XML-escaped."""
    definition: dict[str, object] = {
        "id": "test-escape",
        "tape_mm": 12,
        "elements": [{"type": "text", "x": 10, "y": 20, "font_size": 14, "field": "title"}],
    }
    sample: dict[str, object] = {"title": "A & B < C > D", "qr_payload": "x"}
    svg = render_template_svg(definition, sample)

    # The raw ampersand/angle must NOT appear outside CDATA.
    # The escaped forms must appear.
    assert "A &amp; B &lt; C &gt; D" in svg
    # Must still parse as valid XML.
    ET.fromstring(svg)


def test_svg_unsupported_tape_mm_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported tape_mm"):
        render_template_svg({"id": "bad", "tape_mm": 99, "elements": []}, {})


def test_svg_all_tape_sizes_produce_different_heights() -> None:
    """12mm, 18mm and 24mm tapes must result in different SVG heights."""
    heights = set()
    for tape_mm in (12, 18, 24):
        definition = _minimal_definition(tape_mm)
        svg = render_template_svg(definition, _sample())
        root = ET.fromstring(svg)
        heights.add(int(root.attrib.get("height", 0)))
    assert len(heights) == 3, f"Expected 3 distinct heights, got: {heights}"
