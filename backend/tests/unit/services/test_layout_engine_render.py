"""Render tests per ContentType — output image checks (size, content)."""

from __future__ import annotations

from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.schemas.tape_geometry import TAPE_GEOMETRY
from app.services.layout_engine import LayoutEngine


class TestRenderQROnly:
    def test_image_height_matches_printable_px_12mm(self) -> None:
        eng = LayoutEngine()
        img = eng.render(
            tape_mm=12,
            content_type=ContentType.QR_ONLY,
            data=LabelData(source_app="manual", qr_payload="https://example.com/x"),
        )
        assert img.height == TAPE_GEOMETRY[12].printable_px == 70

    def test_image_mode_is_1bit(self) -> None:
        eng = LayoutEngine()
        img = eng.render(
            tape_mm=12,
            content_type=ContentType.QR_ONLY,
            data=LabelData(source_app="manual", qr_payload="https://example.com/x"),
        )
        assert img.mode == "1"

    def test_qr_pixels_present(self) -> None:
        eng = LayoutEngine()
        img = eng.render(
            tape_mm=12,
            content_type=ContentType.QR_ONLY,
            data=LabelData(source_app="manual", qr_payload="https://example.com/x"),
        )
        black = sum(1 for p in img.getdata() if p == 0)
        assert black > 200, f"Expected QR pixels; got {black} black pixels"

    def test_24mm_renders(self) -> None:
        eng = LayoutEngine()
        img = eng.render(
            tape_mm=24,
            content_type=ContentType.QR_ONLY,
            data=LabelData(source_app="manual", qr_payload="https://example.com/y"),
        )
        assert img.height == TAPE_GEOMETRY[24].printable_px == 128


class TestRenderQROneLine:
    def test_image_height_matches_printable_px(self) -> None:
        from app.schemas.content_type import ContentType
        from app.schemas.label_data import LabelData
        from app.schemas.tape_geometry import TAPE_GEOMETRY
        from app.services.layout_engine import LayoutEngine

        eng = LayoutEngine()
        img = eng.render(
            tape_mm=12,
            content_type=ContentType.QR_ONE_LINE,
            data=LabelData(
                source_app="manual",
                qr_payload="https://example.com/x",
                primary_id="X-001",
            ),
        )
        assert img.height == TAPE_GEOMETRY[12].printable_px

    def test_width_includes_text_column(self) -> None:
        from app.schemas.content_type import ContentType
        from app.schemas.label_data import LabelData
        from app.schemas.tape_geometry import TAPE_GEOMETRY
        from app.services.layout_engine import LayoutEngine

        eng = LayoutEngine()
        img = eng.render(
            tape_mm=12,
            content_type=ContentType.QR_ONE_LINE,
            data=LabelData(
                source_app="manual",
                qr_payload="https://example.com/x",
                primary_id="X-001",
            ),
        )
        assert img.width > TAPE_GEOMETRY[12].text_start_x
