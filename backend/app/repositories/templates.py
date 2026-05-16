"""Repository functions for the Template aggregate."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.template import Template


async def list_all(session: AsyncSession) -> list[Template]:
    result = await session.execute(select(Template).order_by(Template.key))
    return list(result.scalars())


async def get_by_key(session: AsyncSession, key: str) -> Template | None:
    result = await session.execute(
        select(Template).where(col(Template.key) == key)  # col() gives proper Column typing
    )
    return result.scalar_one_or_none()


async def upsert_seed(session: AsyncSession, templates: Iterable[Template]) -> int:
    """Idempotent: insert if key missing, update body if key exists with source='seed'.

    Does NOT touch source='user' rows even if their key matches.
    Returns count of rows touched.
    """
    touched = 0
    for tpl in templates:
        existing = await get_by_key(session, tpl.key)
        if existing is None:
            tpl.source = "seed"
            session.add(tpl)
            touched += 1
            continue
        if existing.source == "user":
            continue  # never overwrite user rows
        # Update seed row in place
        existing.name = tpl.name
        existing.app = tpl.app
        existing.printer_model = tpl.printer_model
        existing.tape_width_mm = tpl.tape_width_mm
        existing.definition = tpl.definition
        existing.schema_version = tpl.schema_version
        session.add(existing)
        touched += 1
    await session.commit()
    return touched


async def create_user_template(session: AsyncSession, template: Template) -> Template:
    template.source = "user"
    session.add(template)
    await session.commit()
    await session.refresh(template)
    return template
