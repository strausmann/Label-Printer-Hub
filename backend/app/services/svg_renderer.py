"""Render a label template as a pure-vector SVG string.

The SVG mirrors the LabelRenderer's pixel coordinate system 1:1 (top-left
origin, 300 DPI Brother geometry) so that SVG previews match what gets printed.

QR codes are rendered as inline pure-vector ``<path>`` elements using
qrcode's SvgPathImage factory.  All text elements become ``<text>`` nodes —
no raster embeds for text.  A gray ``<rect>`` outlines the tape boundary.

Coordinate system:
    - The tape's printable height is taken from TAPE_HEIGHT_PX, same as
      LabelRenderer.
    - The canvas width is fixed at DEFAULT_LABEL_WIDTH_PX (600 px), same as
      LabelRenderer, so element x/y coordinates translate 1:1.
    - An annotation strip of ANNOTATION_HEIGHT_PX is reserved above the tape
      rect so the viewBox shows the title line outside the printable area.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import qrcode
import qrcode.image.svg

from app.services.label_renderer import DEFAULT_LABEL_WIDTH_PX, TAPE_HEIGHT_PX

# Extra vertical space above the tape rect used for the template-key annotation.
_ANNOTATION_HEIGHT_PX: int = 18


def _qr_svg_group(qr_data: str, x: int, y: int, size_px: int) -> str:
    """Return an SVG ``<g>`` element containing the QR code as a pure-vector path.

    The path is extracted from qrcode's SvgPathImage output and scaled so that
    the QR module fills exactly ``size_px x size_px`` pixels at the given (x, y)
    position.

    Args:
        qr_data:  The payload to encode.
        x:        Left edge in the tape's pixel coordinate system.
        y:        Top edge in the tape's pixel coordinate system.
        size_px:  Target width/height in pixels.

    Returns:
        A ``<g transform="...">...</g>`` string ready for embedding in the SVG.
    """
    # Use box_size=1 + border=0 so the path coordinates are in module units
    # (integers), making the scale calculation straightforward.
    factory = qrcode.image.svg.SvgPathImage
    qr_img = qrcode.make(
        qr_data,
        image_factory=factory,
        box_size=1,
        border=0,
    )
    raw_svg = qr_img.to_string(encoding="unicode")

    # Parse the outer <svg> to grab the viewBox dimensions and the <path> element.
    root = ET.fromstring(raw_svg)
    ns = {"svg": "http://www.w3.org/2000/svg"}
    path_el = root.find("svg:path", ns)
    if path_el is None:
        # Fallback: try without namespace (some qrcode versions omit it)
        path_el = root.find("path")
    if path_el is None:
        raise RuntimeError(f"qrcode SvgPathImage produced no <path> element for data={qr_data!r}")

    path_d = path_el.attrib.get("d", "")

    # Derive the QR grid size from the viewBox.  With box_size=1 the viewBox
    # width equals the number of modules.
    vb = root.attrib.get("viewBox", "")
    vb_parts = vb.split()
    if len(vb_parts) == 4:
        qr_units = float(vb_parts[2])  # width in module units
    else:
        # Parse from width attribute ("29mm" etc.) as fallback.
        w_str = root.attrib.get("width", "1")
        qr_units = float(re.sub(r"[^0-9.]", "", w_str) or "1")

    scale = size_px / qr_units if qr_units else 1.0

    # Shift the annotation offset: QR y is in tape-space so we add
    # the annotation strip below in the outer SVG, not here.
    return (
        f'<g transform="translate({x},{y}) scale({scale:.6f})">'
        f'<path d="{path_d}" fill="black" fill-rule="evenodd"/>'
        f"</g>"
    )


def _annotation_label(template_id: str, tape_mm: int, elements: list[dict[str, object]]) -> str:
    """Return a short human-readable title string for the SVG annotation strip."""
    text_count = sum(1 for el in elements if el.get("type") == "text")
    plural = "s" if text_count != 1 else ""
    return f"{template_id} — tape {tape_mm}mm — {text_count} text line{plural}"


def _resolve_sample_value(field: str, sample: dict[str, object]) -> str:
    """Look up *field* in *sample*, joining list values with ' | '."""
    value = sample.get(field, "")
    if isinstance(value, (list, tuple)):
        return " | ".join(str(v) for v in value)
    return str(value)


def render_template_svg(
    template_definition: dict[str, object], sample_data: dict[str, object]
) -> str:
    """Render a template's preview as a pure-vector SVG string.

    The SVG mirrors the LabelRenderer's pixel coordinate system 1:1 so it
    matches the print output. QR codes are rendered as inline ``<path>``
    using python-qrcode's SvgPathImage factory; text elements become
    ``<text>``; the tape outline is a ``<rect>`` with a 1px gray border.

    Args:
        template_definition: contents of Template.definition JSON column
            (already deserialised). Must include ``tape_mm`` and ``elements``.
        sample_data: per-template preview_sample dict (already validated).

    Returns:
        Full SVG XML as a string starting with ``<svg …>``.
    """
    tape_mm = int(str(template_definition["tape_mm"]))
    tape_h = TAPE_HEIGHT_PX.get(tape_mm)
    if tape_h is None:
        raise ValueError(f"Unsupported tape_mm: {tape_mm}. Supported: {sorted(TAPE_HEIGHT_PX)}")

    w = DEFAULT_LABEL_WIDTH_PX
    raw_elements = template_definition.get("elements", [])
    element_list: list[object] = list(raw_elements) if isinstance(raw_elements, list) else []
    elements: list[dict[str, object]] = [dict(el) for el in element_list if isinstance(el, dict)]
    template_id = str(template_definition.get("id", "unknown"))

    # Total SVG height = annotation strip + tape body
    total_h = _ANNOTATION_HEIGHT_PX + tape_h

    # viewBox: origin is at the top-left of the annotation strip; the tape
    # rect starts at y=_ANNOTATION_HEIGHT_PX.
    vb = f"0 0 {w} {total_h}"

    lines: list[str] = []
    lines.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{total_h}" viewBox="{vb}">'
    )

    # — Annotation strip (outside the printable tape area) ——————————————
    annotation = _annotation_label(template_id, tape_mm, elements)
    lines.append(
        f'  <text x="4" y="{_ANNOTATION_HEIGHT_PX - 4}"'
        f' font-family="Liberation Sans, DejaVu Sans, sans-serif"'
        f' font-size="10" fill="#666">'
        f"{annotation}"
        f"</text>"
    )

    # — Tape background + outline ——————————————————————————————————————
    ty = _ANNOTATION_HEIGHT_PX  # tape top y in SVG coordinates
    lines.append(
        f'  <rect x="0.5" y="{ty + 0.5}" width="{w - 1}" height="{tape_h - 1}"'
        f' fill="white" stroke="#aaa" stroke-width="1"/>'
    )

    # — Label elements —————————————————————————————————————————————————
    for el in elements:
        el_type = str(el.get("type", ""))
        ex = int(str(el.get("x", 0)))
        ey = int(str(el.get("y", 0)))

        # Shift element y coordinates by the annotation strip height so that
        # the element positions in the SVG match the pixel coordinates used
        # by the LabelRenderer on the tape.
        svg_y = ty + ey

        if el_type == "qr":
            data_field = str(el.get("data_field", "qr_payload"))
            size_px = int(str(el.get("size", 80)))
            qr_data = _resolve_sample_value(data_field, sample_data)
            # QR group: translate to tape-offset-adjusted position.
            qr_group = _qr_svg_group(qr_data, ex, svg_y, size_px)
            lines.append(f"  {qr_group}")

        elif el_type == "text":
            field = str(el.get("field", ""))
            font_size = int(str(el.get("font_size", 14)))
            text_value = _resolve_sample_value(field, sample_data)
            # Escape XML special characters in user data.
            text_value = (
                text_value.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
            )
            lines.append(
                f'  <text x="{ex}" y="{svg_y + font_size}"'
                f' font-family="Liberation Sans, DejaVu Sans, sans-serif"'
                f' font-size="{font_size}"'
                f' fill="black">{text_value}</text>'
            )

    lines.append("</svg>")
    return "\n".join(lines)
