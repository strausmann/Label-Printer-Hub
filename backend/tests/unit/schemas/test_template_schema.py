import pytest
from app.schemas.template import LayoutElement, TemplateSchema


def test_template_with_qr_and_text() -> None:
    template = TemplateSchema(
        id="snipeit-asset-24mm",
        name="Snipe-IT 24mm",
        app="snipeit",
        tape_mm=24,
        elements=[
            LayoutElement(type="qr", x=0, y=0, size=256, data_field="qr_payload"),
            LayoutElement(type="text", x=270, y=10, field="title", font_size=24),
        ],
    )
    assert len(template.elements) == 2
    assert template.elements[0].type == "qr"


def test_template_qr_requires_data_field() -> None:
    """QR element without data_field must fail validation."""
    with pytest.raises(ValueError, match="data_field"):
        LayoutElement(type="qr", x=0, y=0, size=256)


def test_template_qr_requires_size() -> None:
    """QR element without size must fail validation."""
    with pytest.raises(ValueError, match="size"):
        LayoutElement(type="qr", x=0, y=0, data_field="qr_payload")


def test_template_text_requires_field() -> None:
    with pytest.raises(ValueError, match="field"):
        LayoutElement(type="text", x=0, y=0, font_size=24)


def test_template_text_requires_font_size() -> None:
    with pytest.raises(ValueError, match="font_size"):
        LayoutElement(type="text", x=0, y=0, field="title")


def test_template_app_must_be_one_of_known() -> None:
    with pytest.raises(ValueError):
        TemplateSchema(
            id="t",
            name="t",
            app="unknown",  # not in Literal
            tape_mm=24,
            elements=[],
        )


def test_template_schema_is_frozen() -> None:
    """Templates are immutable after construction."""
    from pydantic_core import ValidationError

    template = TemplateSchema(id="t", name="t", app="snipeit", tape_mm=24, elements=[])
    with pytest.raises(ValidationError, match="frozen_instance"):
        template.name = "different"  # type: ignore[misc]
