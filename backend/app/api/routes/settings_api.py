# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Runtime settings API (admin scope).

The request bodies are parsed by hand on purpose: FastAPI's default 422 body echoes the
offending ``input``, which for a settings update could be a secret (D5).
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.bounded_body import read_bounded
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_admin
from app.db.session import get_session
from app.schemas.settings_api import (
    IntegrationTestRequest,
    IntegrationTestResult,
    SettingsExport,
    SettingsUpdate,
    SettingView,
)
from app.settings_store import SETTINGS, SettingsError, SettingsStore
from app.settings_store.probes import probe_integration
from app.settings_store.registry import INTEGRATIONS

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
AdminDep = Annotated[AuthContext, Depends(require_admin)]

# The largest settings body is a handful of short values; 64 KiB matches the sheet type
# import limit and leaves ample room (R-281-3 Global Constraint: bounded reads only).
MAX_SETTINGS_BODY_BYTES = 65_536
_TOO_LARGE_RESPONSE: dict[int | str, dict[str, Any]] = {
    413: {"description": "Request body larger than 64 KiB."}
}

_BODY_EXTRA_UPDATE = {
    "requestBody": {
        "required": True,
        "content": {"application/json": {"schema": SettingsUpdate.model_json_schema()}},
    }
}
_BODY_EXTRA_TEST = {
    "requestBody": {
        "required": False,
        "content": {"application/json": {"schema": IntegrationTestRequest.model_json_schema()}},
    }
}


def _store(request: Request) -> SettingsStore:
    store: SettingsStore = request.app.state.settings_store
    return store


def _http(exc: SettingsError) -> HTTPException:
    code = status.HTTP_409_CONFLICT if exc.code == "setting_locked" else 422
    return HTTPException(
        status_code=code,
        detail={"error_code": exc.code, "error_message": str(exc), "keys": exc.keys},
    )


def _bad_body(message: str) -> HTTPException:
    return HTTPException(
        status_code=422, detail={"error_code": "invalid_body", "error_message": message}
    )


def _too_large() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        detail={
            "error_code": "body_too_large",
            "error_message": "The request body is larger than 64 KiB.",
        },
    )


async def _values_from_body(request: Request, *, required: bool) -> dict[str, Any]:
    raw = await read_bounded(request, MAX_SETTINGS_BODY_BYTES, _too_large)
    if not raw.strip():
        if required:
            raise _bad_body("a JSON body with a 'values' object is required")
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        raise _bad_body("the body is not valid JSON") from None
    values = data.get("values") if isinstance(data, dict) else None
    if values is None and not required and isinstance(data, dict) and not data:
        return {}
    if not isinstance(values, dict):
        raise _bad_body("the body must be an object with a 'values' object")
    return values


@router.get("", response_model=list[SettingView], summary="List settings")
async def list_settings(request: Request, _auth: AdminDep) -> list[SettingView]:
    return _store(request).describe()


@router.put(
    "",
    response_model=list[SettingView],
    summary="Update settings",
    openapi_extra=_BODY_EXTRA_UPDATE,
    responses=_TOO_LARGE_RESPONSE,
)
async def update_settings(
    request: Request, session: SessionDep, _auth: AdminDep
) -> list[SettingView]:
    values = await _values_from_body(request, required=True)
    store = _store(request)
    try:
        await store.set_many(session, values)
    except SettingsError as exc:
        raise _http(exc) from None
    return store.describe()


@router.get(
    "/export",
    summary="Export the non-secret, non-locked settings",
    responses={200: {"model": SettingsExport}},
)
async def export_settings(request: Request, _auth: AdminDep) -> Response:
    store = _store(request)
    data = {
        key: store.get(key)
        for key, d in SETTINGS.items()
        if d.kind != "secret" and not store.is_locked(key)
    }
    return Response(
        content=json.dumps(data, indent=2, sort_keys=True),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="labelyard-settings.json"'},
    )


@router.post(
    "/integrations/{name}/test",
    response_model=IntegrationTestResult,
    summary="Test an integration with unsaved form values",
    openapi_extra=_BODY_EXTRA_TEST,
    responses=_TOO_LARGE_RESPONSE,
)
async def test_integration(name: str, request: Request, _auth: AdminDep) -> IntegrationTestResult:
    if name not in INTEGRATIONS:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "not_found", "error_message": "unknown integration"},
        )
    form = await _values_from_body(request, required=False)
    try:
        url, secret, timeout = _store(request).resolve_probe(name, form)
    except SettingsError as exc:
        raise _http(exc) from None
    if not url:
        return IntegrationTestResult(ok=False, status=None, detail="no URL configured")
    ok, http_status, detail = await probe_integration(name, url=url, secret=secret, timeout=timeout)
    return IntegrationTestResult(ok=ok, status=http_status, detail=detail)
