# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Adopting a shipped key that already exists (spec 10i, R-334-3/4, I1, I5; #334)."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from app.models.app_setting import AppSetting
from app.models.sheet import Sheet, SheetType, SheetTypeVersion
from app.seed import sheet_seed
from app.seed.sheet_seed import (
    ADOPTED_KEY,
    CORRECTED_KEY,
    NOTICES_KEY,
    SEED_ACTOR,
    load_seed,
    run_sheet_seed,
)
from app.settings_store.store import SettingsStore
from app.sheets import sheet_service as ss
from app.sheets import type_service as ts
from app.sheets.errors import SheetTypeInUseError
from app.sheets.exchange import geometry_from_doc
from app.sheets.geometry import Geometry, geometry_hash
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

Factory = async_sessionmaker[AsyncSession]

REV1 = Path(__file__).parents[2] / "fixtures" / "seed" / "sheet_types_rev1.json"
K6121 = "avery-zweckform-6121"
K3490 = "avery-zweckform-3490"
K4737 = "avery-zweckform-l4737rev"
CHANGE_NOTE = "Verified geometry shipped with Labelyard 1.7.0"
ALL_MARKERS = {K6121: 2, K3490: 2, K4737: 2}


def _shipped(key: str) -> Geometry:
    doc = next(d for d in load_seed().docs if d.type.key == key)
    return geometry_from_doc(doc.version.geometry)


async def _import(
    factory: Factory,
    key: str,
    prefix: str,
    geometry: Geometry,
    *,
    origin: str = "imported",
    product_codes: list[str] | None = None,
    **extra: object,
) -> None:
    fields = ts.TypeFields(
        key=key,
        prefix=prefix,
        vendor=extra.get("vendor", "Avery"),  # type: ignore[arg-type]
        product_codes=product_codes if product_codes is not None else [key.rsplit("-", 1)[-1]],
        description=extra.get("description", "mine"),  # type: ignore[arg-type]
        allow_qr=extra.get("allow_qr", False),  # type: ignore[arg-type]
        verified=False,
        source_name="local source",
        source_url=extra.get("source_url", "https://example.invalid/t"),  # type: ignore[arg-type]
        notes="local notes",
    )
    async with factory() as s:
        await ts.create_type(s, fields, geometry, actor="admin", origin=origin)  # type: ignore[arg-type]


async def _versions(factory: Factory, key: str) -> list[SheetTypeVersion]:
    async with factory() as s:
        t = await ts.get_type(s, key)
        rows = await s.execute(
            select(SheetTypeVersion)
            .where(SheetTypeVersion.type_id == t.id)  # type: ignore[arg-type]
            .order_by(SheetTypeVersion.version)  # type: ignore[arg-type]
        )
        return list(rows.scalars())


async def _type(factory: Factory, key: str) -> SheetType:
    async with factory() as s:
        return await ts.get_type(s, key)


async def _setting(factory: Factory, key: str) -> object:
    async with factory() as s:
        row = await s.get(AppSetting, key)
        return None if row is None or row.value_json is None else json.loads(row.value_json)


async def _notices(factory: Factory) -> list[dict[str, str]]:
    return list(await _setting(factory, NOTICES_KEY) or [])  # type: ignore[call-overload]


def _warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        r
        for r in caplog.records
        if r.levelno >= logging.WARNING and r.name == "app.seed.sheet_seed"
    ]


async def _sheet(factory: Factory, key: str, version: int | None = None) -> Sheet:
    async with factory() as s:
        return await ss.create_sheet(
            s, type_key=key, version=version, used_cells=[], note=None, actor="admin"
        )


async def test_fresh_install_seeds_the_new_types_verified(async_session_factory: Factory) -> None:
    report = await run_sheet_seed(async_session_factory)
    assert {K6121, K3490, K4737} <= set(report.inserted) and not report.adopted
    for key in (K6121, K3490, K4737):
        t = await _type(async_session_factory, key)
        assert t.origin == "seed" and t.verified is True
        assert [v.version for v in await _versions(async_session_factory, key)] == [1]
    assert (await _versions(async_session_factory, K4737))[0].margin_left == 695
    assert await _notices(async_session_factory) == []
    assert await _setting(async_session_factory, ADOPTED_KEY) == ALL_MARKERS  # I1


async def test_fresh_install_second_start_is_silent(
    async_session_factory: Factory, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="app.seed.sheet_seed"):
        await run_sheet_seed(async_session_factory)
        second = await run_sheet_seed(async_session_factory)
    assert second.adopted == [] and second.inserted == [] and second.versions_added == []
    assert await _notices(async_session_factory) == []
    assert _warnings(caplog) == []
    for key in (K6121, K3490, K4737):
        assert len(await _versions(async_session_factory, key)) == 1


