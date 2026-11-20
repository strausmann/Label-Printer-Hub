# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""#215: the ID cell is checked again once the reservation has decided it.

The dry plan that the per-item check ran on can differ from the reservation: another job that
holds the sheet's ID cell is released while the item lookups run, and the reservation then puts
the hub's own label into a cell the plan never checked.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import app.models  # noqa: F401
import pytest
import pytest_asyncio
from app.models.print_batch import PrintBatch
from app.models.sheet import Sheet, SheetCell
from app.sheets import type_service as ts
from app.sheets.errors import IdCellContentMismatchError
from app.sheets.geometry import Geometry
from app.sheets.sheet_service import HUB_SOURCE, ID_CELL_PURPOSE
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.unit.sheets.test_print_service_preview import (
    FakeLookup,
    grocy,
    make_printer,
    make_sheet,
    on,
    record,
    req,
)
from tests.unit.sheets.test_print_service_print import FakeQueue, run_print

KEY = "recheck-600"
# Room for a line of text, but not for the short-URL symbol of the ID label (cf. #210).
SMALL = Geometry("A4", 21000, 29700, 600, 600, 2, 2, 700, 700, 1500, 2000, None, "rectangle")


@pytest_asyncio.fixture
async def factory(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    async with async_session_factory() as s:
        await ts.create_type(
            s, ts.TypeFields(KEY, "RC1", None, ["RC1"], None, True), SMALL, actor="t"
        )
    yield async_session_factory


class ReleasingLookup(FakeLookup):
    """Frees the cell another job holds for the sheet ID while the lookups run."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        super().__init__()
        self._factory = factory

    async def lookup(self, source_app: str, identifier: str) -> Any:
        async with self._factory() as s:
            await s.execute(delete(SheetCell))
            await s.commit()
        return await super().lookup(source_app, identifier)


async def test_id_cell_checked_after_a_replan(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as s:
        printer = await make_printer(s, record(dpis=[300]))
        code = await make_sheet(s, key=KEY)
        sheet = (await s.execute(select(Sheet))).scalar_one()
        sheet.id_placement = "cell"  # a sheet type with the ID in a cell
        # Another job holds the ID cell: the dry plan gives this run none, so nothing checks it.
        s.add(
            SheetCell(
                sheet_id=sheet.id,
                cell_no=1,
                state="reserved",
                source=HUB_SOURCE,
                purpose=ID_CELL_PURPOSE,
                job_id=uuid4(),
            )
        )
        await s.commit()
    queue = FakeQueue()

    with pytest.raises(IdCellContentMismatchError) as refused:
        await run_print(
            factory,
            printer,
            req([grocy(1, _text())], [on(code)]),
            queue=queue,
            lookup=ReleasingLookup(factory),
        )

    assert refused.value.detail == {"cell": "id", "missing_fields": ["qr_payload"]}
    assert queue.calls == 0
    async with factory() as s:
        assert (await s.execute(select(func.count()).select_from(SheetCell))).scalar_one() == 0
        assert (await s.execute(select(func.count()).select_from(PrintBatch))).scalar_one() == 0


def _text() -> Any:
    from app.schemas.content_type import ContentType

    return ContentType.TEXT_TWO_LINES
