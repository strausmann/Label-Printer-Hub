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


def test_template_qr_rejects_zero_size() -> None:
    with pytest.raises(ValueError, match="positive size"):
        LayoutElement(type="qr", x=0, y=0, size=0, data_field="qr_payload")


def test_template_text_rejects_zero_font_size() -> None:
    with pytest.raises(ValueError, match="positive font_size"):
        LayoutElement(type="text", x=0, y=0, field="title", font_size=0)


def test_template_app_accepts_known_string() -> None:
    """app is a plain str | None — no Literal gating at schema level."""
    t = TemplateSchema(
        id="t",
        name="t",
        app="snipeit",
        tape_mm=24,
        elements=[],
    )
    assert t.app == "snipeit"


def test_template_schema_is_frozen() -> None:
    """Templates are immutable after construction."""
    from pydantic_core import ValidationError

    template = TemplateSchema(id="t", name="t", app="snipeit", tape_mm=24, elements=[])
    with pytest.raises(ValidationError, match="frozen_instance"):
        template.name = "different"  # type: ignore[misc]


def test_template_elements_is_immutable() -> None:
    """elements is a tuple — appending must raise AttributeError, not silently mutate."""
    template = TemplateSchema(
        id="t",
        name="t",
        app="snipeit",
        tape_mm=24,
        elements=[LayoutElement(type="text", x=0, y=0, field="title", font_size=12)],
    )
    with pytest.raises(AttributeError):
        template.elements.append(  # type: ignore[attr-defined]
            LayoutElement(type="text", x=10, y=10, field="primary_id", font_size=12)
        )
    assert isinstance(template.elements, tuple)


def test_template_qr_rejects_negative_size() -> None:
    with pytest.raises(ValueError, match="positive size"):
        LayoutElement(type="qr", x=0, y=0, size=-10, data_field="qr_payload")


def test_template_text_rejects_negative_font_size() -> None:
    with pytest.raises(ValueError, match="positive font_size"):
        LayoutElement(type="text", x=0, y=0, field="title", font_size=-12)


def test_template_schema_has_schema_version_field_defaulting_to_1() -> None:
    """schema_version is a versioning hook for future YAML migrations."""
    t = TemplateSchema(
        id="x",
        name="X",
        app="snipeit",
        tape_mm=24,
        elements=(),
    )
    assert t.schema_version == 1


def test_template_schema_accepts_explicit_schema_version() -> None:
    t = TemplateSchema(
        id="x",
        name="X",
        app="snipeit",
        tape_mm=24,
        elements=(),
        schema_version=1,
    )
    assert t.schema_version == 1


def test_template_schema_app_allows_none_for_generic_templates() -> None:
    """app=None marks the template as generic — usable with any plugin."""
    t = TemplateSchema(
        id="qr-only-24mm",
        name="QR-Code only (24mm)",
        app=None,
        tape_mm=24,
        elements=(),
    )
    assert t.app is None


def test_template_schema_app_accepts_arbitrary_string() -> None:
    """Schema does not gate the integration name — the loader validates against the registry."""
    t = TemplateSchema(
        id="x",
        name="X",
        app="future_integration_not_yet_implemented",
        tape_mm=24,
        elements=(),
    )
    assert t.app == "future_integration_not_yet_implemented"
