"""LayoutEngine — semantic layout rendering driven by ContentType + TapeGeometry.

Replaces the v1 LabelRenderer. Each render() call resolves:
  1. tape_mm -> TapeGeometry (via TAPE_GEOMETRY dict)
  2. content_type-required fields -> validated against LabelData
  3. Dispatched to a per-ContentType _render_*() method
  4. Returns a PIL Image whose height matches geometry.printable_px

The _render_*() methods are implemented in subsequent tasks (7-13).
"""

from __future__ import annotations

from typing import ClassVar

from PIL import Image

from app.printer_backends.exceptions import (
    ContentTypeDataMismatchError,
    UnsupportedTapeError,
)
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.schemas.tape_geometry import TAPE_GEOMETRY, TapeGeometry


class LayoutEngine:
    """Tape-independent semantic label renderer.

    Stateless — safe to instantiate once and reuse across requests.
    """

    _REQUIRED_FIELDS: ClassVar[dict[ContentType, tuple[str, ...]]] = {
        ContentType.QR_ONLY: ("qr_payload",),
        ContentType.QR_ONE_LINE: ("qr_payload", "primary_id"),
        ContentType.QR_TWO_LINES: ("qr_payload", "primary_id", "title"),
        ContentType.QR_THREE_LINES: ("qr_payload", "primary_id", "title", "secondary"),
        ContentType.TEXT_ONE_LINE: ("primary_id",),
        ContentType.TEXT_TWO_LINES: ("primary_id", "title"),
        ContentType.QR_WITH_LISTING: ("qr_payload", "primary_id", "items"),
    }
    """ContentType -> ordered tuple of LabelData field names that must be set.

    Used by _validate_data to produce ContentTypeDataMismatchError with a
    complete missing-fields list (one 422 instead of multiple round-trips).
    """

    def render(
        self,
        tape_mm: int,
        content_type: ContentType,
        data: LabelData,
    ) -> Image.Image:
        """Render a label for the given tape width + content type + data.

        Raises:
            UnsupportedTapeError (409): tape_mm not in TAPE_GEOMETRY.
            ContentTypeDataMismatchError (422): data missing required fields.
        """
        geometry = self._lookup_geometry(tape_mm)
        self._validate_data(content_type, data)

        match content_type:
            case ContentType.QR_ONLY:
                return self._render_qr_only(geometry, data)
            case ContentType.QR_ONE_LINE:
                return self._render_qr_one_line(geometry, data)
            case ContentType.QR_TWO_LINES:
                return self._render_qr_two_lines(geometry, data)
            case ContentType.QR_THREE_LINES:
                return self._render_qr_three_lines(geometry, data)
            case ContentType.TEXT_ONE_LINE:
                return self._render_text_one_line(geometry, data)
            case ContentType.TEXT_TWO_LINES:
                return self._render_text_two_lines(geometry, data)
            case ContentType.QR_WITH_LISTING:
                return self._render_qr_with_listing(geometry, data)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _lookup_geometry(self, tape_mm: int) -> TapeGeometry:
        geom = TAPE_GEOMETRY.get(tape_mm)
        if geom is None:
            raise UnsupportedTapeError(tape_mm=tape_mm)
        return geom

    def _validate_data(self, content_type: ContentType, data: LabelData) -> None:
        required = self._REQUIRED_FIELDS[content_type]
        missing: list[str] = []
        for field_name in required:
            value = getattr(data, field_name)
            # Empty string, empty tuple, or None counts as missing.
            if value is None or (hasattr(value, "__len__") and len(value) == 0):
                missing.append(field_name)
        if missing:
            raise ContentTypeDataMismatchError(
                content_type=str(content_type),
                missing_fields=tuple(missing),
            )

    # ------------------------------------------------------------------
    # _render_* methods — implemented in Tasks 7-13
    # ------------------------------------------------------------------

    def _render_qr_only(
        self,
        geometry: TapeGeometry,
        data: LabelData,
    ) -> Image.Image:
        raise NotImplementedError("Task 7")

    def _render_qr_one_line(
        self,
        geometry: TapeGeometry,
        data: LabelData,
    ) -> Image.Image:
        raise NotImplementedError("Task 8")

    def _render_qr_two_lines(
        self,
        geometry: TapeGeometry,
        data: LabelData,
    ) -> Image.Image:
        raise NotImplementedError("Task 9")

    def _render_qr_three_lines(
        self,
        geometry: TapeGeometry,
        data: LabelData,
    ) -> Image.Image:
        raise NotImplementedError("Task 10")

    def _render_text_one_line(
        self,
        geometry: TapeGeometry,
        data: LabelData,
    ) -> Image.Image:
        raise NotImplementedError("Task 11")

    def _render_text_two_lines(
        self,
        geometry: TapeGeometry,
        data: LabelData,
    ) -> Image.Image:
        raise NotImplementedError("Task 12")

    def _render_qr_with_listing(
        self,
        geometry: TapeGeometry,
        data: LabelData,
    ) -> Image.Image:
        raise NotImplementedError("Task 13")
