"""#277: a sheet print run plans at most one sheet; the items that do not fit are left out.

The cart is not limited. One run takes the free cells of one sheet, the first items in order; the
response says how many were placed and how many remain (they stay in the cart).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import app.models  # noqa: F401
import pytest
import pytest_asyncio
from app.sheets import type_service as ts
from app.sheets.errors import InsufficientCellsError, PreviewTooLargeError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.unit.sheets.test_print_service_preview import (
    G48,
    KEY,
    FakeLookup,
    fresh,
    grocy,
    make_printer,
    make_sheet,
    on,
    raw,
    record,
    req,
    run_preview,
)
from tests.unit.sheets.test_print_service_print import FakeQueue, run_print

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def factory(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    async with async_session_factory() as s:
        await ts.create_type(
            s, ts.TypeFields(KEY, "L4736", "Avery", ["L4736REV-25"], None, None), G48, actor="t"
        )
    yield async_session_factory


@pytest_asyncio.fixture
async def session(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with factory() as s:
        yield s


def _new_items(page: object) -> list[int | None]:
    return [c.item_index for c in page.cells if c.state == "new"]  # type: ignore[attr-defined]


async def test_preview_cells_exactly_full_places_everything(session: AsyncSession) -> None:
    printer = await make_printer(session, record())
    code = await make_sheet(session, used=46)  # 48 cells, 2 free

    out = await run_preview(session, printer, req([raw(0), raw(1)], [on(code)]))

    assert (out.placed, out.remaining) == (2, 0)
    assert len(out.pages) == 1 and _new_items(out.pages[0]) == [0, 1]


async def test_preview_one_more_item_than_free_cells_leaves_the_last_out(
    session: AsyncSession,
) -> None:
    printer = await make_printer(session, record())
    code = await make_sheet(session, used=46)
    lookup = FakeLookup()

    out = await run_preview(
        session, printer, req([grocy(0), grocy(1), grocy(2)], [on(code)]), lookup=lookup
    )

    assert (out.placed, out.remaining) == (2, 1)
    assert len(out.pages) == 1 and _new_items(out.pages[0]) == [0, 1]
    # The item that does not fit is not looked up: it is not part of this run.
    assert [identifier for _, identifier in lookup.calls] == ["0", "1"]


async def test_preview_never_plans_more_than_one_sheet(session: AsyncSession) -> None:
    printer = await make_printer(session, record())

    out = await run_preview(session, printer, req([raw(i) for i in range(60)], [fresh()]))

    assert len(out.pages) == 1
    assert (out.placed, out.remaining) == (48, 12)
    assert _new_items(out.pages[0]) == list(range(48))
    assert len(out.expected_cells) == 1 and len(out.expected_cells[0].cells) == 48


async def test_preview_refuses_a_second_sheet(session: AsyncSession) -> None:
    printer = await make_printer(session, record())
    lookup = FakeLookup()

    with pytest.raises(PreviewTooLargeError) as err:
        await run_preview(
            session,
            printer,
            req([grocy(0), grocy(1)], [fresh(count=1), fresh(count=1)]),
            lookup=lookup,
        )

    assert err.value.detail == {"pages": 2, "max": 1}
    assert lookup.calls == []


async def test_preview_a_count_larger_than_the_sheet_is_capped(session: AsyncSession) -> None:
    printer = await make_printer(session, record())
    code = await make_sheet(session, used=47)

    out = await run_preview(session, printer, req([raw(0), raw(1)], [on(code, count=2)]))

    assert (out.placed, out.remaining) == (1, 1)


async def test_preview_chosen_cells_take_the_first_items(session: AsyncSession) -> None:
    printer = await make_printer(session, record())
    code = await make_sheet(session)

    out = await run_preview(
        session, printer, req([raw(0), raw(1), raw(2)], [on(code, cells=[5, 9])])
    )

    assert (out.placed, out.remaining) == (2, 1)
    new = {c.cell: c.item_index for c in out.pages[0].cells if c.state == "new"}
    assert new == {5: 0, 9: 1}


async def test_preview_a_full_sheet_is_still_refused(session: AsyncSession) -> None:
    printer = await make_printer(session, record())
    code = await make_sheet(session, used=48)

    with pytest.raises(InsufficientCellsError):
        await run_preview(session, printer, req([raw(0)], [on(code)]))


async def test_print_places_the_first_items_and_reports_the_rest(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    printer = await make_printer(session, record())
    code = await make_sheet(session, used=46)
    queue = FakeQueue()
    lookup = FakeLookup()

    out = await run_print(
        factory,
        printer,
        req([grocy(0), grocy(1), grocy(2)], [on(code)]),
        queue=queue,
        lookup=lookup,
    )

    assert (out.placed, out.remaining) == (2, 1)
    (page,) = out.pages
    assert page.cells == [47, 48]
    assert [identifier for _, identifier in lookup.calls] == ["0", "1"]
    assert len(queue.payloads) == 1


async def test_print_refuses_a_second_sheet(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    printer = await make_printer(session, record())
    queue = FakeQueue()

    with pytest.raises(PreviewTooLargeError):
        await run_print(
            factory, printer, req([raw(0), raw(1)], [fresh(count=1), fresh()]), queue=queue
        )

    assert queue.payloads == []


async def test_print_cells_exactly_full(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    printer = await make_printer(session, record())
    code = await make_sheet(session, used=46)

    out = await run_print(factory, printer, req([raw(0), raw(1)], [on(code)]))

    assert (out.placed, out.remaining) == (2, 0)
    assert out.pages[0].cells == [47, 48]
