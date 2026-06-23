"""Tests für PresetService + Preset-Schemas (Phase 1k.3, Refs #104)."""

from __future__ import annotations

from uuid import uuid4

import app.models  # noqa: F401 — registriert alle Models
import pytest
import pytest_asyncio
from app.db.engine import _apply_pragmas
from app.printer_backends.exceptions import (
    ContentTypeDataMismatchError,
    UnsupportedTapeError,
)
from app.schemas.content_type import ContentType
from app.schemas.preset import PresetCreatePayload, PresetUpdatePayload
from app.services.preset_service import (
    DuplicatePresetNameError,
    PresetNotFoundError,
    PresetService,
)
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel


@pytest_asyncio.fixture
async def session():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(eng.sync_engine, "connect", _apply_pragmas)
    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False)
    async with factory() as s:
        yield s
    await eng.dispose()


# ---------------------------------------------------------------------------
# Schema-Tests (aus Task 4)
# ---------------------------------------------------------------------------


def test_create_payload_accepts_content_type_enum():
    payload = PresetCreatePayload(
        name="Schublade A",
        content_type=ContentType.QR_THREE_LINES,
        tape_mm=12,
        field_values={"primary_id": "A1", "title": "Schrauben",
                      "qr_payload": "x", "secondary": ["M3"]},
    )
    assert payload.content_type == ContentType.QR_THREE_LINES
    assert payload.tape_mm == 12


def test_create_payload_rejects_empty_name():
    with pytest.raises(ValidationError):
        PresetCreatePayload(name="", content_type=ContentType.QR_ONLY, tape_mm=12)


# ---------------------------------------------------------------------------
# Service-Tests (TDD Phase 1k.3, Step 1 — Refs #104)
# ---------------------------------------------------------------------------


def _valid_three_line_fields() -> dict:
    return {"primary_id": "A1", "title": "Schrauben",
            "qr_payload": "https://x", "secondary": ["M3"]}


@pytest.mark.asyncio
async def test_create_persists_and_returns(session):
    svc = PresetService(session)
    preset = await svc.create(PresetCreatePayload(
        name="Schublade A", content_type=ContentType.QR_THREE_LINES,
        tape_mm=12, field_values=_valid_three_line_fields()))
    assert preset.id is not None
    assert preset.content_type == "qr_three_lines"


@pytest.mark.asyncio
async def test_create_rejects_unsupported_tape(session):
    svc = PresetService(session)
    with pytest.raises(UnsupportedTapeError):
        await svc.create(PresetCreatePayload(
            name="Bad Tape", content_type=ContentType.QR_ONLY,
            tape_mm=999, field_values={"qr_payload": "x"}))


@pytest.mark.asyncio
async def test_create_rejects_missing_required_fields(session):
    svc = PresetService(session)
    with pytest.raises(ContentTypeDataMismatchError):
        await svc.create(PresetCreatePayload(
            name="Missing", content_type=ContentType.QR_THREE_LINES,
            tape_mm=12, field_values={"primary_id": "A1"}))  # title/qr/secondary fehlen


@pytest.mark.asyncio
async def test_create_rejects_duplicate_name_case_insensitive(session):
    svc = PresetService(session)
    await svc.create(PresetCreatePayload(
        name="Schublade A", content_type=ContentType.QR_ONLY,
        tape_mm=12, field_values={"qr_payload": "x"}))
    with pytest.raises(DuplicatePresetNameError):
        await svc.create(PresetCreatePayload(
            name="schublade a", content_type=ContentType.QR_ONLY,
            tape_mm=12, field_values={"qr_payload": "x"}))


@pytest.mark.asyncio
async def test_update_patches_name(session):
    svc = PresetService(session)
    created = await svc.create(PresetCreatePayload(
        name="Alt", content_type=ContentType.QR_ONLY,
        tape_mm=12, field_values={"qr_payload": "x"}))
    updated = await svc.update(created.id, PresetUpdatePayload(name="Neu"))
    assert updated.name == "Neu"


@pytest.mark.asyncio
async def test_update_missing_raises_not_found(session):
    svc = PresetService(session)
    with pytest.raises(PresetNotFoundError):
        await svc.update(uuid4(), PresetUpdatePayload(name="X"))


@pytest.mark.asyncio
async def test_delete_missing_raises_not_found(session):
    svc = PresetService(session)
    with pytest.raises(PresetNotFoundError):
        await svc.delete(uuid4())


@pytest.mark.asyncio
async def test_delete_removes(session):
    svc = PresetService(session)
    created = await svc.create(PresetCreatePayload(
        name="Weg", content_type=ContentType.QR_ONLY,
        tape_mm=12, field_values={"qr_payload": "x"}))
    await svc.delete(created.id)
    with pytest.raises(PresetNotFoundError):
        await svc.get(created.id)


@pytest.mark.asyncio
async def test_update_rejects_incompatible_content_type_change(session):
    svc = PresetService(session)
    created = await svc.create(PresetCreatePayload(
        name="Only QR", content_type=ContentType.QR_ONLY,
        tape_mm=12, field_values={"qr_payload": "x"}))
    with pytest.raises(ContentTypeDataMismatchError):
        await svc.update(created.id, PresetUpdatePayload(
            content_type=ContentType.QR_THREE_LINES))


@pytest.mark.asyncio
async def test_update_rejects_duplicate_name_case_insensitive(session):
    svc = PresetService(session)
    await svc.create(PresetCreatePayload(
        name="Bestehend", content_type=ContentType.QR_ONLY,
        tape_mm=12, field_values={"qr_payload": "x"}))
    other = await svc.create(PresetCreatePayload(
        name="Anderer", content_type=ContentType.QR_ONLY,
        tape_mm=12, field_values={"qr_payload": "x"}))
    with pytest.raises(DuplicatePresetNameError):
        await svc.update(other.id, PresetUpdatePayload(name="bestehend"))
