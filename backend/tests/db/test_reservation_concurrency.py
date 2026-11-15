# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

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


async def test_a_burst_of_maximal_prints_does_not_starve_the_write_lock(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """R10-2: six parallel 50-page prints. The reservations are serialised by the write lock, so
    the last one waits for five holds; with a hold of 1.5 s that is more than ``busy_timeout``
    (5 s) and requests failed with ``database is locked``. The hold is a fraction of that now."""

    async def big() -> list[ReservedPage]:
        async with factory() as s:
            return await reserve(
                s,
                placements=[
                    PlacementRequest(
                        sheet_code=None,
                        new_sheet=NewSheetIn(KEY, None, "margin"),
                        count=10,
                    )
                    for _ in range(50)
                ],
                items=[ItemMeta("api", f"item {i}", None) for i in range(500)],
                expected=None,
                hw_margins_hmm=None,
                margin=MARGIN,
                required_type_key=None,
                actor="tester",
            )

    results = await asyncio.gather(*(big() for _ in range(6)), return_exceptions=True)

    failures = [r for r in results if isinstance(r, BaseException)]
    assert failures == []
    codes = [p.sheet_code for r in results if not isinstance(r, BaseException) for p in r]
    assert len(codes) == len(set(codes)) == 300  # every sheet got its own code


async def _timed_reserve_on_existing(
    factory: async_sessionmaker[AsyncSession], codes: list[str]
) -> float:
    import time

    async with factory() as s:
        t = time.perf_counter()
        await reserve(
            s,
            placements=[PlacementRequest(sheet_code=c, new_sheet=None, count=1) for c in codes],
            items=[ItemMeta("api", f"item {i}", None) for i in range(len(codes))],
            expected=None,
            hw_margins_hmm=None,
            margin=MARGIN,
            required_type_key=None,
            actor="tester",
        )
        return time.perf_counter() - t


async def test_the_lock_hold_does_not_grow_with_unrelated_queued_payloads(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """R11-1: the in-flight check read and decoded every queued payload of the hub for each
    existing sheet of a request, under the write lock. 200 unrelated queued jobs of about
    300 KB (60 MB, what one print key can queue) took the lock for tens of seconds. Only the
    jobs of the sheet are read now, by index, and only the two entries the rules look at."""
    import json
    from uuid import uuid4

    from app.models.job import Job

    # Fresh sheets for each run: a reservation without a job row makes the check answer at once.
    codes = [await new_sheet(factory, used=0, placement="margin") for _ in range(50)]
    more = [await new_sheet(factory, used=0, placement="margin") for _ in range(50)]
    quiet = await _timed_reserve_on_existing(factory, more)

    cell = {"label_data": {"title": "T" * 512, "secondary": ["S" * 512] * 10}}
    other_sheet = {
        "kind": "sheet_page",
        "detail": {
            "sheet_id": str(uuid4()),
            "margin_id": {"text": "x"},
            "feed_mark": {"x": 1},
            "cells": [cell] * 150,
        },
    }
    assert len(json.dumps(other_sheet)) > 250_000
    async with factory() as s:
        printer_id = uuid4()
        from app.models.printer import Printer

        s.add(
            Printer(
                id=printer_id,
                name="p",
                slug="p",
                model="m",
                backend="ipp",
                connection={"uri": "ipp://x.invalid/ipp"},
                enabled=True,
            )
        )
        await s.flush()
        for _ in range(200):
            s.add(Job(printer_id=printer_id, state="queued", payload=other_sheet))
        await s.commit()

    loaded = await _timed_reserve_on_existing(factory, codes)

    assert loaded < quiet * 3 + 0.5, (quiet, loaded)


async def test_fifty_placements_on_existing_sheets_hold_the_lock_briefly(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """The views of existing sheets were read one sheet at a time (about eight statements
    each) under the write lock: 1.4 s for 50 sheets. They are read in a fixed number of
    statements now."""
    codes = [await new_sheet(factory, used=0, placement="margin") for _ in range(50)]

    held = await _timed_reserve_on_existing(factory, codes)

    assert held < 0.5, held


async def test_a_burst_of_prints_onto_existing_sheets_does_not_starve_the_write_lock(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    sets = [
        [await new_sheet(factory, used=0, placement="margin") for _ in range(50)] for _ in range(6)
    ]

    results = await asyncio.gather(
        *(_timed_reserve_on_existing(factory, codes) for codes in sets), return_exceptions=True
    )

    assert [r for r in results if isinstance(r, BaseException)] == []
