"""Sheet type service: create, edit, versions, archive, delete (Plan 1, Task 3)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

import pytest
import pytest_asyncio
from app.models.sheet import Sheet, SheetType, SheetTypeVersion
from app.sheets import type_service as ts
from app.sheets.errors import (
    InvalidFieldError,
    InvalidGeometryError,
    PrefixLockedError,
    PrefixTakenError,
    SheetTypeInUseError,
    SheetTypeNotFoundError,
    TypeExistsError,
)
from app.sheets.geometry import Geometry, cell_count
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# 4 x 12 labels of 45.7 x 21.2 mm on A4 (L4736-like).
G_4X12 = Geometry(
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
# 5 x 12 variant used as version 2.
G_5X12 = replace(G_4X12, label_w=3600, cols=5, pitch_x=4000, margin_left=500)
# 25.4 x 10 mm labels, 7 x 27.
G_SMALL = replace(
    G_4X12, label_w=2540, label_h=1000, cols=7, rows=27, pitch_x=2600, pitch_y=1000,
    margin_top=1000, margin_left=500,
)  # fmt: skip


def fields(key: str = "avery-l4736", prefix: str = "L4736", **kw: Any) -> ts.TypeFields:
    base: dict[str, Any] = {
        "key": key,
        "prefix": prefix,
        "vendor": "Avery",
        "product_codes": ["L4736REV-25"],
        "description": "Address labels",
        "allow_qr": None,
    }
    base.update(kw)
    return ts.TypeFields(**base)


@pytest_asyncio.fixture
async def session(async_session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[Any]:
    async with async_session_factory() as s:
        yield s


async def _add_sheet(session: AsyncSession, key: str, version: int, code: str) -> Sheet:
    # Takes the key, not the row: a rolled-back transaction expires loaded rows.
    type_id = (await ts.get_type(session, key)).id
    version_id = (await ts.get_version(session, key, version)).id
    sheet = Sheet(code=code, type_id=type_id, type_version_id=version_id, id_placement="cell")
    session.add(sheet)
    await session.commit()
    return sheet


async def _version_count(session: AsyncSession) -> int:
    return int(
        (await session.execute(select(func.count()).select_from(SheetTypeVersion))).scalar_one()
    )


async def test_create_type_version_1(session: AsyncSession) -> None:
    t, v = await ts.create_type(session, fields(), G_4X12, actor="tester")
    assert t.origin == "custom"
    assert v.version == 1
    assert len(v.geometry_hash) == 64
    assert v.created_by == "tester"
    assert t.allow_qr is True  # shorter side 21.2 mm >= 15 mm
    _, v_small = await ts.create_type(
        session, fields("small-type", "SMALL1"), G_SMALL, actor="tester"
    )
    t_small = await ts.get_type(session, "small-type")
    assert t_small.allow_qr is False  # shorter side 10 mm
    assert v_small.version == 1
    t3, _ = await ts.create_type(
        session, fields("forced-qr", "FQR", allow_qr=True), G_SMALL, actor="tester"
    )
    assert t3.allow_qr is True  # an explicit value wins over the default


async def test_create_duplicate_key_and_prefix(session: AsyncSession) -> None:
    await ts.create_type(session, fields(), G_4X12, actor="tester")
    with pytest.raises(TypeExistsError):
        await ts.create_type(session, fields(prefix="OTHER1"), G_4X12, actor="tester")
    with pytest.raises(PrefixTakenError):
        await ts.create_type(session, fields(key="avery-other"), G_4X12, actor="tester")
    assert await _version_count(session) == 1


async def test_create_rejects_bad_key_prefix_and_geometry(session: AsyncSession) -> None:
    with pytest.raises(InvalidGeometryError):
        await ts.create_type(session, fields(key="Bad Key"), G_4X12, actor="tester")
    with pytest.raises(InvalidGeometryError):
        await ts.create_type(session, fields(prefix="bad"), G_4X12, actor="tester")
    with pytest.raises(InvalidGeometryError):
        await ts.create_type(session, fields(), replace(G_4X12, cols=0), actor="tester")
    count = (await session.execute(select(func.count()).select_from(SheetType))).scalar_one()
    assert count == 0


async def test_get_type_not_found_and_get_version(session: AsyncSession) -> None:
    with pytest.raises(SheetTypeNotFoundError):
        await ts.get_type(session, "nope")
    t, v1 = await ts.create_type(session, fields(), G_4X12, actor="tester")
    assert (await ts.get_version(session, t.key, 1)).id == v1.id
    with pytest.raises(SheetTypeNotFoundError):
        await ts.get_version(session, t.key, 7)


async def test_new_version_does_not_move_existing_sheets(session: AsyncSession) -> None:
    t, v1 = await ts.create_type(session, fields(), G_4X12, actor="tester")
    sheet = await _add_sheet(session, t.key, 1, "L4736-0001")
    v2 = await ts.add_version(session, t.key, G_5X12, actor="tester", change_note="5 columns")
    assert v2.version == 2
    assert v2.change_note == "5 columns"
    assert (await ts.current_version(session, t.id)).id == v2.id
    await session.refresh(sheet)
    assert sheet.type_version_id == v1.id
    pinned = await ts.get_version(session, t.key, 1)
    assert cell_count(ts.version_geometry(pinned)) == 48
    rows = await ts.list_versions_with_sheet_counts(session, t.id)
    assert [(v.version, n) for v, n in rows] == [(1, 1), (2, 0)]


async def test_add_version_unchanged_rejected(session: AsyncSession) -> None:
    t, _ = await ts.create_type(session, fields(), G_4X12, actor="tester")
    with pytest.raises(InvalidGeometryError) as exc:
        await ts.add_version(session, t.key, G_4X12, actor="tester", change_note="same")
    assert exc.value.detail == {"field": "geometry", "reason": "unchanged"}
    assert await _version_count(session) == 1


async def test_add_version_after_revert_to_old_geometry_is_allowed(session: AsyncSession) -> None:
    # Only equality with the *current* version is rejected, not with any older one.
    t, _ = await ts.create_type(session, fields(), G_4X12, actor="tester")
    await ts.add_version(session, t.key, G_5X12, actor="tester", change_note="five")
    v3 = await ts.add_version(session, t.key, G_4X12, actor="tester", change_note="back")
    assert v3.version == 3


async def test_add_version_unknown_type(session: AsyncSession) -> None:
    with pytest.raises(SheetTypeNotFoundError):
        await ts.add_version(session, "nope", G_4X12, actor="tester", change_note="x")


async def test_patch_non_geometry_does_not_add_version(session: AsyncSession) -> None:
    t, _ = await ts.create_type(session, fields(), G_4X12, actor="tester")
    patched = await ts.patch_type(
        session, t.key, {"description": "New text", "verified": True}, actor="tester"
    )
    assert patched.description == "New text"
    assert patched.verified is True
    assert await _version_count(session) == 1


async def test_patch_rejects_unknown_field(session: AsyncSession) -> None:
    t, _ = await ts.create_type(session, fields(), G_4X12, actor="tester")
    with pytest.raises(InvalidGeometryError):
        await ts.patch_type(session, t.key, {"origin": "seed"}, actor="tester")
    with pytest.raises(InvalidGeometryError):
        await ts.patch_type(session, t.key, {"product_codes": "L4736"}, actor="tester")
    assert (await ts.get_type(session, t.key)).origin == "custom"


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("allow_qr", None),
        ("allow_qr", "yes"),
        ("allow_qr", 1),
        ("verified", None),
        ("verified", "true"),
        ("verified", 0),
        ("prefix", None),
        ("prefix", 5),
        ("vendor", 5),
        ("description", ["x"]),
        ("source_name", 1.5),
        ("source_url", {}),
        ("notes", True),
        ("product_codes", None),
        ("product_codes", [1]),
    ],
)
async def test_patch_rejects_wrong_value_types(session: AsyncSession, field: str, bad: Any) -> None:
    t, _ = await ts.create_type(session, fields(), G_4X12, actor="tester")
    key = t.key
    with pytest.raises(InvalidGeometryError) as exc:
        await ts.patch_type(session, key, {field: bad}, actor="tester")
    assert exc.value.status == 422
    assert exc.value.error_code == "invalid_geometry"
    assert exc.value.detail is not None and exc.value.detail["field"] == field
    assert "geometry" not in exc.value.message.lower()
    stored = await ts.get_type(session, key)
    assert stored.allow_qr is True and stored.verified is False and stored.prefix == "L4736"


async def test_patch_nullable_text_fields_accept_none(session: AsyncSession) -> None:
    t, _ = await ts.create_type(session, fields(), G_4X12, actor="tester")
    patched = await ts.patch_type(
        session,
        t.key,
        {"vendor": None, "description": None, "notes": None, "allow_qr": False},
        actor="tester",
    )
    assert patched.vendor is None and patched.description is None
    assert patched.allow_qr is False


async def test_noop_patch_keeps_updated_at(session: AsyncSession) -> None:
    t, _ = await ts.create_type(session, fields(), G_4X12, actor="tester")
    before = t.updated_at
    same = await ts.patch_type(session, t.key, {"description": t.description}, actor="tester")
    assert same.updated_at == before


async def test_format_errors_do_not_talk_about_geometry(session: AsyncSession) -> None:
    with pytest.raises(InvalidGeometryError) as exc:
        await ts.create_type(session, fields(key="Bad Key"), G_4X12, actor="tester")
    assert exc.value.error_code == "invalid_geometry"
    assert "geometry" not in exc.value.message.lower()
    with pytest.raises(InvalidGeometryError) as exc2:
        await ts.create_type(session, fields(prefix="bad"), G_4X12, actor="tester")
    assert "geometry" not in exc2.value.message.lower()


async def test_prefix_editable_only_without_sheets(session: AsyncSession) -> None:
    t, _ = await ts.create_type(session, fields(), G_4X12, actor="tester")
    key = t.key
    await ts.create_type(session, fields("other-type", "OTH1"), G_4X12, actor="tester")
    patched = await ts.patch_type(session, key, {"prefix": "NEWP1"}, actor="tester")
    assert patched.prefix == "NEWP1"
    with pytest.raises(PrefixTakenError):
        await ts.patch_type(session, key, {"prefix": "OTH1"}, actor="tester")
    with pytest.raises(InvalidGeometryError):
        await ts.patch_type(session, key, {"prefix": "lower"}, actor="tester")
    await _add_sheet(session, key, 1, "NEWP1-0001")
    with pytest.raises(PrefixLockedError) as exc:
        await ts.patch_type(session, key, {"prefix": "THIRD1"}, actor="tester")
    assert exc.value.status == 409
    assert exc.value.error_code == "prefix_taken"
    assert exc.value.detail == {"reason": "sheets_exist"}
    # Writing the unchanged prefix is not a change and stays allowed.
    same = await ts.patch_type(session, key, {"prefix": "NEWP1"}, actor="tester")
    assert same.prefix == "NEWP1"


async def test_archive_and_unarchive(session: AsyncSession) -> None:
    t, _ = await ts.create_type(session, fields(), G_4X12, actor="tester")
    archived = await ts.archive_type(session, t.key, actor="tester")
    assert archived.archived_at is not None
    again = await ts.archive_type(session, t.key, actor="tester")
    assert again.archived_at is not None
    restored = await ts.unarchive_type(session, t.key, actor="tester")
    assert restored.archived_at is None
    with pytest.raises(SheetTypeNotFoundError):
        await ts.archive_type(session, "nope", actor="tester")


async def test_delete_rules(session: AsyncSession) -> None:
    plain, _ = await ts.create_type(session, fields("plain-type", "PLAIN"), G_4X12, actor="t")
    await ts.delete_type(session, plain.key, actor="t")
    with pytest.raises(SheetTypeNotFoundError):
        await ts.get_type(session, "plain-type")
    assert await _version_count(session) == 0  # versions go with the type

    used, _ = await ts.create_type(session, fields("used-type", "USED1"), G_4X12, actor="t")
    await _add_sheet(session, used.key, 1, "USED1-0001")
    with pytest.raises(SheetTypeInUseError) as exc:
        await ts.delete_type(session, used.key, actor="t")
    assert exc.value.status == 409
    assert exc.value.error_code == "type_in_use"
    assert exc.value.detail == {"reason": "has_sheets"}

    for origin, reason in (("seed", "seed_type"), ("imported", "imported_type")):
        key = f"{origin}-type"
        await ts.create_type(
            session, fields(key, origin[:4].upper() + "1"), G_4X12, actor="t", origin=origin
        )  # type: ignore[arg-type]
        with pytest.raises(SheetTypeInUseError) as exc2:
            await ts.delete_type(session, key, actor="t")
        assert exc2.value.detail == {"reason": reason}
        assert (await ts.get_type(session, key)).origin == origin

    with pytest.raises(SheetTypeNotFoundError):
        await ts.delete_type(session, "nope", actor="t")


async def test_list_filters(session: AsyncSession) -> None:
    await ts.create_type(session, fields(), G_4X12, actor="t")
    await ts.create_type(
        session,
        fields("zweckform-small", "ZSM1", vendor="Zweckform", product_codes=["J8651"],
               description="Tiny labels"),
        G_SMALL,
        actor="t",
    )  # fmt: skip
    gone, _ = await ts.create_type(session, fields("old-one", "OLD1"), G_4X12, actor="t")
    await ts.archive_type(session, gone.key, actor="t")

    def keys(rows: list[SheetType]) -> list[str]:
        return sorted(r.key for r in rows)

    kw: dict[str, Any] = {"page": None, "vendor": None, "q": None, "w": None, "h": None}
    both = await ts.list_types(session, include_archived=False, **kw)
    assert keys(both) == ["avery-l4736", "zweckform-small"]
    with_arch = await ts.list_types(session, include_archived=True, **kw)
    assert keys(with_arch) == ["avery-l4736", "old-one", "zweckform-small"]

    size = {**kw, "w": 45.7, "h": 21.2}
    assert keys(await ts.list_types(session, include_archived=False, **size)) == ["avery-l4736"]
    near = {**kw, "w": 46.1, "h": 20.8}  # within +-0.5 mm
    assert keys(await ts.list_types(session, include_archived=False, **near)) == ["avery-l4736"]
    far = {**kw, "w": 46.3, "h": 21.2}  # 0.6 mm off
    assert await ts.list_types(session, include_archived=False, **far) == []
    small = {**kw, "w": 25.4, "h": 10}
    assert keys(await ts.list_types(session, include_archived=False, **small)) == [
        "zweckform-small"
    ]
    only_w = {**kw, "w": 25.4}
    assert keys(await ts.list_types(session, include_archived=False, **only_w)) == [
        "zweckform-small"
    ]

    assert keys(
        await ts.list_types(session, include_archived=False, **{**kw, "vendor": "Avery"})
    ) == ["avery-l4736"]
    assert keys(await ts.list_types(session, include_archived=False, **{**kw, "page": "A4"})) == [
        "avery-l4736",
        "zweckform-small",
    ]
    assert await ts.list_types(session, include_archived=False, **{**kw, "page": "Letter"}) == []
    for q, want in (("L4736", ["avery-l4736"]), ("j8651", ["zweckform-small"]),
                    ("TINY", ["zweckform-small"]), ("small", ["zweckform-small"])):  # fmt: skip
        got = await ts.list_types(session, include_archived=False, **{**kw, "q": q})
        assert keys(got) == want, q


async def test_list_size_tolerance_boundary_is_exact(session: AsyncSession) -> None:
    await ts.create_type(session, fields(), G_4X12, actor="t")  # label 45.70 x 21.20
    kw: dict[str, Any] = {"page": None, "vendor": None, "q": None, "include_archived": False}
    for w in (45.2, 46.2):  # exactly +-0.50 mm: included
        assert [x.key for x in await ts.list_types(session, w=w, h=None, **kw)] == ["avery-l4736"]
    for w in (45.19, 46.21):  # just outside
        assert await ts.list_types(session, w=w, h=None, **kw) == []
    assert [x.key for x in await ts.list_types(session, w=None, h=20.7, **kw)] == ["avery-l4736"]


async def test_list_size_boundary_survives_float_noise(session: AsyncSession) -> None:
    # abs(31.70 - 32.2) is 0.5000000000000036 in floating point; in hundredths it is exactly 50.
    await ts.create_type(session, fields(), replace(G_4X12, label_w=3170), actor="t")
    kw: dict[str, Any] = {"page": None, "vendor": None, "q": None, "include_archived": False}
    assert [x.key for x in await ts.list_types(session, w=32.2, h=None, **kw)] == ["avery-l4736"]


async def test_list_uses_current_version_size(session: AsyncSession) -> None:
    t, _ = await ts.create_type(session, fields(), G_4X12, actor="t")
    await ts.add_version(session, t.key, G_5X12, actor="t", change_note="narrower")
    kw: dict[str, Any] = {"page": None, "vendor": None, "q": None, "h": None}
    old = await ts.list_types(session, w=45.7, include_archived=False, **kw)
    assert old == []  # v1 width no longer matches, only the current version counts
    new = await ts.list_types(session, w=36.0, include_archived=False, **kw)
    assert [x.key for x in new] == ["avery-l4736"]


async def test_write_error_rolls_back(session: AsyncSession) -> None:
    t, _ = await ts.create_type(session, fields(), G_4X12, actor="t")
    with pytest.raises(InvalidGeometryError):
        await ts.add_version(
            session, t.key, replace(G_5X12, cols=500), actor="t", change_note="too many"
        )
    assert await _version_count(session) == 1


async def test_commit_failure_rolls_back(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, _ = await ts.create_type(session, fields(), G_4X12, actor="t")
    key, type_id = t.key, t.id

    async def boom() -> None:
        raise RuntimeError("disk gone")

    monkeypatch.setattr(session, "commit", boom)
    with pytest.raises(RuntimeError):
        await ts.add_version(session, key, G_5X12, actor="t", change_note="x")
    monkeypatch.undo()
    assert await _version_count(session) == 1
    assert (await ts.current_version(session, type_id)).version == 1


async def _lock_seq(session: AsyncSession) -> int:
    row = (await session.execute(text("SELECT seq FROM sheet_write_lock WHERE id = 1"))).first()
    return 0 if row is None else int(row[0])


async def test_every_write_takes_the_write_lock(session: AsyncSession) -> None:
    """Each writing call bumps the lock row; a rejected call leaves it unchanged."""
    seen = [await _lock_seq(session)]
    t, _ = await ts.create_type(session, fields(), G_4X12, actor="t")
    seen.append(await _lock_seq(session))
    await ts.patch_type(session, t.key, {"notes": "n"}, actor="t")
    seen.append(await _lock_seq(session))
    await ts.add_version(session, t.key, G_5X12, actor="t", change_note="v2")
    seen.append(await _lock_seq(session))
    await ts.archive_type(session, t.key, actor="t")
    seen.append(await _lock_seq(session))
    await ts.unarchive_type(session, t.key, actor="t")
    seen.append(await _lock_seq(session))
    await ts.delete_type(session, t.key, actor="t")
    seen.append(await _lock_seq(session))
    assert seen == sorted(set(seen)), seen  # strictly increasing: one bump per call
    before = await _lock_seq(session)
    with pytest.raises(SheetTypeNotFoundError):
        await ts.archive_type(session, "nope", actor="t")
    assert await _lock_seq(session) == before  # the rollback undid the bump


# --- free text is sanitised (Task 6 retrofit) ------------------------------------------


async def test_create_sanitises_free_text(session: AsyncSession) -> None:
    t, v = await ts.create_type(
        session,
        fields(
            vendor=" Av\x07ery‮ ",
            description="Address⁦ labels",
            product_codes=["L4736\x00REV-25", "‎L4736"],
            source_name="Data‏sheet",
            notes="Measured\x1b by hand \U0001f468‍\U0001f469",
        ),
        G_4X12,
        actor="tester",
        change_note="first\x07 cut",
    )
    stored = await ts.get_type(session, t.key)
    assert stored.vendor == "Avery"
    assert stored.description == "Address labels"
    assert stored.product_codes == ["L4736REV-25", "L4736"]
    assert stored.source_name == "Datasheet"
    assert stored.notes == "Measured by hand \U0001f468‍\U0001f469"
    assert v.change_note == "first cut"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("vendor", "x" * 201),
        ("description", "x" * 201),
        ("source_name", "x" * 201),
        ("notes", "x" * 2001),
        ("product_codes", ["x" * 41]),
    ],
)
async def test_create_refuses_over_long_text(session: AsyncSession, field: str, value: Any) -> None:
    with pytest.raises(InvalidGeometryError) as exc:
        await ts.create_type(session, fields(**{field: value}), G_4X12, actor="tester")
    assert exc.value.status == 422
    assert exc.value.detail == {"field": field, "reason": "too long"}
    assert await _version_count(session) == 0


async def test_patch_sanitises_and_refuses_over_long_text(session: AsyncSession) -> None:
    t, _ = await ts.create_type(session, fields(), G_4X12, actor="tester")
    key = t.key
    patched = await ts.patch_type(
        session,
        key,
        {"notes": "ok‪\x07", "product_codes": ["A⁩B"], "vendor": "\x07"},
        actor="tester",
    )
    assert (patched.notes, patched.product_codes, patched.vendor) == ("ok", ["AB"], None)
    with pytest.raises(InvalidGeometryError) as exc:
        await ts.patch_type(
            session, key, {"description": "fine", "notes": "y" * 2001}, actor="tester"
        )
    assert exc.value.detail == {"field": "notes", "reason": "too long"}
    stored = await ts.get_type(session, key)
    assert stored.notes == "ok" and stored.description == "Address labels"


async def test_add_version_sanitises_and_refuses_over_long_change_note(
    session: AsyncSession,
) -> None:
    t, _ = await ts.create_type(session, fields(), G_4X12, actor="tester")
    v = await ts.add_version(session, t.key, G_5X12, actor="tester", change_note="5‮ cols")
    assert v.change_note == "5 cols"
    with pytest.raises(InvalidGeometryError) as exc:
        await ts.add_version(session, t.key, G_SMALL, actor="tester", change_note="z" * 501)
    assert exc.value.detail == {"field": "change_note", "reason": "too long"}
    assert await _version_count(session) == 2


async def test_text_that_cleans_to_nothing_is_null_and_empty_codes_are_dropped(
    session: AsyncSession,
) -> None:
    t, v = await ts.create_type(
        session,
        fields(
            vendor="\x07\x08",
            description="  ",
            source_name="‮",
            notes="\x1b",
            product_codes=["\x07", "A1", "", "‎"],
        ),
        G_4X12,
        actor="tester",
        change_note="\x07",
    )
    stored = await ts.get_type(session, t.key)
    assert (stored.vendor, stored.description, stored.source_name, stored.notes) == (None,) * 4
    assert stored.product_codes == ["A1"]
    assert v.change_note is None
    patched = await ts.patch_type(
        session, t.key, {"description": "x", "product_codes": ["\x07"]}, actor="tester"
    )
    assert patched.product_codes == []
    cleared = await ts.patch_type(session, t.key, {"description": "\x07"}, actor="tester")
    assert cleared.description is None


async def test_add_version_refuses_a_change_note_that_cleans_to_nothing(
    session: AsyncSession,
) -> None:
    t, _ = await ts.create_type(session, fields(), G_4X12, actor="tester")
    with pytest.raises(InvalidGeometryError) as exc:
        await ts.add_version(session, t.key, G_5X12, actor="tester", change_note="\x07 ")
    assert exc.value.detail == {"field": "change_note", "reason": "must not be empty"}
    assert await _version_count(session) == 1


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "ftp://example.invalid/x", "https://", "https://a b", "/rel"]
)
async def test_source_url_must_be_http_on_create_and_patch(session: AsyncSession, url: str) -> None:
    with pytest.raises(InvalidGeometryError) as exc:
        await ts.create_type(session, fields(source_url=url), G_4X12, actor="tester")
    assert exc.value.detail is not None and exc.value.detail["field"] == "source_url"
    t, _ = await ts.create_type(session, fields(), G_4X12, actor="tester")
    with pytest.raises(InvalidGeometryError):
        await ts.patch_type(session, t.key, {"source_url": url}, actor="tester")
    ok = await ts.patch_type(
        session, t.key, {"source_url": "https://example.invalid/sheet"}, actor="tester"
    )
    assert ok.source_url == "https://example.invalid/sheet"
    cleared = await ts.patch_type(session, t.key, {"source_url": None}, actor="tester")
    assert cleared.source_url is None


async def test_source_url_over_500_characters_is_refused(session: AsyncSession) -> None:
    with pytest.raises(InvalidGeometryError) as exc:
        await ts.create_type(
            session, fields(source_url="https://e.invalid/" + "a" * 500), G_4X12, actor="tester"
        )
    assert exc.value.detail == {"field": "source_url", "reason": "too long"}


async def test_service_refuses_more_than_fifty_product_codes(session: AsyncSession) -> None:
    many = [f"P-{i}" for i in range(51)]
    with pytest.raises(InvalidFieldError) as exc:
        await ts.create_type(session, fields(product_codes=many), G_4X12, actor="tester")
    assert exc.value.detail == {"field": "product_codes", "reason": "too many"}
    t, _ = await ts.create_type(session, fields(product_codes=many[:50]), G_4X12, actor="tester")
    with pytest.raises(InvalidFieldError):
        await ts.patch_type(session, t.key, {"product_codes": many}, actor="tester")
