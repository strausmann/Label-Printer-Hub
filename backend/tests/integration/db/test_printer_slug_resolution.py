"""Repository-Tests für slug-Lookup und Slug-oder-UUID-Resolution."""

from __future__ import annotations

import pytest
from app.models.printer import Printer
from app.repositories import printers as printers_repo
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_get_by_slug_returns_printer(db_session: AsyncSession):
    p = Printer(name="Brother PT-P750W", slug="brother-p750w", model="PT-P750W", backend="ptouch")
    await printers_repo.create(db_session, p)

    found = await printers_repo.get_by_slug(db_session, "brother-p750w")
    assert found is not None
    assert found.id == p.id


@pytest.mark.asyncio
async def test_get_by_slug_returns_none_when_missing(db_session: AsyncSession):
    found = await printers_repo.get_by_slug(db_session, "does-not-exist")
    assert found is None


@pytest.mark.asyncio
async def test_resolve_by_slug_or_uuid_with_uuid(db_session: AsyncSession):
    p = Printer(name="X", slug="x", model="X", backend="mock")
    await printers_repo.create(db_session, p)

    found = await printers_repo.resolve_by_slug_or_uuid(db_session, str(p.id))
    assert found is not None
    assert found.id == p.id


@pytest.mark.asyncio
async def test_resolve_by_slug_or_uuid_with_slug(db_session: AsyncSession):
    p = Printer(name="Y", slug="my-printer", model="Y", backend="mock")
    await printers_repo.create(db_session, p)

    found = await printers_repo.resolve_by_slug_or_uuid(db_session, "my-printer")
    assert found is not None
    assert found.id == p.id


@pytest.mark.asyncio
async def test_resolve_by_slug_or_uuid_with_garbage(db_session: AsyncSession):
    found = await printers_repo.resolve_by_slug_or_uuid(db_session, "nonexistent")
    assert found is None
