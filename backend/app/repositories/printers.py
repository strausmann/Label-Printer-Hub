"""Repository functions for the Printer aggregate."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.printer import Printer


async def list_all(session: AsyncSession) -> list[Printer]:
    result = await session.execute(
        select(Printer).order_by(col(Printer.created_at))  # col() gives proper Column typing
    )
    return list(result.scalars())


async def get(session: AsyncSession, printer_id: UUID) -> Printer | None:
    return await session.get(Printer, printer_id)


async def get_by_name(session: AsyncSession, name: str) -> Printer | None:
    result = await session.execute(
        select(Printer).where(col(Printer.name) == name)  # col() gives proper Column typing
    )
    return result.scalar_one_or_none()


async def create(session: AsyncSession, printer: Printer) -> Printer:
    session.add(printer)
    await session.commit()
    await session.refresh(printer)
    return printer


async def get_by_slug(session: AsyncSession, slug: str) -> Printer | None:
    """Lookup nach slug. None wenn nicht vorhanden."""
    result = await session.execute(
        select(Printer).where(col(Printer.slug) == slug)
    )
    return result.scalar_one_or_none()


async def resolve_by_slug_or_uuid(session: AsyncSession, key: str) -> Printer | None:
    """Akzeptiert Slug-String ODER UUID-String. UUID hat Vorrang (Performance)."""
    try:
        uuid_obj = UUID(key)
        printer = await get(session, uuid_obj)
        if printer is not None:
            return printer
    except ValueError:
        pass
    return await get_by_slug(session, key)
