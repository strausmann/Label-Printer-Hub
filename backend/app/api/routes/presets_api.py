"""JSON-CRUD-API für Layout-Presets (Phase 1k.3, Refs #104).

Routes
------
GET    /api/v1/presets            — Liste (require_read)
POST   /api/v1/presets            — Anlegen 201 (require_print)
GET    /api/v1/presets/{id}       — Einzeln 200/404 (require_read)
PUT    /api/v1/presets/{id}       — Update 200/404/409/422 (require_print)
DELETE /api/v1/presets/{id}       — Löschen 204/404 (require_print)

Preview (preview.png) folgt in einem separaten Modul-Abschnitt.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_print, require_read
from app.db.session import get_session
from app.printer_backends.exceptions import (
    ContentTypeDataMismatchError,
    UnsupportedTapeError,
)
from app.schemas.preset import (
    PresetCreatePayload,
    PresetResponse,
    PresetUpdatePayload,
)
from app.services.preset_service import (
    DuplicatePresetNameError,
    PresetNotFoundError,
    PresetService,
)

router = APIRouter(prefix="/api/v1/presets", tags=["presets"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ReadAuthDep = Annotated[AuthContext, Depends(require_read)]
WriteAuthDep = Annotated[AuthContext, Depends(require_print)]


def _map_validation_error(exc: Exception) -> HTTPException:
    """Domain-Fehler auf HTTP-Statuscodes mappen."""
    if isinstance(exc, UnsupportedTapeError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    if isinstance(exc, ContentTypeDataMismatchError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    if isinstance(exc, DuplicatePresetNameError):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    raise exc  # pragma: no cover — unerwarteter Typ


@router.get("", response_model=list[PresetResponse])
async def list_presets(session: SessionDep, _auth: ReadAuthDep) -> list[PresetResponse]:
    """Alle gespeicherten Presets zurückgeben."""
    presets = await PresetService(session).list_all()
    return [PresetResponse.model_validate(p) for p in presets]


@router.post("", response_model=PresetResponse, status_code=status.HTTP_201_CREATED)
async def create_preset(
    payload: PresetCreatePayload, session: SessionDep, _auth: WriteAuthDep
) -> PresetResponse:
    """Neues Preset anlegen — validiert Tape + ContentType-Pflichtfelder."""
    try:
        preset = await PresetService(session).create(payload)
    except (UnsupportedTapeError, ContentTypeDataMismatchError, DuplicatePresetNameError) as exc:
        raise _map_validation_error(exc) from exc
    return PresetResponse.model_validate(preset)


@router.get("/{preset_id}", response_model=PresetResponse)
async def get_preset(preset_id: UUID, session: SessionDep, _auth: ReadAuthDep) -> PresetResponse:
    """Einzelnes Preset per ID abrufen — 404 wenn nicht gefunden."""
    try:
        preset = await PresetService(session).get(preset_id)
    except PresetNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return PresetResponse.model_validate(preset)


@router.put("/{preset_id}", response_model=PresetResponse)
async def update_preset(
    preset_id: UUID,
    payload: PresetUpdatePayload,
    session: SessionDep,
    _auth: WriteAuthDep,
) -> PresetResponse:
    """Preset aktualisieren (PUT mit optionalen Feldern — nur gesetzte Felder werden übernommen)."""
    try:
        preset = await PresetService(session).update(preset_id, payload)
    except PresetNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (UnsupportedTapeError, ContentTypeDataMismatchError, DuplicatePresetNameError) as exc:
        raise _map_validation_error(exc) from exc
    return PresetResponse.model_validate(preset)


@router.delete("/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_preset(preset_id: UUID, session: SessionDep, _auth: WriteAuthDep) -> Response:
    """Preset löschen — 204 bei Erfolg, 404 wenn nicht gefunden."""
    try:
        await PresetService(session).delete(preset_id)
    except PresetNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
