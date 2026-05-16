"""Repository functions for the Preset aggregate."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.preset import Preset


async def list_all(session: AsyncSession) -> list[Preset]:
    result = await session.execute(select(Preset).order_by(Preset.created_at))
    return list(result.scalars())


async def get(session: AsyncSession, preset_id: UUID) -> Preset | None:
    return await session.get(Preset, preset_id)


async def create(session: AsyncSession, preset: Preset) -> Preset:
    session.add(preset)
    await session.commit()
    await session.refresh(preset)
    return preset


async def update(session: AsyncSession, preset_id: UUID, **changes) -> Preset | None:
    preset = await session.get(Preset, preset_id)
    if preset is None:
        return None
    for key, value in changes.items():
        setattr(preset, key, value)
    preset.updated_at = datetime.now(UTC)
    session.add(preset)
    await session.commit()
    await session.refresh(preset)
    return preset


async def delete(session: AsyncSession, preset_id: UUID) -> bool:
    preset = await session.get(Preset, preset_id)
    if preset is None:
        return False
    await session.delete(preset)
    await session.commit()
    return True
