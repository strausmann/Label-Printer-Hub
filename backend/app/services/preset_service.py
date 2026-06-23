"""PresetService — Validierung + CRUD für Layout-Presets (Phase 1k.3, Refs #104).

Presets speichern ein Layout (ContentType + Ziel-Band + Default-Feldwerte).
Der Service validiert gegen TAPE_GEOMETRY und die ContentType-Pflichtfelder,
bevor er ans Repository delegiert. Domain-Errors werden im Router auf
HTTP-Statuscodes gemappt.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.preset import Preset
from app.printer_backends.exceptions import (
    ContentTypeDataMismatchError,
    UnsupportedTapeError,
)
from app.repositories import presets as preset_repo
from app.schemas.content_type import ContentType
from app.schemas.preset import PresetCreatePayload, PresetUpdatePayload
from app.schemas.tape_geometry import TAPE_GEOMETRY
from app.services.layout_engine import LayoutEngine


class PresetNotFoundError(Exception):
    def __init__(self, preset_id: UUID) -> None:
        self.preset_id = preset_id
        super().__init__(f"Preset {preset_id} nicht gefunden")


class DuplicatePresetNameError(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Preset-Name {name!r} bereits vergeben")


def _validate_layout(
    content_type: ContentType, tape_mm: int, field_values: dict[str, object]
) -> None:
    """Tape + ContentType-Pflichtfelder prüfen. Wirft Domain-Errors bei Verstoß."""
    if tape_mm not in TAPE_GEOMETRY:
        raise UnsupportedTapeError(tape_mm=tape_mm)
    required = LayoutEngine.required_fields(content_type)
    missing = [
        f
        for f in required
        if (v := field_values.get(f)) is None
        or (hasattr(v, "__len__") and len(v) == 0)
    ]
    if missing:
        raise ContentTypeDataMismatchError(
            content_type=str(content_type), missing_fields=tuple(missing)
        )


class PresetService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> list[Preset]:
        return await preset_repo.list_all(self._session)

    async def get(self, preset_id: UUID) -> Preset:
        preset = await preset_repo.get(self._session, preset_id)
        if preset is None:
            raise PresetNotFoundError(preset_id)
        return preset

    async def create(self, payload: PresetCreatePayload) -> Preset:
        _validate_layout(payload.content_type, payload.tape_mm, payload.field_values)
        if await preset_repo.get_by_name(self._session, payload.name) is not None:
            raise DuplicatePresetNameError(payload.name)
        preset = Preset(
            name=payload.name,
            content_type=str(payload.content_type),
            tape_mm=payload.tape_mm,
            field_values=dict(payload.field_values),
            printer_id=payload.printer_id,
        )
        return await preset_repo.create(self._session, preset)

    async def update(self, preset_id: UUID, payload: PresetUpdatePayload) -> Preset:
        existing = await self.get(preset_id)
        merged_ct = payload.content_type or ContentType(existing.content_type)
        merged_tape = payload.tape_mm if payload.tape_mm is not None else existing.tape_mm
        merged_fields = (
            payload.field_values
            if payload.field_values is not None
            else existing.field_values
        )
        _validate_layout(merged_ct, merged_tape, merged_fields)
        if payload.name is not None and payload.name.lower() != existing.name.lower():
            clash = await preset_repo.get_by_name(self._session, payload.name)
            if clash is not None:
                raise DuplicatePresetNameError(payload.name)
        changes: dict[str, object] = {}
        if payload.name is not None:
            changes["name"] = payload.name
        if payload.content_type is not None:
            changes["content_type"] = str(payload.content_type)
        if payload.tape_mm is not None:
            changes["tape_mm"] = payload.tape_mm
        if payload.field_values is not None:
            changes["field_values"] = dict(payload.field_values)
        if "printer_id" in payload.model_fields_set:
            changes["printer_id"] = payload.printer_id
        updated = await preset_repo.update(self._session, preset_id, **changes)
        if updated is None:  # pragma: no cover — get() oben garantiert Existenz
            raise PresetNotFoundError(preset_id)
        return updated

    async def delete(self, preset_id: UUID) -> None:
        ok = await preset_repo.delete(self._session, preset_id)
        if not ok:
            raise PresetNotFoundError(preset_id)
