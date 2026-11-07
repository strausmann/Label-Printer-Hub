"""Reservations under contention on a real SQLite file in WAL mode (acceptance 12, C26).

In-memory SQLite has no second connection, so these tests use a temp file, the production
pragmas and one engine with several sessions racing through ``asyncio.gather``.
"""

from __future__ import annotations

import asyncio
import pathlib
from collections.abc import AsyncIterator
from typing import Any

import app.models  # noqa: F401 — registers all models with SQLModel.metadata
import pytest
import pytest_asyncio
from app.db.engine import _apply_pragmas
from app.models.sheet import SheetCell
from app.page_render.transform import Deviation
from app.sheets import reservation as rv
from app.sheets import sheet_service as ss
from app.sheets import type_service as ts
from app.sheets.errors import CellsTakenError
from app.sheets.geometry import Geometry
from app.sheets.planner import MarginContext
from app.sheets.reservation import ItemMeta, NewSheetIn, PlacementRequest, ReservedPage, reserve
from app.sheets.sheet_service import MarkedCell
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlmodel import SQLModel

G48 = Geometry(
    page_size="A4",
    page_w=21000,
    page_h=29700,
    label_w=4570,
    label_h=2120,
    cols=4,
    rows=12,
    pitch_x=4850,
    pitch_y=2120,
    margin_top=2150,
    margin_left=840,
    corner_radius=None,
    shape="rectangle",
)
KEY = "avery-l4736rev"
FIELDS = ts.TypeFields(
    key=KEY,
    prefix="L4736",
    vendor="Avery",
    product_codes=["L4736REV-25"],
    description=None,
    allow_qr=None,
)
MARGIN = MarginContext(
    deviation=Deviation(), scan_payload=lambda c: f"sheet:{c}", render_dpi=600, language=None
)


@pytest.fixture(autouse=True)
def no_replan(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """The write lock serialises the requests, so the IntegrityError re-plan is never needed.

    Without this the re-plan would rescue a missing lock and the tests would still pass.
    """
    taken: list[int] = []
    real = rv._InsertConflictError.__init__

    def counting(self: Any, *args: Any, **kwargs: Any) -> None:
        taken.append(1)
        real(self, *args, **kwargs)

    monkeypatch.setattr(rv._InsertConflictError, "__init__", counting)
    return taken


@pytest_asyncio.fixture
async def factory(tmp_path: pathlib.Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine: AsyncEngine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'hub.db'}")
    event.listen(engine.sync_engine, "connect", _apply_pragmas)  # WAL + busy_timeout
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        await ts.create_type(s, FIELDS, G48, actor="tester")
    yield maker
    await engine.dispose()


async def new_sheet(
    factory: async_sessionmaker[AsyncSession], used: int, placement: str = "manual"
) -> str:
    async with factory() as s:
        sheet = await ss.create_sheet(
            s,
            type_key=KEY,
            version=None,
            id_placement=placement,  # type: ignore[arg-type]
            used_cells=[MarkedCell(n) for n in range(1, used + 1)],
            note=None,
            actor="tester",
        )
        return sheet.code


async def one(
    factory: async_sessionmaker[AsyncSession], code: str, n: int, **placement: Any
) -> list[ReservedPage]:
    async with factory() as s:
        return await reserve(
            s,
            placements=[PlacementRequest(sheet_code=code, new_sheet=None, **placement)],
            items=[ItemMeta("api", f"item {i}", None) for i in range(n)],
            expected=None,
            hw_margins_hmm=None,
            margin=MARGIN,
            required_type_key=KEY,
            actor="tester",
        )


def cells_of(pages: list[ReservedPage]) -> set[int]:
    return {a.cell for p in pages for a in p.assignments}


async def test_parallel_first_free_never_overlap(
    factory: async_sessionmaker[AsyncSession], no_replan: list[int]
) -> None:
    for _ in range(20):
        code = await new_sheet(factory, used=8)
        a, b = await asyncio.gather(one(factory, code, 20), one(factory, code, 20))
        assert cells_of(a).isdisjoint(cells_of(b))
        assert cells_of(a) | cells_of(b) == set(range(9, 49))
        assert no_replan == []
        async with factory() as s:
            rows = (await s.execute(select(SheetCell))).scalars().all()
        # every cell of the sheet appears once: used ones and the 40 reserved ones
        assert len({(r.sheet_id, r.cell_no) for r in rows}) == len(rows)


async def test_parallel_explicit_vs_first_free(
    factory: async_sessionmaker[AsyncSession], no_replan: list[int]
) -> None:
    outcomes = set()
    for _ in range(20):
        code = await new_sheet(factory, used=8)
        results = await asyncio.gather(
            one(factory, code, 2, cells=[9, 10]),
            one(factory, code, 2),
            return_exceptions=True,
        )
        explicit, free = results
        if isinstance(explicit, CellsTakenError):
            assert explicit.detail == {"cells": [9, 10]}
            assert not isinstance(free, BaseException)
            assert cells_of(free) == {9, 10}
            outcomes.add("explicit_lost")
        else:
            assert not isinstance(explicit, BaseException) and not isinstance(free, BaseException)
            assert cells_of(explicit) == {9, 10}
            assert cells_of(free) == {11, 12}  # re-planned on the next free cells
            outcomes.add("explicit_won")
    assert outcomes  # either order is allowed; overlap never is
    assert no_replan == []


async def test_parallel_margin_id_is_drawn_once(
    factory: async_sessionmaker[AsyncSession], no_replan: list[int]
) -> None:
    """C26: no ``jobs`` row exists yet, the other request's reserved cells say it is in flight."""
    for _ in range(10):
        code = await new_sheet(factory, used=0, placement="margin")
        a, b = await asyncio.gather(one(factory, code, 2), one(factory, code, 2))
        assert [p.margin_id for p in a + b].count(True) == 1
        assert cells_of(a).isdisjoint(cells_of(b))
    assert no_replan == []


async def test_parallel_new_sheets_get_distinct_codes_and_counter_steps(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async def create(i: int) -> list[ReservedPage]:
        async with factory() as s:
            return await reserve(
                s,
                placements=[
                    PlacementRequest(None, NewSheetIn(KEY, None, "cell"), count=3),
                ],
                items=[ItemMeta("api", "x", None)] * 3,
                expected=None,
                hw_margins_hmm=None,
                margin=MARGIN,
                required_type_key=KEY,
                actor=f"client-{i}",
            )

    pages = [p for batch in await asyncio.gather(*(create(i) for i in range(6))) for p in batch]
    assert sorted(p.sheet_code for p in pages) == [f"L4736-{n:04d}" for n in range(1, 7)]
    assert all(p.id_cell == 1 for p in pages)
