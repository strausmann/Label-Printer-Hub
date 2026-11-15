# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Correcting a shipped sheet type whose shipped geometry changed (spec 10i, R-334-7; #334)."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path

import pytest
from app.models.app_setting import AppSetting
from app.models.sheet import Sheet, SheetTypeVersion
from app.seed import sheet_seed
from app.seed.sheet_seed import CORRECTED_KEY, NOTICES_KEY, SEED_ACTOR, load_seed, run_sheet_seed
from app.sheets import sheet_service as ss
from app.sheets import type_service as ts
from app.sheets.exchange import geometry_from_doc
from app.sheets.geometry import Geometry, geometry_hash
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

Factory = async_sessionmaker[AsyncSession]

REV1 = Path(__file__).parents[2] / "fixtures" / "seed" / "sheet_types_rev1.json"
KEY = "avery-zweckform-l4731rev"
CHANGE_NOTE = (
    "Verified geometry shipped with Labelyard 1.7.0 "
    "(top margin 13.5 → 12.54 mm, row pitch 10.0 → 9.98 mm)"
)


def _geometry(seed_docs: list, key: str = KEY) -> Geometry:  # type: ignore[type-arg]
    doc = next(d for d in seed_docs if d.type.key == key)
    return geometry_from_doc(doc.version.geometry)


NEW = _geometry(load_seed().docs)
OLD = _geometry(load_seed(REV1).docs)


async def _seed_rev1(factory: Factory, monkeypatch: pytest.MonkeyPatch) -> None:
    real = sheet_seed.load_seed
    monkeypatch.setattr(sheet_seed, "load_seed", lambda: real(REV1))
    await run_sheet_seed(factory)
    monkeypatch.undo()


async def _versions(factory: Factory) -> list[SheetTypeVersion]:
    async with factory() as s:
        t = await ts.get_type(s, KEY)
        rows = await s.execute(
            select(SheetTypeVersion)
            .where(SheetTypeVersion.type_id == t.id)  # type: ignore[arg-type]
            .order_by(SheetTypeVersion.version)  # type: ignore[arg-type]
        )
        return list(rows.scalars())


async def _notices(factory: Factory) -> list[dict[str, str]]:
    async with factory() as s:
        row = await s.get(AppSetting, NOTICES_KEY)
        return [] if row is None or row.value_json is None else json.loads(row.value_json)


async def _sheet(factory: Factory, version: int | None = None) -> Sheet:
    async with factory() as s:
        return await ss.create_sheet(
            s, type_key=KEY, version=version, used_cells=[], note=None, actor="admin"
        )


async def test_fresh_install_has_the_corrected_l4731rev(async_session_factory: Factory) -> None:
    await run_sheet_seed(async_session_factory)
    versions = await _versions(async_session_factory)
    assert [v.version for v in versions] == [1]
    assert versions[0].geometry_hash == geometry_hash(NEW) and versions[0].margin_top == 1254
    async with async_session_factory() as s:
        assert (await ts.get_type(s, KEY)).verified is True
    assert await _notices(async_session_factory) == []


