import pytest
from app.schemas.label_data import LabelData


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
    assert data.secondary == []


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


def test_label_data_is_frozen() -> None:
    """LabelData is an immutable value object — mutating fields after construction must fail."""
    import pydantic

    data = LabelData(
        title="t",
        primary_id="p",
        qr_payload="q",
        source_app="snipeit",
    )
    with pytest.raises(pydantic.ValidationError):
        data.title = "different"  # type: ignore[misc]


def test_label_data_default_secondary_is_distinct_per_instance() -> None:
    """The default empty list must NOT be a shared mutable default."""
    a = LabelData(title="a", primary_id="a", qr_payload="a", source_app="snipeit")
    b = LabelData(title="b", primary_id="b", qr_payload="b", source_app="snipeit")
    # With frozen=True we cannot append, but we can still verify the lists are distinct objects.
    assert a.secondary is not b.secondary
