"""Repository for ApiKey aggregate — Phase 7c app-side authentication."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.api_key import ApiKey


async def create(session: AsyncSession, key: ApiKey) -> ApiKey:
    """Insert a new ApiKey row and return the persisted instance."""
    session.add(key)
    await session.commit()
    await session.refresh(key)
    return key


async def get(session: AsyncSession, key_id: UUID) -> ApiKey | None:
    """Return the ApiKey row for ``key_id``, or ``None`` if not found."""
    return await session.get(ApiKey, key_id)


async def get_by_prefix(session: AsyncSession, prefix: str) -> ApiKey | None:
    """Return the first ApiKey whose ``key_prefix`` matches ``prefix``."""
    stmt = select(ApiKey).where(col(ApiKey.key_prefix) == prefix).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_active(session: AsyncSession) -> list[ApiKey]:
    """Return all enabled, non-expired ApiKey rows."""
    now = datetime.now(UTC)
    stmt = (
        select(ApiKey)
        .where(col(ApiKey.enabled).is_(True))
        .where(
            (col(ApiKey.expires_at).is_(None)) | (col(ApiKey.expires_at) > now)
        )
        .order_by(col(ApiKey.created_at))
    )
    result = await session.execute(stmt)
    return list(result.scalars())


async def revoke(session: AsyncSession, key_id: UUID) -> ApiKey | None:
    """Set ``enabled = False`` on the key. Returns the updated key or None if not found."""
    key = await session.get(ApiKey, key_id)
    if key is None:
        return None
    key.enabled = False
    session.add(key)
    await session.commit()
    await session.refresh(key)
    return key


async def update_last_used(session: AsyncSession, key_id: UUID, *, ip: str) -> ApiKey | None:
    """Update ``last_used_at`` and ``last_used_ip`` for a key."""
    key = await session.get(ApiKey, key_id)
    if key is None:
        return None
    key.last_used_at = datetime.now(UTC)
    key.last_used_ip = ip
    session.add(key)
    await session.commit()
    await session.refresh(key)
    return key
