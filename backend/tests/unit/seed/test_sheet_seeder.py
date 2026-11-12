"""The sheet type seeder (Plan 1, Task 5; OC-14)."""

from __future__ import annotations

import logging
from dataclasses import replace

import pytest
from app.models.sheet import Sheet, SheetType, SheetTypeVersion
from app.seed import sheet_seed
from app.seed.sheet_seed import SEED_ACTOR, load_seed, run_sheet_seed
from app.sheets import type_service as ts
from app.sheets.exchange import ExportDoc, geometry_from_doc
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

Factory = async_sessionmaker[AsyncSession]


async def _count(factory: Factory, model: type) -> int:
    async with factory() as s:
        return int((await s.execute(select(func.count()).select_from(model))).scalar_one())


def _patched(monkeypatch: pytest.MonkeyPatch, key: str, revision: int = 2) -> None:
    """Return the shipped seed with a different column count for ``key``."""
    _, docs = load_seed()

    def changed(d: ExportDoc) -> ExportDoc:
        g = d.version.geometry
        return d.model_copy(
            update={"version": d.version.model_copy(update={"geometry": g.model_copy(
                update={"cols": g.cols - 1})})}
        )  # fmt: skip

    patched = [changed(d) if d.type.key == key else d for d in docs]
    monkeypatch.setattr(sheet_seed, "load_seed", lambda: (revision, patched))


async def test_seeder_inserts_once(async_session_factory: Factory) -> None:
    first = await run_sheet_seed(async_session_factory)
    assert len(first.inserted) == 36 and not first.versions_added and not first.skipped
    second = await run_sheet_seed(async_session_factory)
    assert not second.inserted and not second.versions_added and not second.skipped
    assert await _count(async_session_factory, SheetType) == 36
    async with async_session_factory() as s:
        origins = set((await s.execute(select(SheetType.origin))).scalars())
        assert origins == {"seed"}
        verified = set((await s.execute(select(SheetType.verified))).scalars())
        assert verified == {False}


