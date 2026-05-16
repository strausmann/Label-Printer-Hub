"""Repository functions for the Printer aggregate."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.printer import Printer


async def list_all(session: AsyncSession) -> list[Printer]:
    result = await session.execute(select(Printer).order_by(Printer.created_at))
    return list(result.scalars())


async def get(session: AsyncSession, printer_id: UUID) -> Printer | None:
    return await session.get(Printer, printer_id)


async def get_by_name(session: AsyncSession, name: str) -> Printer | None:
    result = await session.execute(select(Printer).where(Printer.name == name))
    return result.scalar_one_or_none()


async def create(session: AsyncSession, printer: Printer) -> Printer:
    session.add(printer)
    await session.commit()
    await session.refresh(printer)
    return printer
