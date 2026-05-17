"""REST CRUD endpoints for API key management — Phase 7c Step 8.

All endpoints require ``admin`` scope.

Routes
------
GET    /api/admin/api-keys          — list all keys (metadata only, no hashes/plaintexts)
POST   /api/admin/api-keys          — create key, returns plaintext ONCE in response
GET    /api/admin/api-keys/{id}     — single key metadata
PATCH  /api/admin/api-keys/{id}     — update enabled/rate_limit/notes
DELETE /api/admin/api-keys/{id}     — revoke key (sets enabled=False)
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import AuthContext
from app.auth.key_generator import generate_api_key
from app.auth.scope_deps import require_admin
from app.auth.verifier import invalidate_cache
from app.db.session import get_session
from app.models.api_key import ApiKey
from app.repositories import api_keys as api_keys_repo
from app.services.rate_limiter import _rate_limiter

router = APIRouter(prefix="/api/admin/api-keys", tags=["admin"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
AdminAuthDep = Annotated[AuthContext, Depends(require_admin)]


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class ApiKeyCreate(BaseModel):
    name: str
    scopes: list[str]
    allowed_printer_ids: list[str] = []
    rate_limit_per_minute: int = 60
    notes: str | None = None
    expires_at: str | None = None  # ISO-8601 string or null


class ApiKeyCreateResponse(BaseModel):
    """Returned ONCE on creation — includes plaintext. Never return again."""

    key_id: UUID
    plaintext: str
    prefix: str
    name: str
    scopes: list[str]


class ApiKeyRead(BaseModel):
    """Metadata-only view — no key_hash, no plaintext."""

    id: UUID
    name: str
    key_prefix: str
    scopes: list[str]
    allowed_printer_ids: list[str]
    rate_limit_per_minute: int
    enabled: bool
    created_at: str
    last_used_at: str | None
    last_used_ip: str | None
    expires_at: str | None
    notes: str | None


class ApiKeyPatch(BaseModel):
    enabled: bool | None = None
    rate_limit_per_minute: int | None = None
    notes: str | None = None
    allowed_printer_ids: list[str] | None = None


def _key_to_read(key: ApiKey) -> ApiKeyRead:
    return ApiKeyRead(
        id=key.id,
        name=key.name,
        key_prefix=key.key_prefix,
        scopes=key.scopes,
        allowed_printer_ids=key.allowed_printer_ids,
        rate_limit_per_minute=key.rate_limit_per_minute,
        enabled=key.enabled,
        created_at=key.created_at.isoformat() if key.created_at else "",
        last_used_at=key.last_used_at.isoformat() if key.last_used_at else None,
        last_used_ip=key.last_used_ip,
        expires_at=key.expires_at.isoformat() if key.expires_at else None,
        notes=key.notes,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[ApiKeyRead],
    summary="List all API keys",
    description="Returns metadata for all API keys. key_hash and plaintext are never included.",
)
async def list_api_keys(session: SessionDep, _auth: AdminAuthDep) -> list[ApiKeyRead]:
    result = await session.execute(__import__("sqlalchemy", fromlist=["select"]).select(ApiKey))
    keys = list(result.scalars())
    return [_key_to_read(k) for k in keys]


@router.post(
    "",
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new API key",
    description=(
        "Creates a new API key. The ``plaintext`` field in the response is the "
        "full key — it is shown ONCE and never stored. Copy it before closing "
        "this response. Subsequent GETs return only the prefix."
    ),
)
async def create_api_key(
    body: ApiKeyCreate,
    session: SessionDep,
    _auth: AdminAuthDep,
) -> ApiKeyCreateResponse:
    plaintext, prefix, hashed = generate_api_key()
    key = ApiKey(
        name=body.name,
        key_hash=hashed,
        key_prefix=prefix,
        scopes=body.scopes,
        allowed_printer_ids=body.allowed_printer_ids,
        rate_limit_per_minute=body.rate_limit_per_minute,
        notes=body.notes,
        enabled=True,
    )
    if body.expires_at:
        from datetime import datetime

        key.expires_at = datetime.fromisoformat(body.expires_at)

    created = await api_keys_repo.create(session, key)
    return ApiKeyCreateResponse(
        key_id=created.id,
        plaintext=plaintext,
        prefix=prefix,
        name=created.name,
        scopes=created.scopes,
    )


@router.get(
    "/{key_id}",
    response_model=ApiKeyRead,
    summary="Get API key metadata",
    description="Returns metadata for a single API key. key_hash and plaintext are never included.",
)
async def get_api_key(
    key_id: UUID,
    session: SessionDep,
    _auth: AdminAuthDep,
) -> ApiKeyRead:
    key = await api_keys_repo.get(session, key_id)
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key {key_id} not found",
        )
    return _key_to_read(key)


@router.patch(
    "/{key_id}",
    response_model=ApiKeyRead,
    summary="Update API key metadata",
    description=(
        "Update ``enabled``, ``rate_limit_per_minute``, ``notes``, or "
        "``allowed_printer_ids``. Cannot change scopes or the key value itself — "
        "revoke and recreate for that."
    ),
)
async def update_api_key(
    key_id: UUID,
    body: ApiKeyPatch,
    session: SessionDep,
    _auth: AdminAuthDep,
) -> ApiKeyRead:
    key = await api_keys_repo.get(session, key_id)
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key {key_id} not found",
        )
    if body.enabled is not None:
        key.enabled = body.enabled
    if body.rate_limit_per_minute is not None:
        key.rate_limit_per_minute = body.rate_limit_per_minute
    if body.notes is not None:
        key.notes = body.notes
    if body.allowed_printer_ids is not None:
        key.allowed_printer_ids = body.allowed_printer_ids

    session.add(key)
    await session.commit()
    await session.refresh(key)
    return _key_to_read(key)


@router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an API key",
    description=(
        "Sets ``enabled = False``. The key will be rejected on next use. "
        "The row is kept for audit purposes (jobs referencing this key_id "
        "remain intact)."
    ),
)
async def revoke_api_key(
    key_id: UUID,
    session: SessionDep,
    _auth: AdminAuthDep,
) -> None:
    key = await api_keys_repo.revoke(session, key_id)
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key {key_id} not found",
        )
    # Invalidate bcrypt cache so the key is rejected immediately
    invalidate_cache(key.key_hash)
    # Clear rate-limiter bucket
    _rate_limiter.reset(key_id)