async def test_seeder_adds_version_for_untouched_seed_type(
    async_session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    await run_sheet_seed(async_session_factory)
    _patched(monkeypatch, "herma-4098")
    report = await run_sheet_seed(async_session_factory)
    assert report.versions_added == ["herma-4098"] and not report.inserted
    async with async_session_factory() as s:
        t = await ts.get_type(s, "herma-4098")
        v = await ts.current_version(s, t.id)
        assert v.version == 2 and v.cols == 2 and v.created_by == SEED_ACTOR
    again = await run_sheet_seed(async_session_factory)
    assert not again.versions_added


async def test_seeder_leaves_edited_type_alone(
    async_session_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await run_sheet_seed(async_session_factory)
    _, docs = load_seed()
    doc = next(d for d in docs if d.type.key == "herma-4098")
    edited = replace(geometry_from_doc(doc.version.geometry), margin_left=700)
    async with async_session_factory() as s:
        await ts.add_version(s, "herma-4098", edited, actor="admin", change_note="local fix")
    _patched(monkeypatch, "herma-4098")
    with caplog.at_level(logging.INFO, logger="app.seed.sheet_seed"):
        report = await run_sheet_seed(async_session_factory)
    assert not report.versions_added
    assert any(r.levelno == logging.INFO and "herma-4098" in r.getMessage() for r in caplog.records)
    async with async_session_factory() as s:
        t = await ts.get_type(s, "herma-4098")
        assert (await ts.current_version(s, t.id)).version == 2  # only the admin's version


async def test_seeder_treats_an_allow_qr_edit_as_a_local_edit(
    async_session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    await run_sheet_seed(async_session_factory)
    async with async_session_factory() as s:
        t = await ts.get_type(s, "herma-4098")
        await ts.patch_type(s, t.key, {"allow_qr": not t.allow_qr}, actor="admin")
    _patched(monkeypatch, "herma-4098")
    report = await run_sheet_seed(async_session_factory)
    assert not report.versions_added
    async with async_session_factory() as s:
        t = await ts.get_type(s, "herma-4098")
        assert (await ts.current_version(s, t.id)).version == 1


async def test_seeder_does_not_mistake_a_user_named_seed_for_itself(
    async_session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.routes.sheet_common import actor
    from app.auth.dependencies import AuthContext

    await run_sheet_seed(async_session_factory)
    _, docs = load_seed()
    doc = next(d for d in docs if d.type.key == "herma-4098")
    edited = replace(geometry_from_doc(doc.version.geometry), margin_left=700)
    who = actor(
        AuthContext(
            source="pangolin-sso", scope="print", api_key_id=None, user="seed", ip="192.0.2.1"
        )
    )
    async with async_session_factory() as s:
        await ts.add_version(s, "herma-4098", edited, actor=who, change_note="local fix")
    _patched(monkeypatch, "herma-4098")
    report = await run_sheet_seed(async_session_factory)
    assert not report.versions_added


async def test_seeder_leaves_type_with_sheets_alone(
    async_session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    await run_sheet_seed(async_session_factory)
    async with async_session_factory() as s:
        t = await ts.get_type(s, "herma-4098")
        v = await ts.current_version(s, t.id)
        s.add(Sheet(code="H4098-0001", type_id=t.id, type_version_id=v.id, id_placement="cell"))
        await s.commit()
    _patched(monkeypatch, "herma-4098")
    report = await run_sheet_seed(async_session_factory)
    assert not report.versions_added
    assert await _count(async_session_factory, SheetTypeVersion) == 36


async def test_seeder_skips_on_prefix_taken(
    async_session_factory: Factory, caplog: pytest.LogCaptureFixture
) -> None:
    _, docs = load_seed()
    doc = next(d for d in docs if d.type.key == "avery-zweckform-l4731rev")
    async with async_session_factory() as s:
        await ts.create_type(
            s,
            ts.TypeFields(
                key="my-own-type",
                prefix="L4731",
                vendor=None,
                product_codes=[],
                description=None,
                allow_qr=False,
            ),
            geometry_from_doc(doc.version.geometry),
            actor="admin",
        )
    with caplog.at_level(logging.WARNING, logger="app.seed.sheet_seed"):
        report = await run_sheet_seed(async_session_factory)
    assert report.skipped == {"avery-zweckform-l4731rev": "prefix_taken"}
    assert len(report.inserted) == 35
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    assert await _count(async_session_factory, SheetType) == 36  # 35 seed + 1 custom


async def test_notices_list_glabels() -> None:
    from pathlib import Path

    text = (Path(__file__).parents[4] / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    for needle in (
        "gLabels-qt",
        "37901c1",
        "Copyright (C) 2001-2026 Jaye Evins",
        "Permission is hereby granted, free of charge",
    ):
        assert needle in text


async def test_seeder_leaves_type_with_row_edit_alone(
    async_session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A row edit makes no version, so geometry provenance alone would miss it."""
    await run_sheet_seed(async_session_factory)
    async with async_session_factory() as s:
        await ts.patch_type(s, "herma-4098", {"verified": True}, actor="admin")
    _patched(monkeypatch, "herma-4098")
    report = await run_sheet_seed(async_session_factory)
    assert not report.versions_added
    async with async_session_factory() as s:
        t = await ts.get_type(s, "herma-4098")
        assert (await ts.current_version(s, t.id)).version == 1
        assert t.verified is True


async def test_seeder_leaves_type_that_is_not_seed_origin_alone(
    async_session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    await run_sheet_seed(async_session_factory)
    async with async_session_factory() as s:
        t = await ts.get_type(s, "herma-4098")
        t.origin = "custom"
        await s.commit()
    _patched(monkeypatch, "herma-4098")
    report = await run_sheet_seed(async_session_factory)
    assert not report.versions_added


async def test_one_bad_seed_entry_keeps_the_others(
    async_session_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """264-10: a failing entry is rolled back alone and logged; the other seeds are stored."""
    real = ts.create_type_locked

    async def failing(session: AsyncSession, fields: ts.TypeFields, *a: object, **kw: object):
        if fields.key == "herma-4098":
            await real(session, fields, *a, **kw)  # writes rows, then fails: the savepoint undoes
            raise RuntimeError("broken entry")
        return await real(session, fields, *a, **kw)

    monkeypatch.setattr(ts, "create_type_locked", failing)
    with caplog.at_level(logging.ERROR, logger="app.seed.sheet_seed"):
        report = await run_sheet_seed(async_session_factory)
    assert report.skipped == {"herma-4098": "error"}
    assert len(report.inserted) == 35 and "herma-4098" not in report.inserted
    assert await _count(async_session_factory, SheetType) == 35
    assert await _count(async_session_factory, SheetTypeVersion) == 35
    assert any("herma-4098" in r.getMessage() for r in caplog.records)
    monkeypatch.setattr(ts, "create_type_locked", real)
    again = await run_sheet_seed(async_session_factory)
    assert again.inserted == ["herma-4098"]


async def test_older_seed_does_not_add_revert_version(
    async_session_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """264-11: after a newer seed added version 2, the older seed (version 1) changes nothing."""
    await run_sheet_seed(async_session_factory)
    _, docs = load_seed()
    original = next(d for d in docs if d.type.key == "herma-4098")
    g = original.version.geometry
    newer = original.model_copy(
        update={"version": original.version.model_copy(
            update={"version": 2, "geometry": g.model_copy(update={"cols": g.cols - 1})})}
    )  # fmt: skip
    monkeypatch.setattr(
        sheet_seed,
        "load_seed",
        lambda: (2, [newer if d.type.key == "herma-4098" else d for d in docs]),
    )
    assert (await run_sheet_seed(async_session_factory)).versions_added == ["herma-4098"]

    monkeypatch.setattr(sheet_seed, "load_seed", lambda: (1, docs))  # the hub was downgraded
    with caplog.at_level(logging.INFO, logger="app.seed.sheet_seed"):
        report = await run_sheet_seed(async_session_factory)
    assert not report.versions_added and not report.skipped
    assert any(r.levelno == logging.INFO and "herma-4098" in r.getMessage() for r in caplog.records)
    async with async_session_factory() as s:
        t = await ts.get_type(s, "herma-4098")
        current = await ts.current_version(s, t.id)
        assert current.version == 2 and current.cols == g.cols - 1