async def test_old_shipped_l4731rev_gets_a_new_version(
    async_session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_rev1(async_session_factory, monkeypatch)
    old_sheet = await _sheet(async_session_factory)
    async with async_session_factory() as s:
        before = await ts.get_type(s, KEY)
        qr_before = before.allow_qr
    report = await run_sheet_seed(async_session_factory)
    assert report.corrected == [KEY]
    versions = await _versions(async_session_factory)
    assert [v.version for v in versions] == [1, 2]
    assert versions[0].geometry_hash == geometry_hash(OLD)  # v1 unchanged
    assert versions[1].geometry_hash == geometry_hash(NEW)
    assert versions[1].created_by == SEED_ACTOR and versions[1].change_note == CHANGE_NOTE
    new_sheet = await _sheet(async_session_factory)
    async with async_session_factory() as s:
        t = await ts.get_type(s, KEY)
        assert (await s.get(Sheet, old_sheet.id)).type_version_id == versions[0].id  # type: ignore[union-attr]
        assert (await s.get(Sheet, new_sheet.id)).type_version_id == versions[1].id  # type: ignore[union-attr]
    shipped = next(d for d in load_seed().docs if d.type.key == KEY)
    assert t.verified is True and t.allow_qr is qr_before and t.notes == shipped.type.notes
    notices = await _notices(async_session_factory)
    assert [(n["kind"], n["key"], n["code"]) for n in notices] == [
        ("sheet_type_updated", KEY, "L4731REV")
    ]


async def test_operator_v3_is_already_corrected(
    async_session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_rev1(async_session_factory, monkeypatch)
    async with async_session_factory() as s:
        await ts.add_version(
            s, KEY, replace(OLD, margin_top=1260), actor="admin", change_note="first try"
        )
        await ts.add_version(s, KEY, NEW, actor="admin", change_note="check print passed")
    await run_sheet_seed(async_session_factory)
    assert [v.version for v in await _versions(async_session_factory)] == [1, 2, 3]
    assert await _notices(async_session_factory) == []


async def test_edited_notes_are_kept(
    async_session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_rev1(async_session_factory, monkeypatch)
    async with async_session_factory() as s:
        await ts.patch_type(s, KEY, {"notes": "my own notes"}, actor="admin")
    await run_sheet_seed(async_session_factory)
    assert [v.version for v in await _versions(async_session_factory)] == [1, 2]
    async with async_session_factory() as s:
        t = await ts.get_type(s, KEY)
    assert t.verified is True and t.notes == "my own notes"


async def test_locally_edited_geometry_is_left_alone(
    async_session_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _seed_rev1(async_session_factory, monkeypatch)
    async with async_session_factory() as s:
        await ts.add_version(
            s, KEY, replace(OLD, margin_top=1300), actor="admin", change_note="my measurement"
        )
    with caplog.at_level(logging.INFO, logger="app.seed.sheet_seed"):
        report = await run_sheet_seed(async_session_factory)
    assert report.corrected == [] and report.versions_added == []
    assert [v.version for v in await _versions(async_session_factory)] == [1, 2]
    assert await _notices(async_session_factory) == []
    async with async_session_factory() as s:
        assert (await ts.get_type(s, KEY)).verified is False
    assert any(
        r.levelno == logging.INFO and "seed correction skipped" in r.getMessage()
        for r in caplog.records
    )


async def test_non_seed_origin_is_left_alone(
    async_session_factory: Factory, caplog: pytest.LogCaptureFixture
) -> None:
    fields = ts.TypeFields(
        key=KEY,
        prefix="L4731",
        vendor="Avery Zweckform",
        product_codes=["L4731REV-25"],
        description=None,
        allow_qr=True,
    )
    async with async_session_factory() as s:
        await ts.create_type(s, fields, OLD, actor="admin", origin="imported")
    with caplog.at_level(logging.INFO, logger="app.seed.sheet_seed"):
        report = await run_sheet_seed(async_session_factory)
        await run_sheet_seed(async_session_factory)
    assert report.corrected == [] and report.versions_added == []
    versions = await _versions(async_session_factory)
    assert [v.version for v in versions] == [1] and versions[0].geometry_hash == geometry_hash(OLD)
    assert await _notices(async_session_factory) == []
    # a never-shipped type is no "locally edited" shipped type: no line on any start
    assert not [r for r in caplog.records if "seed correction skipped" in r.getMessage()]


async def test_correction_runs_once(
    async_session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_rev1(async_session_factory, monkeypatch)
    await run_sheet_seed(async_session_factory)
    # The user goes back to the old geometry before the next start: the recorded correction,
    # not the geometry, is what keeps the seeder from correcting a second time.
    async with async_session_factory() as s:
        await ts.add_version(s, KEY, OLD, actor="admin", change_note="back to the old one")
    second = await run_sheet_seed(async_session_factory)
    assert second.corrected == [] and second.versions_added == []
    assert [v.version for v in await _versions(async_session_factory)] == [1, 2, 3]
    assert len(await _notices(async_session_factory)) == 1
    third = await run_sheet_seed(async_session_factory)
    assert third.corrected == [] and third.versions_added == []
    async with async_session_factory() as s:
        row = await s.get(AppSetting, CORRECTED_KEY)
    assert row is not None and json.loads(row.value_json or "{}") == {KEY: 2}


async def test_correction_second_start_is_quiet(
    async_session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_rev1(async_session_factory, monkeypatch)
    await run_sheet_seed(async_session_factory)
    second = await run_sheet_seed(async_session_factory)
    assert second.corrected == [] and second.versions_added == []
    assert [v.version for v in await _versions(async_session_factory)] == [1, 2]
    assert len(await _notices(async_session_factory)) == 1


async def test_downgraded_seed_does_not_revert(
    async_session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    await run_sheet_seed(async_session_factory)
    real = sheet_seed.load_seed
    monkeypatch.setattr(sheet_seed, "load_seed", lambda: real(REV1))
    report = await run_sheet_seed(async_session_factory)
    assert report.versions_added == [] and report.corrected == []
    versions = await _versions(async_session_factory)
    assert [v.version for v in versions] == [1] and versions[0].geometry_hash == geometry_hash(NEW)
