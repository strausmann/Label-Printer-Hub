"""Unit tests for PrintRequest with content_type (no template_id)."""

from __future__ import annotations

import pytest
from app.schemas.content_type import ContentType
from app.schemas.print_request import (
    PrintLookupRequest,
    PrintRequest,
    RawLabelData,
)
from pydantic import ValidationError


class TestRawLabelData:
    def test_all_fields_optional(self) -> None:
        raw = RawLabelData()
        assert raw.title is None
        assert raw.primary_id is None
        assert raw.qr_payload is None
        assert raw.secondary == ()
        assert raw.items == ()

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError, match="extra"):
            RawLabelData(unknown_field="x")  # type: ignore[call-arg]


class TestPrintRequest:
    def test_with_content_type_and_raw_data(self) -> None:
        req = PrintRequest(
            content_type=ContentType.QR_TWO_LINES,
            data=RawLabelData(
                primary_id="K-02",
                title="Werkstatt",
                qr_payload="https://example.com/x",
            ),
        )
        assert req.content_type == ContentType.QR_TWO_LINES
        assert req.data is not None
        assert req.data.primary_id == "K-02"
        assert req.lookup is None

    def test_with_content_type_and_lookup(self) -> None:
        req = PrintRequest(
            content_type=ContentType.QR_ONLY,
            lookup=PrintLookupRequest(app="snipeit", identifier="ABC-123"),
        )
        assert req.lookup is not None
        assert req.lookup.app == "snipeit"
        assert req.data is None

    def test_both_data_and_lookup_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Exactly one"):
            PrintRequest(
                content_type=ContentType.QR_ONLY,
                data=RawLabelData(qr_payload="x"),
                lookup=PrintLookupRequest(app="snipeit", identifier="X"),
            )

    def test_neither_data_nor_lookup_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Exactly one"):
            PrintRequest(content_type=ContentType.QR_ONLY)

    def test_no_template_id_field(self) -> None:
        with pytest.raises(ValidationError, match="extra"):
            PrintRequest(
                template_id="anything",
                content_type=ContentType.QR_ONLY,
                data=RawLabelData(qr_payload="x"),
            )  # type: ignore[call-arg]

    def test_no_on_tape_mismatch_field(self) -> None:
        with pytest.raises(ValidationError, match="extra"):
            PrintRequest(
                on_tape_mismatch="queue",
                content_type=ContentType.QR_ONLY,
                data=RawLabelData(qr_payload="x"),
            )  # type: ignore[call-arg]
