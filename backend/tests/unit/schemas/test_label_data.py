import pytest
from app.schemas.label_data import LabelData
from pydantic_core import ValidationError


def test_label_data_minimal() -> None:
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
        title="BambuLab PLA",
        primary_id="#42",
        qr_payload="https://spoolman.example/spool/42",
        source_app="spoolman",
        secondary=["Color: Black", "Weight: 850g"],
    )
    assert len(data.secondary) == 2
    assert data.secondary[0] == "Color: Black"
    # The tuple is the actual immutability guarantee — confirm.
    assert isinstance(data.secondary, tuple)


def test_label_data_is_frozen() -> None:
    """LabelData is an immutable value object — mutating fields after construction must fail."""
    data = LabelData(
        title="t",
        primary_id="p",
        qr_payload="q",
        source_app="snipeit",
    )
    with pytest.raises(ValidationError, match="frozen_instance"):
        data.title = "different"  # type: ignore[misc]


def test_label_data_secondary_is_immutable() -> None:
    """A tuple field cannot be mutated in-place — append must raise AttributeError."""
    data = LabelData(
        title="t",
        primary_id="p",
        qr_payload="q",
        source_app="snipeit",
        secondary=["a"],
    )
    with pytest.raises(AttributeError):
        data.secondary.append("b")  # type: ignore[attr-defined]
