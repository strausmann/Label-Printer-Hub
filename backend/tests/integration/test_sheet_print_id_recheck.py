# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""#215: the ID cell is checked again once the reservation has decided it.

The dry plan that the per-item check ran on can differ from the reservation: another job that
holds the sheet's ID cell is released while the item lookups run, and the reservation then puts
the hub's own label into a cell the plan never checked.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import app.models  # noqa: F401
import pytest
import pytest_asyncio
from app.models.print_batch import PrintBatch
from app.models.sheet import Sheet, SheetCell
from app.schemas.content_type import ContentType
from app.sheets import print_service
from app.sheets import type_service as ts
from app.sheets.errors import IdCellContentMismatchError
from app.sheets.geometry import Geometry
from app.sheets.reservation import NewSheetIn
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


async def _held_sheet(factory: async_sessionmaker[AsyncSession]) -> tuple[Any, str]:
    """A ``cell`` sheet whose ID cell another job holds: the dry plan gives a run no ID cell."""
    async with factory() as s:
        printer = await make_printer(s, record(dpis=[300]))
        code = await make_sheet(s, key=KEY)
        sheet = (await s.execute(select(Sheet))).scalar_one()
        sheet.id_placement = "cell"  # a sheet type with the ID in a cell
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
    return printer, code


async def _no_reserved_cells(factory: async_sessionmaker[AsyncSession]) -> int:
    async with factory() as s:
        q = select(func.count()).select_from(SheetCell).where(SheetCell.state == "reserved")
        return int((await s.execute(q)).scalar_one())


async def test_id_cell_checked_after_a_replan(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    printer, code = await _held_sheet(factory)
    queue = FakeQueue()

    with pytest.raises(IdCellContentMismatchError) as refused:
        await run_print(
            factory,
            printer,
            req([grocy(1, ContentType.TEXT_TWO_LINES)], [on(code)]),
            queue=queue,
            lookup=ReleasingLookup(factory),
        )

    assert refused.value.detail == {"cell": "id", "missing_fields": ["qr_payload"]}
    assert queue.calls == 0
    async with factory() as s:
        assert (await s.execute(select(func.count()).select_from(SheetCell))).scalar_one() == 0
        assert (await s.execute(select(func.count()).select_from(PrintBatch))).scalar_one() == 0


@pytest.mark.parametrize("failure", [asyncio.CancelledError(), RuntimeError("boom")])
async def test_a_failing_recheck_does_not_leak_reservations(
    factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
) -> None:
    """A cancel, or any error but the mismatch, during the threaded check frees the cells."""
    printer, code = await _held_sheet(factory)

    def broken(*_a: Any, **_k: Any) -> None:
        raise failure

    monkeypatch.setattr(print_service, "check_id_cell_fits", broken)

    with pytest.raises(type(failure)):
        await run_print(
            factory,
            printer,
            req([grocy(1, ContentType.TEXT_TWO_LINES)], [on(code)]),
            queue=FakeQueue(),
            lookup=ReleasingLookup(factory),
        )

    assert await _no_reserved_cells(factory) == 0


async def test_id_label_sheet_keeps_its_code_when_the_recheck_refuses(
    factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sheet exists after the reservation committed: the 422 carries its code."""
    async with factory() as s:
        printer = await make_printer(s, record(dpis=[300]))
    calls = 0

    def second_call_refuses(*_args: Any, **_kwargs: Any) -> None:  # the hint check passes
        nonlocal calls
        calls += 1
        if calls == 2:  # the real code no longer fits where the hint did
            raise IdCellContentMismatchError(("qr_payload",))

    monkeypatch.setattr(print_service, "check_id_cell_fits", second_call_refuses)
    new = NewSheetIn(type_key=KEY, version=None, id_placement="cell")

    with pytest.raises(IdCellContentMismatchError) as refused:
        await print_service.create_sheet_with_id_label(
            factory,
            printer=printer,
            tray=None,
            new=new,
            queue=FakeQueue(),
            actor="t",
            api_key_id=None,
            source_ip=None,
            language="en",
        )

    assert calls == 2
    assert refused.value.detail is not None
    assert refused.value.detail["sheet_code"] == "RC1-0001"
    assert await _no_reserved_cells(factory) == 0
