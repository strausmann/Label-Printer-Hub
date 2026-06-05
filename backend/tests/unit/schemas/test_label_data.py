import pytest
from app.schemas.label_data import LabelData
from app.schemas.label_data_item import (
    LabelDataItem,
)
from pydantic import ValidationError


def test_label_data_all_fields() -> None:
    """Construction with all fields must succeed and fields must be accessible."""
    data = LabelData(
        title="MacBook Pro 16",
        primary_id="ASSET-12345",
        qr_payload="https://snipe-it.example/assets/12345",
        source_app="snipeit",
    )
    assert data.title == "MacBook Pro 16"
    assert data.primary_id == "ASSET-12345"
    assert data.qr_payload == "https://snipe-it.example/assets/12345"
    assert data.source_app == "snipeit"
    assert data.secondary == ()


def test_label_data_with_secondary_fields() -> None:
    data = LabelData(
        source_app="spoolman",
        secondary=["Color: Black", "Weight: 850g"],
    )
    assert len(data.secondary) == 2
    assert data.secondary[0] == "Color: Black"
    # The tuple is the actual immutability guarantee — confirm.
    assert isinstance(data.secondary, tuple)


def test_label_data_is_frozen() -> None:
    """LabelData is an immutable value object — mutating fields after construction must fail."""
    data = LabelData(source_app="snipeit")
    with pytest.raises(ValidationError, match="frozen_instance"):
        data.title = "different"  # type: ignore[misc]


def test_label_data_secondary_is_immutable() -> None:
    """A tuple field cannot be mutated in-place — append must raise AttributeError."""
    data = LabelData(
        source_app="snipeit",
        secondary=["a"],
    )
    with pytest.raises(AttributeError):
        data.secondary.append("b")  # type: ignore[attr-defined]


class TestLabelDataOptionalFields:
    def test_only_source_app_required(self) -> None:
        data = LabelData(source_app="manual")
        assert data.title is None
        assert data.primary_id is None
        assert data.qr_payload is None
        assert data.secondary == ()
        assert data.items == ()

    def test_all_fields_set(self) -> None:
        data = LabelData(
            source_app="hangar",
            primary_id="K-02",
            title="Werkstatt",
            qr_payload="https://example.com/locations/k-02",
            secondary=("Notiz 1",),
            items=(LabelDataItem(item="A"), LabelDataItem(item="B")),
        )
        assert data.items[0].item == "A"
        assert len(data.items) == 2

    def test_frozen(self) -> None:
        data = LabelData(source_app="manual")
        with pytest.raises(ValidationError, match="frozen_instance"):
            data.title = "x"  # type: ignore[misc]

    def test_source_app_required(self) -> None:
        with pytest.raises(ValidationError, match="source_app"):
            LabelData()  # type: ignore[call-arg]