async def test_upgrade_from_revision_1_adopts_nothing(
    async_session_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    real = sheet_seed.load_seed
    monkeypatch.setattr(sheet_seed, "load_seed", lambda: real(REV1))
    await run_sheet_seed(async_session_factory)
    monkeypatch.undo()
    with caplog.at_level(logging.WARNING, logger="app.seed.sheet_seed"):
        first = await run_sheet_seed(async_session_factory)
        notices_after_first = await _notices(async_session_factory)
        second = await run_sheet_seed(async_session_factory)
    assert {K6121, K3490, K4737} <= set(first.inserted) and first.adopted == []
    assert second.adopted == [] and second.inserted == []
    assert await _setting(async_session_factory, ADOPTED_KEY) == ALL_MARKERS
    # the only notice of the upgrade is the L4731REV correction, none for the three new types
    assert [n["key"] for n in notices_after_first] == ["avery-zweckform-l4731rev"]
    assert await _notices(async_session_factory) == notices_after_first
    assert [r for r in _warnings(caplog) if "adopted" in r.getMessage()] == []


async def test_imported_3490_with_other_geometry_gets_a_new_version(
    async_session_factory: Factory,
) -> None:
    other = replace(_shipped(K3490), margin_top=443)
    await _import(async_session_factory, K3490, "A3490", other, product_codes=["3490"])
    await run_sheet_seed(async_session_factory)
    versions = await _versions(async_session_factory, K3490)
    assert [v.version for v in versions] == [1, 2]
    assert versions[1].geometry_hash == geometry_hash(_shipped(K3490))
    assert versions[1].change_note == CHANGE_NOTE and versions[1].created_by == SEED_ACTOR
    notices = await _notices(async_session_factory)
    assert [(n["kind"], n["key"], n["code"]) for n in notices] == [
        ("sheet_type_updated", K3490, "3490")
    ]


async def test_imported_6121_with_the_same_geometry_is_adopted(
    async_session_factory: Factory, caplog: pytest.LogCaptureFixture
) -> None:
    await _import(async_session_factory, K6121, "A6121", _shipped(K6121), product_codes=["6121-X"])
    with caplog.at_level(logging.WARNING, logger="app.seed.sheet_seed"):
        report = await run_sheet_seed(async_session_factory)
    seed = next(d for d in load_seed().docs if d.type.key == K6121)
    t = await _type(async_session_factory, K6121)
    assert len(await _versions(async_session_factory, K6121)) == 1 and report.adopted == [K6121]
    assert t.origin == "seed" and t.verified is True
    assert t.notes == seed.type.notes and t.source_name == seed.type.source_name
    assert t.source_url is None  # overwritten by the shipped value
    assert (t.prefix, t.vendor, t.product_codes) == ("A6121", "Avery", ["6121-X"])
    assert (t.description, t.allow_qr) == ("mine", False)  # m2: the user's own choices stay
    notices = await _notices(async_session_factory)
    assert [(n["kind"], n["code"]) for n in notices] == [("sheet_type_verified", "6121-X")]
    assert (await _setting(async_session_factory, ADOPTED_KEY))[K6121] == 2  # type: ignore[index]
    adopted = [r for r in _warnings(caplog) if "adopted as shipped" in r.getMessage()]
    assert len(adopted) == 1 and (seed.type.notes or "") not in adopted[0].getMessage()


async def test_imported_l4737rev_is_adopted_as_verified(async_session_factory: Factory) -> None:
    """The operator's instance holds v1 (7.25) and v2 (6.95, the shipped one, latest)."""
    shipped = _shipped(K4737)
    codes = ["L4737REV-25", "L4737REV-10", "L4737REV-100", "L4737"]
    await _import(
        async_session_factory,
        K4737,
        "L4737",
        replace(shipped, margin_left=725),
        product_codes=codes,
    )
    async with async_session_factory() as s:
        await ts.add_version(s, K4737, shipped, actor="admin", change_note="measured")
    sheet = await _sheet(async_session_factory, K4737, 1)
    await run_sheet_seed(async_session_factory)
    versions = await _versions(async_session_factory, K4737)
    assert [v.version for v in versions] == [1, 2]
    assert versions[0].margin_left == 725
    async with async_session_factory() as s:
        pinned = (await s.get(Sheet, sheet.id)).type_version_id  # type: ignore[union-attr]
    assert pinned == versions[0].id
    assert [(n["kind"], n["code"]) for n in await _notices(async_session_factory)] == [
        ("sheet_type_verified", "L4737REV")
    ]
    assert (await _type(async_session_factory, K4737)).verified is True


async def test_imported_l4737rev_on_7_25_gets_the_shipped_geometry(
    async_session_factory: Factory,
) -> None:
    await _import(
        async_session_factory,
        K4737,
        "L4737",
        replace(_shipped(K4737), margin_left=725),
        product_codes=["L4737REV-25"],
    )
    await run_sheet_seed(async_session_factory)
    versions = await _versions(async_session_factory, K4737)
    assert [v.version for v in versions] == [1, 2]
    assert versions[1].geometry_hash == (
        "ca1dcfafb491a55240b24c343c483d96a462d6d7d10239b9c7e68c07dffce509"
    )
    assert versions[1].change_note == CHANGE_NOTE
    assert [n["kind"] for n in await _notices(async_session_factory)] == ["sheet_type_updated"]


async def test_custom_6121_with_other_geometry_gets_a_new_version(
    async_session_factory: Factory,
) -> None:
    other = replace(_shipped(K6121), pitch_x=4060, margin_left=500)
    await _import(async_session_factory, K6121, "A6121", other, origin="custom")
    old_sheet = await _sheet(async_session_factory, K6121)
    await run_sheet_seed(async_session_factory)
    versions = await _versions(async_session_factory, K6121)
    assert [v.version for v in versions] == [1, 2]
    assert versions[0].pitch_x == 4060 and versions[0].created_by == "admin"
    assert versions[1].geometry_hash == geometry_hash(_shipped(K6121))
    assert versions[1].created_by == SEED_ACTOR and versions[1].change_note == CHANGE_NOTE
    new_sheet = await _sheet(async_session_factory, K6121)
    async with async_session_factory() as s:
        old = await s.get(Sheet, old_sheet.id)
        new = await s.get(Sheet, new_sheet.id)
    assert old.type_version_id == versions[0].id  # type: ignore[union-attr]
    assert new.type_version_id == versions[1].id  # type: ignore[union-attr]
    t = await _type(async_session_factory, K6121)
    assert t.origin == "seed" and t.verified is True
    assert [n["kind"] for n in await _notices(async_session_factory)] == ["sheet_type_updated"]
    async with async_session_factory() as s:  # m1: a taken-over type is archived, not deleted
        with pytest.raises(SheetTypeInUseError):
            await ts.delete_type(s, K6121, actor="admin")
        assert (await ts.archive_type(s, K6121, actor="admin")).archived_at is not None


async def test_adoption_ignores_foreign_versions_and_a_lower_seed_version(
    async_session_factory: Factory,
) -> None:
    g = _shipped(K6121)
    await _import(async_session_factory, K6121, "A6121", replace(g, margin_top=900))
    for n, top in enumerate((950, 1000), start=2):
        async with async_session_factory() as s:
            await ts.add_version(
                s, K6121, replace(g, margin_top=top), actor="admin", change_note=f"v{n}"
            )
    await run_sheet_seed(async_session_factory)  # the seed says version 1, the type is at 3
    versions = await _versions(async_session_factory, K6121)
    assert [v.version for v in versions] == [1, 2, 3, 4]
    assert versions[3].geometry_hash == geometry_hash(g) and versions[3].created_by == SEED_ACTOR


async def test_adoption_runs_once(
    async_session_factory: Factory, caplog: pytest.LogCaptureFixture
) -> None:
    await _import(async_session_factory, K6121, "A6121", replace(_shipped(K6121), margin_top=900))
    with caplog.at_level(logging.WARNING, logger="app.seed.sheet_seed"):
        await run_sheet_seed(async_session_factory)
        again = await run_sheet_seed(async_session_factory)
    assert again.adopted == [] and again.versions_added == []
    assert len(await _versions(async_session_factory, K6121)) == 2
    assert len(await _notices(async_session_factory)) == 1
    assert len([r for r in _warnings(caplog) if "adopted as shipped" in r.getMessage()]) == 1


async def test_a_failing_notice_write_rolls_back_the_adoption(
    async_session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """I5, fault injection: the exception lands between the version write and the notice write."""
    await _import(async_session_factory, K6121, "A6121", replace(_shipped(K6121), margin_top=900))

    async def failing(*args: object, **kwargs: object) -> None:
        raise RuntimeError("notice store down")

    monkeypatch.setattr(sheet_seed, "_append_notice", failing)
    report = await run_sheet_seed(async_session_factory)
    assert report.skipped[K6121] == "error" and report.adopted == []
    assert len(await _versions(async_session_factory, K6121)) == 1
    t = await _type(async_session_factory, K6121)
    assert t.origin == "imported" and t.verified is False
    assert K6121 not in (await _setting(async_session_factory, ADOPTED_KEY) or {})  # type: ignore[operator]
    assert await _count(async_session_factory, SheetType) == 39  # the others are stored
    monkeypatch.undo()
    again = await run_sheet_seed(async_session_factory)
    assert again.adopted == [K6121]
    assert len(await _versions(async_session_factory, K6121)) == 2
    assert len(await _notices(async_session_factory)) == 1
    assert (await _setting(async_session_factory, ADOPTED_KEY))[K6121] == 2  # type: ignore[index]


async def _count(factory: Factory, model: type) -> int:
    async with factory() as s:
        return int((await s.execute(select(func.count()).select_from(model))).scalar_one())


async def test_a_later_local_edit_is_left_alone(async_session_factory: Factory) -> None:
    await _import(async_session_factory, K6121, "A6121", replace(_shipped(K6121), margin_top=900))
    await run_sheet_seed(async_session_factory)
    async with async_session_factory() as s:
        await ts.add_version(
            s,
            K6121,
            replace(_shipped(K6121), margin_top=1000),
            actor="admin",
            change_note="my tweak",
        )
    again = await run_sheet_seed(async_session_factory)
    assert again.versions_added == [] and again.adopted == []
    assert len(await _versions(async_session_factory, K6121)) == 3


async def test_custom_6121_with_another_prefix_keeps_its_prefix(
    async_session_factory: Factory,
) -> None:
    await _import(
        async_session_factory,
        K6121,
        "AZ6121",
        replace(_shipped(K6121), margin_top=900),
        origin="custom",
    )
    sheet = await _sheet(async_session_factory, K6121)
    assert sheet.code.startswith("AZ6121-")
    await run_sheet_seed(async_session_factory)
    t = await _type(async_session_factory, K6121)
    assert t.prefix == "AZ6121" and t.origin == "seed" and t.verified is True
    assert len(await _versions(async_session_factory, K6121)) == 2


async def test_another_type_holding_a6121_blocks_the_insert(
    async_session_factory: Factory,
) -> None:
    await _import(async_session_factory, "my-labels", "A6121", _shipped(K6121), origin="custom")
    first = await run_sheet_seed(async_session_factory)
    assert first.skipped[K6121] == "prefix_taken" and K6121 not in first.inserted
    assert K6121 not in (await _setting(async_session_factory, ADOPTED_KEY) or {})  # type: ignore[operator]
    async with async_session_factory() as s:
        await ts.patch_type(s, "my-labels", {"prefix": "MYL1"}, actor="admin")
    second = await run_sheet_seed(async_session_factory)
    assert K6121 in second.inserted
    assert (await _setting(async_session_factory, ADOPTED_KEY))[K6121] == 2  # type: ignore[index]
    assert await _notices(async_session_factory) == []


async def test_adoption_never_deletes_a_version(async_session_factory: Factory) -> None:
    await _import(async_session_factory, K6121, "A6121", replace(_shipped(K6121), margin_top=900))
    await _import(async_session_factory, K3490, "A3490", _shipped(K3490))
    await _sheet(async_session_factory, K6121)
    await _sheet(async_session_factory, K3490)
    versions_before = await _count(async_session_factory, SheetTypeVersion)
    sheets_before = await _count(async_session_factory, Sheet)
    report = await run_sheet_seed(async_session_factory)
    added = await _count(async_session_factory, SheetTypeVersion) - versions_before
    # 36 other seed types are inserted with one version each, the adoption adds one for 6121
    assert added == len(report.inserted) + 1
    assert await _count(async_session_factory, Sheet) == sheets_before


async def test_internal_keys_do_not_reach_the_settings_store(
    async_session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    # an install on revision 1 (the L4731REV correction writes the third row) plus an adoption
    real = sheet_seed.load_seed
    monkeypatch.setattr(sheet_seed, "load_seed", lambda: real(REV1))
    await run_sheet_seed(async_session_factory)
    monkeypatch.undo()
    await _import(async_session_factory, K6121, "A6121", replace(_shipped(K6121), margin_top=900))
    await run_sheet_seed(async_session_factory)
    async with async_session_factory() as s:
        keys = set((await s.execute(select(AppSetting.key))).scalars())
        assert {ADOPTED_KEY, CORRECTED_KEY, NOTICES_KEY} <= keys
        store = SettingsStore()
        await store.load(s)
    assert not {v.key for v in store.describe()} & keys


async def test_notices_older_than_30_days_are_pruned_on_write(
    async_session_factory: Factory,
) -> None:
    old = (datetime.now(UTC) - timedelta(days=31)).isoformat().replace("+00:00", "Z")
    async with async_session_factory() as s:
        s.add(
            AppSetting(
                key=NOTICES_KEY,
                value_json=json.dumps(
                    [
                        {
                            "id": "old",
                            "kind": "sheet_type_verified",
                            "key": "x",
                            "code": "X",
                            "at": old,
                        }
                    ]
                ),
            )
        )
        await s.commit()
    await _import(async_session_factory, K6121, "A6121", replace(_shipped(K6121), margin_top=900))
    await run_sheet_seed(async_session_factory)
    stored = await _notices(async_session_factory)
    assert [n["id"] for n in stored] == [f"sheet-type-verified:{K6121}:2"]
