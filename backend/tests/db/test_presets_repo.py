"""Tests for the presets repository — FK enforcement + nullable printer_id."""
from uuid import uuid4

import pytest
import sqlalchemy.exc

from app.models.preset import Preset
from app.models.printer import Printer
from app.models.template import Template
from app.repositories import presets, printers, templates


def _printer() -> Printer:
    return Printer(
        name="test-printer",
        model="pt-series",
        backend="ptouch",
        connection={"interface": "usb"},
    )


def _template() -> Template:
    return Template(
        key="test-label",
        name="Test Label",
        printer_model="pt-series",
        tape_width_mm=12,
        definition={"elements": []},
        source="seed",
    )


@pytest.mark.asyncio
async def test_create_with_template_required(session):
    """Creates a Template then a Preset referencing it; asserts both columns populated."""
    tpl = await templates.create_user_template(session, _template())
    p = await printers.create(session, _printer())

    preset = Preset(
        name="office-label",
        printer_id=p.id,
        template_id=tpl.id,
        field_values={"greeting": "Hello"},
    )
    created = await presets.create(session, preset)

    assert created.id is not None
    assert created.template_id == tpl.id
    assert created.printer_id == p.id
    assert created.field_values == {"greeting": "Hello"}

    fetched = await presets.get(session, created.id)
    assert fetched is not None
    assert fetched.name == "office-label"


@pytest.mark.asyncio
async def test_printer_id_optional(session):
    """Preset with printer_id=None round-trips fine."""
    tpl = await templates.create_user_template(session, _template())

    preset = Preset(
        name="no-printer-preset",
        printer_id=None,
        template_id=tpl.id,
        field_values={"line1": "Hi"},
    )
    created = await presets.create(session, preset)

    assert created.id is not None
    assert created.printer_id is None
    assert created.template_id == tpl.id

    fetched = await presets.get(session, created.id)
    assert fetched is not None
    assert fetched.printer_id is None


@pytest.mark.asyncio
async def test_fk_to_missing_template_fails(session):
    """FK enforcement: template_id referencing a non-existent UUID raises IntegrityError."""
    preset = Preset(
        name="orphan-preset",
        printer_id=None,
        template_id=uuid4(),  # does not exist in templates table
        field_values={},
    )
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        await presets.create(session, preset)
