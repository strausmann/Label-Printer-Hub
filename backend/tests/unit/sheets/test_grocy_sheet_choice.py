# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""``choose_grocy_sheet``: which sheet a Grocy label goes to (#281, R-281-15).

Among the type's active sheets with a free cell, all versions counted, the one with the fewest
free cells; equal counts go by ``(len(code), code)``, as on the print page. ``None``: no sheet
has room, a new one is opened.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest_asyncio
from app.models.sheet import Sheet, SheetCell
from app.sheets import sheet_service as ss
from app.sheets import type_service as ts
from app.sheets.geometry import Geometry
from app.sheets.grocy_sheet import choose_grocy_sheet
from app.sheets.sheet_service import MarkedCell
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# 2 x 5 = 10 cells: small, so "free n" is easy to set up.
G10 = Geometry("A4", 21000, 29700, 4570, 2120, 2, 5, 4850, 2120, 2150, 840, None, "rectangle")
KEY = "grocy-t10"
OTHER = "grocy-other"


def _fields(key: str, prefix: str) -> ts.TypeFields:
    return ts.TypeFields(key, prefix, "Acme", ["G-1"], None, None)


@pytest_asyncio.fixture
async def session(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as s:
        await ts.create_type(s, _fields(KEY, "GT"), G10, actor="t")
        await ts.create_type(s, _fields(OTHER, "GO"), G10, actor="t")
        yield s


async def _sheet(session: AsyncSession, *, free: int, key: str = KEY) -> str:
    total = G10.cols * G10.rows
    sheet = await ss.create_sheet(
        session,
        type_key=key,
        version=None,
        id_placement="manual",
        used_cells=[MarkedCell(n) for n in range(1, total - free + 1)],
        note=None,
        actor="t",
    )
    return sheet.code


async def test_fewest_free_wins(session: AsyncSession) -> None:
    await _sheet(session, free=3)  # A
    b = await _sheet(session, free=1)  # B
    await _sheet(session, free=0)  # C: full
    d = await _sheet(session, free=10)  # D: discarded below
    await ss.discard_sheet(session, d, actor="t")
    await _sheet(session, free=1, key=OTHER)  # E: another type

    assert await choose_grocy_sheet(session, KEY) == b


async def test_tie_goes_to_code_order(session: AsyncSession) -> None:
    codes = [await _sheet(session, free=0) for _ in range(10)]
    second, tenth = codes[1], codes[9]
    assert (len(second), second) < (len(tenth), tenth)
    # Free one cell on the tenth sheet first, then on the second: order of creation must not
    # decide, the code does.
    for code in (tenth, second):
        sheet = (await session.execute(select(Sheet).where(Sheet.code == code))).scalar_one()
        cell = await session.get(SheetCell, (sheet.id, 10))
        assert cell is not None
        await session.delete(cell)
        await session.commit()

    assert await choose_grocy_sheet(session, KEY) == second


async def test_unconfirmed_cells_are_not_free(session: AsyncSession) -> None:
    code = await _sheet(session, free=2)
    sheet = (await session.execute(select(Sheet).where(Sheet.code == code))).scalar_one()
    session.add_all(
        SheetCell(sheet_id=sheet.id, cell_no=n, state=state, job_id=uuid4(), source="api")
        for n, state in ((9, "unconfirmed"), (10, "reserved"))
    )
    await session.commit()

    assert await choose_grocy_sheet(session, KEY) is None


async def test_older_version_counts(session: AsyncSession) -> None:
    old = await _sheet(session, free=4)  # pinned to version 1
    v2 = Geometry(**{**G10.__dict__, "rows": 6})
    await ts.add_version(session, KEY, v2, actor="t", change_note="v2")
    await _sheet(session, free=12)  # version 2, more free

    assert await choose_grocy_sheet(session, KEY) == old


async def test_no_sheet_is_none(session: AsyncSession) -> None:
    await _sheet(session, free=1, key=OTHER)

    assert await choose_grocy_sheet(session, KEY) is None
    assert await choose_grocy_sheet(session, "no-such-type") is None


async def test_excluded_code_is_skipped(session: AsyncSession) -> None:
    """Review I-2: the re-choice never returns the sheet the first try was refused on."""
    refused = await _sheet(session, free=1)
    other = await _sheet(session, free=3)

    assert await choose_grocy_sheet(session, KEY, exclude={refused}) == other
    assert await choose_grocy_sheet(session, KEY, exclude={refused, other}) is None
