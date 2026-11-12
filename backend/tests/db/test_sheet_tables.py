"""Sheet archive tables: constraints and the write-lock helper (spec 7.1)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from app.models.sheet import Sheet, SheetCell, SheetType, SheetTypeVersion
from app.sheets.locking import acquire_sheet_write_lock
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def _type(**over: Any) -> SheetType:
    base: dict[str, Any] = {
        "key": f"t-{uuid4().hex[:8]}",
        "prefix": f"P{uuid4().hex[:6]}".upper(),
        "origin": "custom",
    }
    base.update(over)
    return SheetType(**base)


def _version(type_id: Any, **over: Any) -> SheetTypeVersion:
    base: dict[str, Any] = {
        "type_id": type_id,
        "version": 1,
        "page_size": "A4",
        "page_w": 21000,
        "page_h": 29700,
        "label_w": 3000,
        "label_h": 2000,
        "cols": 2,
        "rows": 2,
        "pitch_x": 3100,
        "pitch_y": 2100,
        "margin_top": 1000,
        "margin_left": 1000,
        "shape": "rectangle",
        "geometry_hash": "h",
    }
    base.update(over)
    return SheetTypeVersion(**base)


def _sheet(type_id: Any, version_id: Any, **over: Any) -> Sheet:
    base: dict[str, Any] = {
        "code": f"X-{uuid4().hex[:6]}",
        "type_id": type_id,
        "type_version_id": version_id,
        "id_placement": "cell",
    }
    base.update(over)
    return Sheet(**base)


async def _make_sheet(session: Any) -> Sheet:
    t = _type()
    session.add(t)
    await session.flush()
    v = _version(t.id)
    session.add(v)
    await session.flush()
    s = _sheet(t.id, v.id)
    session.add(s)
    await session.commit()
    return s


async def test_sheet_cells_composite_pk_blocks_double_take(session):
    s = await _make_sheet(session)
    session.add(SheetCell(sheet_id=s.id, cell_no=5, state="reserved", source="manual"))
    await session.commit()
    session.add(SheetCell(sheet_id=s.id, cell_no=5, state="used", source="manual"))
    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.parametrize(
    "kind",
    ["sheet_state", "id_placement", "cell_state", "origin", "shape", "page_size"],
)
async def test_check_constraints(session, kind):
    s = await _make_sheet(session)
    bad: Any
    if kind == "sheet_state":
        bad = _sheet(s.type_id, s.type_version_id, state="bogus")
    elif kind == "id_placement":
        bad = _sheet(s.type_id, s.type_version_id, id_placement="bogus")
    elif kind == "cell_state":
        bad = SheetCell(sheet_id=s.id, cell_no=1, state="bogus", source="manual")
    elif kind == "origin":
        bad = _type(origin="bogus")
    elif kind == "shape":
        bad = _version(s.type_id, version=2, shape="bogus")
    else:
        bad = _version(s.type_id, version=2, page_size="A3")
    session.add(bad)
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_unique_key_prefix_and_version(session):
    s = await _make_sheet(session)
    type_id = s.type_id
    t = await session.get(SheetType, type_id)
    key, prefix = t.key, t.prefix
    session.add(_type(key=key))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()
    session.add(_type(prefix=prefix))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()
    session.add(_version(type_id, version=1))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_sheet_code_unique(session):
    s = await _make_sheet(session)
    session.add(_sheet(s.type_id, s.type_version_id, code=s.code))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_sheet_cells_job_id_not_fk(session):
    s = await _make_sheet(session)
    assert (await session.execute(text("PRAGMA foreign_keys"))).scalar() == 1
    session.add(SheetCell(sheet_id=s.id, cell_no=1, state="used", source="manual", job_id=uuid4()))
    await session.commit()


async def test_sheet_cell_requires_existing_sheet(session):
    session.add(SheetCell(sheet_id=uuid4(), cell_no=1, state="used", source="manual"))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_write_lock_upsert_without_row(session):
    await acquire_sheet_write_lock(session)
    assert (
        await session.execute(text("SELECT seq FROM sheet_write_lock WHERE id = 1"))
    ).scalar() == 1
    await session.commit()  # the lock is the first statement of its transaction (264-01)
    await acquire_sheet_write_lock(session)
    assert (
        await session.execute(text("SELECT seq FROM sheet_write_lock WHERE id = 1"))
    ).scalar() == 2


async def test_write_lock_rejects_second_row(session):
    await acquire_sheet_write_lock(session)
    with pytest.raises(IntegrityError):
        await session.execute(text("INSERT INTO sheet_write_lock (id, seq) VALUES (2, 1)"))
