"""V4-Winner smoke script: LayoutEngine 12mm QR_TWO_LINES.

Phase 1k.1a (Task 25): Verifies that the LayoutEngine renders a 12mm
QR_TWO_LINES label to a valid PIL image without crashing.

Run from the backend directory:

    python -m scripts.smoke_layout_engine_12mm_v4

No printer hardware required -- pure rendering smoke test.
Exits 0 on success, 1 on failure.
"""

from __future__ import annotations

import io
import sys

from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.services.layout_engine import LayoutEngine
from PIL import Image


def main() -> int:
    """Run 12mm QR_TWO_LINES render smoke test."""
    engine = LayoutEngine()
    label_data = LabelData(
        source_app="smoke",
        primary_id="SMOKE-001",
        title="12mm V4-Winner",
        qr_payload="https://example.com/smoke/12mm",
    )

    print("Rendering 12mm QR_TWO_LINES label...")  # noqa: T201
    try:
        image = engine.render(12, ContentType.QR_TWO_LINES, label_data)
    except Exception as exc:
        print(f"FAIL: render raised {type(exc).__name__}: {exc}", file=sys.stderr)  # noqa: T201
        return 1

    if not isinstance(image, Image.Image):
        print(f"FAIL: expected PIL Image, got {type(image)!r}", file=sys.stderr)  # noqa: T201
        return 1

    if image.width <= 0 or image.height <= 0:
        print(  # noqa: T201
            f"FAIL: image has zero/negative dimensions: {image.size}",
            file=sys.stderr,
        )
        return 1

    print(  # noqa: T201
        f"OK: rendered {image.mode} image {image.width}x{image.height}px for 12mm QR_TWO_LINES"
    )

    # Spot-check: save as PNG bytes (exercises the codec pipeline)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    png_bytes = buf.getvalue()
    if len(png_bytes) < 100:  # A valid PNG is always > 100 bytes
        print(  # noqa: T201
            f"FAIL: PNG encode produced suspiciously small output ({len(png_bytes)} bytes)",
            file=sys.stderr,
        )
        return 1

    print(f"OK: PNG encode produced {len(png_bytes)} bytes")  # noqa: T201
    print("SMOKE PASS")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
