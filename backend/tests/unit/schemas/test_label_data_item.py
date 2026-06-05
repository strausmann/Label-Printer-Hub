"""Unit tests for LabelDataItem (qr_with_listing child)."""

from __future__ import annotations

import pytest
from app.schemas.label_data_item import LabelDataItem
from pydantic import ValidationError


class TestLabelDataItem:
    def test_minimal_item(self) -> None:
        item = LabelDataItem(item="A — Schrauben")
        assert item.item == "A — Schrauben"
        assert item.qr_payload is None

    def test_with_qr_payload(self) -> None:
        item = LabelDataItem(item="B", qr_payload="https://example.com/locations/k02/b")
        assert item.qr_payload == "https://example.com/locations/k02/b"

    def test_item_required(self) -> None:
        with pytest.raises(ValidationError, match="item"):
            LabelDataItem()  # type: ignore[call-arg]

    def test_frozen(self) -> None:
        item = LabelDataItem(item="A")
        with pytest.raises(ValidationError, match="frozen_instance"):
            item.item = "B"  # type: ignore[misc]
