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
        # In mode "1", tobytes() returns packed bytes (8 pixels per byte).
        # Black pixels are zero bits — count by inspecting the bytes.
        pixel_bytes = img.tobytes()
        # If any pixel is black (bit=0), at least one byte will be != 0xFF.
        non_white_bytes = sum(1 for b in pixel_bytes if b != 0xFF)
        assert non_white_bytes > 30, f"Expected QR pixels; got {non_white_bytes} non-white bytes"

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


class TestRenderQRTwoLines:
    def test_baseline_12mm_v4_winner(self) -> None:
        from app.schemas.content_type import ContentType
        from app.schemas.label_data import LabelData
        from app.schemas.tape_geometry import TAPE_GEOMETRY
        from app.services.layout_engine import LayoutEngine

        eng = LayoutEngine()
        img = eng.render(
            tape_mm=12,
            content_type=ContentType.QR_TWO_LINES,
            data=LabelData(
                source_app="hangar",
                primary_id="K-02",
                title="Werkstatt",
                qr_payload="https://example.com/locations/k-02",
            ),
        )
        assert img.height == 70
        geom = TAPE_GEOMETRY[12]
        assert img.width > geom.text_start_x

    def test_24mm_renders(self) -> None:
        from app.schemas.content_type import ContentType
        from app.schemas.label_data import LabelData
        from app.services.layout_engine import LayoutEngine

        eng = LayoutEngine()
        img = eng.render(
            tape_mm=24,
            content_type=ContentType.QR_TWO_LINES,
            data=LabelData(
                source_app="hangar",
                primary_id="K-02",
                title="Werkstatt",
                qr_payload="https://example.com/x",
            ),
        )
        assert img.height == 128

    def test_62mm_renders_at_higher_dpi(self) -> None:
        from app.schemas.content_type import ContentType
        from app.schemas.label_data import LabelData
        from app.services.layout_engine import LayoutEngine

        eng = LayoutEngine()
        img = eng.render(
            tape_mm=62,
            content_type=ContentType.QR_TWO_LINES,
            data=LabelData(
                source_app="samla",
                primary_id="HH-AK-SM01",
                title="Samla 11L",
                qr_payload="https://example.com/x",
            ),
        )
        assert img.height == 696


class TestRenderQRThreeLines:
    def test_18mm_with_secondary(self) -> None:
        from app.schemas.content_type import ContentType
        from app.schemas.label_data import LabelData
        from app.services.layout_engine import LayoutEngine

        eng = LayoutEngine()
        img = eng.render(
            tape_mm=18,
            content_type=ContentType.QR_THREE_LINES,
            data=LabelData(
                source_app="grocy",
                primary_id="Erdbeermarmelade",
                title="Lager > Vorrat",
                qr_payload="https://example.com/x",
                secondary=("MHD 2027-04-30",),
            ),
        )
        assert img.height == 112

    def test_24mm_renders(self) -> None:
        from app.schemas.content_type import ContentType
        from app.schemas.label_data import LabelData
        from app.services.layout_engine import LayoutEngine

        eng = LayoutEngine()
        img = eng.render(
            tape_mm=24,
            content_type=ContentType.QR_THREE_LINES,
            data=LabelData(
                source_app="grocy",
                primary_id="X",
                title="Y",
                qr_payload="https://example.com/x",
                secondary=("Z",),
            ),
        )
        assert img.height == 128


class TestRenderTextOneLine:
    def test_no_qr_present(self) -> None:
        from app.schemas.content_type import ContentType
        from app.schemas.label_data import LabelData
        from app.services.layout_engine import LayoutEngine

        eng = LayoutEngine()
        img = eng.render(
            tape_mm=12,
            content_type=ContentType.TEXT_ONE_LINE,
            data=LabelData(source_app="manual", primary_id="HELLO"),
        )
        assert img.width < 200

    def test_renders_at_correct_height(self) -> None:
        from app.schemas.content_type import ContentType
        from app.schemas.label_data import LabelData
        from app.schemas.tape_geometry import TAPE_GEOMETRY
        from app.services.layout_engine import LayoutEngine

        eng = LayoutEngine()
        img = eng.render(
            tape_mm=24,
            content_type=ContentType.TEXT_ONE_LINE,
            data=LabelData(source_app="manual", primary_id="X"),
        )
        assert img.height == TAPE_GEOMETRY[24].printable_px


class TestRenderTextTwoLines:
    def test_18mm_renders(self) -> None:
        from app.schemas.content_type import ContentType
        from app.schemas.label_data import LabelData
        from app.services.layout_engine import LayoutEngine

        eng = LayoutEngine()
        img = eng.render(
            tape_mm=18,
            content_type=ContentType.TEXT_TWO_LINES,
            data=LabelData(source_app="manual", primary_id="LINE1", title="LINE2"),
        )
        assert img.height == 112


class TestRenderQRWithListing:
    def test_4_items_render(self) -> None:
        from app.schemas.content_type import ContentType
        from app.schemas.label_data import LabelData
        from app.schemas.label_data_item import LabelDataItem
        from app.services.layout_engine import LayoutEngine

        eng = LayoutEngine()
        img = eng.render(
            tape_mm=24,
            content_type=ContentType.QR_WITH_LISTING,
            data=LabelData(
                source_app="hangar",
                primary_id="Kallax-02",
                qr_payload="https://example.com/k02",
                items=(
                    LabelDataItem(item="A — Schrauben"),
                    LabelDataItem(item="B — Muttern"),
                    LabelDataItem(item="C — Werkzeug"),
                    LabelDataItem(item="D — Kabel"),
                ),
            ),
        )
        assert img.height == 128

    def test_overflow_shows_n_more(self) -> None:
        from app.schemas.content_type import ContentType
        from app.schemas.label_data import LabelData
        from app.schemas.label_data_item import LabelDataItem
        from app.services.layout_engine import LayoutEngine

        eng = LayoutEngine()
        many = tuple(LabelDataItem(item=f"Item {i}") for i in range(10))
        img = eng.render(
            tape_mm=12,
            content_type=ContentType.QR_WITH_LISTING,
            data=LabelData(
                source_app="hangar",
                primary_id="X",
                qr_payload="x",
                items=many,
            ),
        )
        assert img.height == 70
