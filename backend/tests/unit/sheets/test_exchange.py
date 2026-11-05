"""Sheet type export and import (Plan 1, Task 4)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from app.models.sheet import SheetType, SheetTypeVersion
from app.sheets import exchange
from app.sheets import type_service as ts
from app.sheets.errors import (
    ImportTooLargeError,
    InvalidImportError,
    PrefixTakenError,
    TypeExistsError,
)
from app.sheets.geometry import Geometry
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

# L4736-like: 4 x 12 labels of 45.7 x 21.2 mm on A4.
G = Geometry(
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
    corner_radius=150,
    shape="rectangle",
)
G_V2 = replace(G, label_w=3600, cols=5, pitch_x=4000, margin_left=500)


@pytest_asyncio.fixture
async def session(async_session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[Any]:
    async with async_session_factory() as s:
        yield s


@pytest_asyncio.fixture
async def other_session(tmp_path: Path) -> AsyncIterator[AsyncSession]:
    """A second, empty database: 'another hub'."""
    import app.models  # noqa: F401

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'other.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


def _fields(key: str = "avery-l4736", prefix: str = "L4736") -> ts.TypeFields:
    return ts.TypeFields(
        key=key,
        prefix=prefix,
        vendor="Avery",
        product_codes=["L4736REV-25"],
        description="Address labels",
        allow_qr=True,
        source_name="Vendor datasheet",
        source_url="https://example.com/l4736",
        notes="Measured by hand.",
    )


async def _counts(session: AsyncSession) -> tuple[int, int]:
    types = (await session.execute(select(func.count()).select_from(SheetType))).scalar_one()
    versions = (
        await session.execute(select(func.count()).select_from(SheetTypeVersion))
    ).scalar_one()
    return int(types), int(versions)


def _doc_dict(doc: exchange.ExportDoc) -> dict[str, Any]:
    return json.loads(doc.model_dump_json())


def _raw(d: dict[str, Any]) -> bytes:
    return json.dumps(d).encode()


async def _base_doc(session: AsyncSession) -> dict[str, Any]:
    await ts.create_type(session, _fields(), G, actor="tester")
    return _doc_dict(await exchange.export_type(session, "avery-l4736", None))


async def test_export_document_shape(session: AsyncSession) -> None:
    await ts.create_type(session, _fields(), G, actor="tester")
    await ts.add_version(session, "avery-l4736", G_V2, actor="tester", change_note="five columns")
    current = _doc_dict(await exchange.export_type(session, "avery-l4736", None))
    first = _doc_dict(await exchange.export_type(session, "avery-l4736", 1))
    assert current["format"] == "label-printer-hub.sheet-type"
    assert current["format_version"] == 1
    assert current["version"]["version"] == 2
    assert first["version"]["version"] == 1
    assert first["version"]["geometry"]["label_w"] == 45.7
    assert first["version"]["geometry"]["margin_left"] == 8.4
    assert first["type"]["key"] == "avery-l4736"
    assert first["type"]["prefix"] == "L4736"
    assert isinstance(first["exported_by_hub"], str)
    assert set(first) == {
        "format",
        "format_version",
        "type",
        "version",
        "exported_at",
        "exported_by_hub",
    }  # no sheet data


async def test_export_unknown_type_or_version(session: AsyncSession) -> None:
    from app.sheets.errors import SheetTypeNotFoundError

    with pytest.raises(SheetTypeNotFoundError):
        await exchange.export_type(session, "nope-nope", None)
    await ts.create_type(session, _fields(), G, actor="tester")
    with pytest.raises(SheetTypeNotFoundError):
        await exchange.export_type(session, "avery-l4736", 7)


def test_geometry_doc_roundtrip() -> None:
    mm = exchange.geometry_to_doc(G)
    assert exchange.geometry_from_doc(mm) == G
    assert mm.label_w == 45.7


async def test_roundtrip_identical_hash(session: AsyncSession, other_session: AsyncSession) -> None:
    await ts.create_type(session, replace(_fields(), verified=True), G, actor="tester")
    exported = _doc_dict(await exchange.export_type(session, "avery-l4736", None))
    assert exported["type"]["verified"] is True
    doc = exchange.parse_import(_raw(exported))
    result = await exchange.import_type(other_session, doc, actor="importer")
    assert (result.outcome, result.key, result.version) == ("created", "avery-l4736", 1)
    original = await ts.get_version(session, "avery-l4736", 1)
    imported = await ts.get_version(other_session, "avery-l4736", 1)
    assert imported.geometry_hash == original.geometry_hash  # acceptance 10
    t = await ts.get_type(other_session, "avery-l4736")
    assert t.origin == "imported"
    assert t.prefix == "L4736"
    assert t.created_by == "importer"
    assert t.verified is False  # a stranger's claim is not a verification


async def test_import_same_geometry_unchanged(session: AsyncSession) -> None:
    d = await _base_doc(session)
    before = await _counts(session)
    result = await exchange.import_type(session, exchange.parse_import(_raw(d)), actor="importer")
    assert (result.outcome, result.key, result.version) == ("unchanged", "avery-l4736", 1)
    assert await _counts(session) == before


async def test_import_unchanged_names_the_matching_older_version(session: AsyncSession) -> None:
    d = await _base_doc(session)  # exported at version 1
    await ts.add_version(session, "avery-l4736", G_V2, actor="tester", change_note="five columns")
    result = await exchange.import_type(session, exchange.parse_import(_raw(d)), actor="importer")
    assert (result.outcome, result.version) == ("unchanged", 1)
    assert await _counts(session) == (1, 2)


def _changed(d: dict[str, Any]) -> dict[str, Any]:
    d = json.loads(json.dumps(d))
    d["version"]["geometry"].update(label_w=36.0, cols=5, pitch_x=40.0, margin_left=5.0)
    return d


async def test_import_changed_geometry_strict_conflict(session: AsyncSession) -> None:
    d = _changed(await _base_doc(session))
    doc = exchange.parse_import(_raw(d))
    with pytest.raises(TypeExistsError):
        await exchange.import_type(session, doc, actor="importer")
    assert await _counts(session) == (1, 1)

    as_new = await exchange.import_type(
        session, doc, mode="as_new_key", new_key="my-l4736", new_prefix="ML4736", actor="importer"
    )
    assert (as_new.outcome, as_new.key, as_new.version) == ("created_as_new_key", "my-l4736", 1)
    t = await ts.get_type(session, "my-l4736")
    assert (t.origin, t.prefix) == ("imported", "ML4736")

    added = await exchange.import_type(session, doc, mode="new_version", actor="importer")
    assert (added.outcome, added.key, added.version) == ("version_added", "avery-l4736", 2)
    v2 = await ts.get_version(session, "avery-l4736", 2)
    assert (v2.cols, v2.created_by) == (5, "importer")

    # the same document again is now identical to version 2: nothing is written
    again = await exchange.import_type(session, doc, mode="new_version", actor="importer")
    assert (again.outcome, again.version) == ("unchanged", 2)
    assert await _counts(session) == (2, 3)


async def test_as_new_key_needs_key_and_free_prefix(session: AsyncSession) -> None:
    doc = exchange.parse_import(_raw(_changed(await _base_doc(session))))
    before = await _counts(session)
    with pytest.raises(InvalidImportError):
        await exchange.import_type(session, doc, mode="as_new_key", actor="importer")
    with pytest.raises(PrefixTakenError):  # the prefix of the document is still taken
        await exchange.import_type(
            session, doc, mode="as_new_key", new_key="my-l4736", actor="importer"
        )
    with pytest.raises(TypeExistsError):
        await exchange.import_type(
            session,
            doc,
            mode="as_new_key",
            new_key="avery-l4736",
            new_prefix="ML4736",
            actor="importer",
        )
    assert await _counts(session) == before


async def test_import_prefix_taken(session: AsyncSession) -> None:
    await ts.create_type(session, _fields("other-type", "L4736"), G, actor="tester")
    other = _doc_dict(await exchange.export_type(session, "other-type", None))
    other["type"]["key"] = "avery-l4736"  # a new key, but the prefix belongs to other-type
    doc = exchange.parse_import(_raw(other))
    with pytest.raises(PrefixTakenError):
        await exchange.import_type(session, doc, actor="importer")
    assert await _counts(session) == (1, 1)
    result = await exchange.import_type(session, doc, new_prefix="ML4736", actor="importer")
    assert (result.outcome, result.key) == ("created", "avery-l4736")
    assert (await ts.get_type(session, "avery-l4736")).prefix == "ML4736"


async def test_import_existing_key_with_other_prefix_changes_nothing(
    session: AsyncSession,
) -> None:
    d = _changed(await _base_doc(session))
    d["type"]["prefix"] = "OTHER1"
    with pytest.raises(TypeExistsError):
        await exchange.import_type(session, exchange.parse_import(_raw(d)), actor="importer")
    assert (await ts.get_type(session, "avery-l4736")).prefix == "L4736"
    assert await _counts(session) == (1, 1)


def _mutate(path: list[str], value: Any) -> Any:
    def apply(d: dict[str, Any]) -> bytes:
        node = d
        for part in path[:-1]:
            node = node[part]
        node[path[-1]] = value
        return _raw(d)

    return apply


def _drop(path: list[str]) -> Any:
    def apply(d: dict[str, Any]) -> bytes:
        node = d
        for part in path[:-1]:
            node = node[part]
        del node[path[-1]]
        return _raw(d)

    return apply


def _nan(d: dict[str, Any]) -> bytes:
    return _raw(d).replace(b'"margin_top": 21.5', b'"margin_top": NaN')


def _infinity(d: dict[str, Any]) -> bytes:
    return _raw(d).replace(b'"margin_top": 21.5', b'"margin_top": Infinity')


def _deep_notes(d: dict[str, Any]) -> bytes:
    d["type"]["notes"] = json.loads("[" * 400 + "]" * 400)
    return _raw(d)


REJECTED: list[tuple[str, Any, type[Exception]]] = [
    ("oversize", lambda d: b" " * (exchange.MAX_IMPORT_BYTES + 1), ImportTooLargeError),
    ("top_level_list", lambda d: b"[]", InvalidImportError),
    ("top_level_scalar", lambda d: b"42", InvalidImportError),
    ("empty", lambda d: b"", InvalidImportError),
    ("not_utf8", lambda d: b"\xff\xfe\x00\x01", InvalidImportError),
    ("not_json", lambda d: b"{nope", InvalidImportError),
    ("unknown_type_field", _mutate(["type", "colour"], "red"), InvalidImportError),
    ("unknown_top_field", _mutate(["extra"], 1), InvalidImportError),
    ("unknown_geometry_field", _mutate(["version", "geometry", "bleed"], 1.0), InvalidImportError),
    ("format_version_2", _mutate(["format_version"], 2), InvalidImportError),
    ("format_wrong", _mutate(["format"], "other.format"), InvalidImportError),
    ("three_decimals", _mutate(["version", "geometry", "margin_top"], 9.855), InvalidImportError),
    ("negative_length", _mutate(["version", "geometry", "label_w"], -1), InvalidImportError),
    ("huge_length", _mutate(["version", "geometry", "label_w"], 1e300), InvalidImportError),
    ("string_length", _mutate(["version", "geometry", "label_w"], "45.7"), InvalidImportError),
    ("bool_length", _mutate(["version", "geometry", "label_w"], True), InvalidImportError),
    ("null_length", _mutate(["version", "geometry", "label_w"], None), InvalidImportError),
    ("nan_literal", _nan, InvalidImportError),
    ("infinity_literal", _infinity, InvalidImportError),
    ("nested_depth_bomb", lambda d: b"[" * 32000 + b"]" * 32000, InvalidImportError),
    ("nested_notes", _deep_notes, InvalidImportError),
    ("javascript_url", _mutate(["type", "source_url"], "javascript:alert(1)"), InvalidImportError),
    ("data_url", _mutate(["type", "source_url"], "data:text/html,x"), InvalidImportError),
    (
        "url_too_long",
        _mutate(["type", "source_url"], "https://e.com/" + "a" * 500),
        InvalidImportError,
    ),
    ("key_too_long", _mutate(["type", "key"], "a" * 65), InvalidImportError),
    ("key_bad_pattern", _mutate(["type", "key"], "Bad Key"), InvalidImportError),
    ("prefix_bad_pattern", _mutate(["type", "prefix"], "bad"), InvalidImportError),
    ("vendor_too_long", _mutate(["type", "vendor"], "v" * 201), InvalidImportError),
    ("description_too_long", _mutate(["type", "description"], "d" * 201), InvalidImportError),
    ("source_name_too_long", _mutate(["type", "source_name"], "s" * 201), InvalidImportError),
    ("notes_too_long", _mutate(["type", "notes"], "n" * 2001), InvalidImportError),
    ("too_many_codes", _mutate(["type", "product_codes"], ["c"] * 51), InvalidImportError),
    ("code_too_long", _mutate(["type", "product_codes"], ["c" * 41]), InvalidImportError),
    ("codes_not_strings", _mutate(["type", "product_codes"], [1, 2]), InvalidImportError),
    ("bad_page_size", _mutate(["version", "geometry", "page_size"], "A3"), InvalidImportError),
    ("bad_shape", _mutate(["version", "geometry", "shape"], "oval"), InvalidImportError),
    ("missing_geometry", _drop(["version", "geometry"]), InvalidImportError),
    ("version_zero", _mutate(["version", "version"], 0), InvalidImportError),
    # fails validate_geometry: the grid is wider than the page
    ("grid_wider_than_page", _mutate(["version", "geometry", "cols"], 9), InvalidImportError),
    # fails validate_geometry: round labels must be square
    ("round_not_square", _mutate(["version", "geometry", "shape"], "round"), InvalidImportError),
    # fails validate_geometry: page size does not match the stated page width
    ("page_width_mismatch", _mutate(["version", "geometry", "page_w"], 200.0), InvalidImportError),
]


@pytest.mark.parametrize(("name", "build", "error"), REJECTED, ids=[r[0] for r in REJECTED])
async def test_import_rejects(
    session: AsyncSession, name: str, build: Any, error: type[Exception]
) -> None:
    d = await _base_doc(session)
    d["type"]["key"] = "fresh-key"  # would be created if it were accepted
    d["type"]["prefix"] = "FRESH1"
    before = await _counts(session)
    raw = build(d)
    with pytest.raises(error):
        doc = exchange.parse_import(raw)
        # a document that parses must not slip through the write path either
        await exchange.import_type(session, doc, actor="importer")
    assert await _counts(session) == before


async def test_duplicate_object_keys_rejected(session: AsyncSession) -> None:
    # a complete, otherwise valid document: only the repeated key makes it invalid
    d = await _base_doc(session)
    raw = _raw(d).replace(b'"format_version": 1', b'"format_version": 2, "format_version": 1')
    assert raw != _raw(d)
    with pytest.raises(InvalidImportError):
        exchange.parse_import(raw)
    exchange.parse_import(_raw(d))  # the untouched document is accepted


def test_oversize_checked_before_parsing() -> None:
    # not even valid JSON: the size check must come first
    with pytest.raises(ImportTooLargeError):
        exchange.parse_import(b"{" * (exchange.MAX_IMPORT_BYTES + 1))
    assert exchange.MAX_IMPORT_BYTES == 65536


def test_error_http_shape() -> None:
    too_large = ImportTooLargeError().to_http()
    assert too_large.status_code == 413
    d: dict[str, Any] = too_large.detail  # type: ignore[assignment]
    assert d["error_code"] == "import_too_large"
    invalid = InvalidImportError(["type.key"]).to_http()
    assert invalid.status_code == 422
    inv: dict[str, Any] = invalid.detail  # type: ignore[assignment]
    assert inv["error_code"] == "invalid_import"
    assert inv["error_detail"] == {"errors": ["type.key"]}


@pytest.mark.parametrize("where", ["field_name", "field_value"])
async def test_import_error_detail_has_no_input_values(session: AsyncSession, where: str) -> None:
    d = await _base_doc(session)
    if where == "field_name":
        d["type"]["<script>"] = "<script>"
    else:
        d["type"]["vendor"] = ["<script>"]
        d["version"]["geometry"]["label_w"] = "<script>"
    with pytest.raises(InvalidImportError) as info:
        exchange.parse_import(_raw(d))
    rendered = json.dumps(info.value.to_http().detail)
    assert "<script>" not in rendered
    assert "script" not in rendered
    assert info.value.detail is not None
    assert info.value.detail["errors"]


async def test_error_detail_names_the_field_path(session: AsyncSession) -> None:
    d = await _base_doc(session)
    d["version"]["geometry"]["margin_top"] = 9.855
    with pytest.raises(InvalidImportError) as info:
        exchange.parse_import(_raw(d))
    assert info.value.detail == {"errors": ["version.geometry.margin_top"]}


async def test_concurrent_identical_imports_one_creates_rest_unchanged(
    async_session_factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    """Review Important 1: the decision is taken under the write lock (no read-then-upgrade)."""
    import asyncio

    from sqlalchemy import text

    await session.execute(text("PRAGMA journal_mode=WAL"))  # the production mode
    await ts.create_type(session, _fields("seed-type", "SEED1"), G, actor="tester")
    d = _doc_dict(await exchange.export_type(session, "seed-type", None))
    d["type"]["key"] = "racing-type"
    d["type"]["prefix"] = "RACE1"
    doc = exchange.parse_import(_raw(d))

    async def one() -> exchange.ImportResult:
        async with async_session_factory() as s:
            return await exchange.import_type(s, doc, actor="importer")

    results = await asyncio.gather(*(one() for _ in range(6)))
    assert sorted(r.outcome for r in results) == ["created"] + ["unchanged"] * 5
    assert {r.version for r in results} == {1}
    assert await _counts(session) == (2, 2)


async def test_concurrent_new_version_imports_add_exactly_one_version(
    async_session_factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    import asyncio

    from sqlalchemy import text

    await session.execute(text("PRAGMA journal_mode=WAL"))
    doc = exchange.parse_import(_raw(_changed(await _base_doc(session))))

    async def one() -> exchange.ImportResult:
        async with async_session_factory() as s:
            return await exchange.import_type(s, doc, mode="new_version", actor="importer")

    results = await asyncio.gather(*(one() for _ in range(5)))
    assert sorted(r.outcome for r in results) == ["unchanged"] * 4 + ["version_added"]
    assert {r.version for r in results} == {2}
    assert await _counts(session) == (1, 2)


async def test_unchanged_path_releases_the_lock(
    async_session_factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    doc = exchange.parse_import(_raw(await _base_doc(session)))
    async with async_session_factory() as a:
        assert (await exchange.import_type(a, doc, actor="x")).outcome == "unchanged"
        # session `a` is still open; another writer must not be blocked by it
        await ts.create_type(session, _fields("second-one", "SECOND1"), G, actor="tester")


async def test_identical_geometry_with_other_prefix_is_unchanged(session: AsyncSession) -> None:
    """Spec 9.3 / OC-12: identical geometry changes nothing, whatever the prefix says."""
    d = await _base_doc(session)
    d["type"]["prefix"] = "OTHER1"
    result = await exchange.import_type(session, exchange.parse_import(_raw(d)), actor="importer")
    assert (result.outcome, result.version) == ("unchanged", 1)
    assert (await ts.get_type(session, "avery-l4736")).prefix == "L4736"
    assert await _counts(session) == (1, 1)


async def test_new_key_with_unknown_key_is_refused(session: AsyncSession) -> None:
    d = await _base_doc(session)
    d["type"]["key"] = "fresh-key"
    d["type"]["prefix"] = "FRESH1"
    doc = exchange.parse_import(_raw(d))
    before = await _counts(session)
    with pytest.raises(InvalidImportError) as info:
        await exchange.import_type(session, doc, mode="as_new_key", new_key="other-key", actor="i")
    assert info.value.detail == {"errors": ["new_key"]}
    assert await _counts(session) == before


async def test_failure_after_flush_leaves_no_partial_rows(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = await _base_doc(session)
    d["type"]["key"] = "fresh-key"
    d["type"]["prefix"] = "FRESH1"
    doc = exchange.parse_import(_raw(d))

    def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("version insert failed")

    monkeypatch.setattr(ts, "_new_version", boom)  # runs after the type row was flushed
    before = await _counts(session)
    with pytest.raises(RuntimeError):
        await exchange.import_type(session, doc, actor="importer")
    assert await _counts(session) == before
    monkeypatch.undo()
    assert (await exchange.import_type(session, doc, actor="i")).outcome == "created"


async def test_new_key_outside_as_new_key_mode_is_refused(session: AsyncSession) -> None:
    doc = exchange.parse_import(_raw(_changed(await _base_doc(session))))
    for mode in ("strict", "new_version"):
        with pytest.raises(InvalidImportError):
            await exchange.import_type(session, doc, mode=mode, new_key="x-key", actor="i")  # type: ignore[arg-type]
    assert await _counts(session) == (1, 1)


# --- free text is sanitised (Task 6 retrofit) ------------------------------------------


async def test_import_sanitises_free_text(session: AsyncSession) -> None:
    d = await _base_doc(session)
    d["type"].update(
        key="dirty-type",
        prefix="DIRTY",
        vendor="Av\u0007ery‮",
        description="Labels⁧",
        product_codes=["L47\u001b36"],
        source_name="‎Sheet",
        notes="  note\u0000 ‍ ",
    )
    result = await exchange.import_type(session, exchange.parse_import(_raw(d)), actor="x")
    assert result.outcome == "created"
    t = await ts.get_type(session, "dirty-type")
    assert (t.vendor, t.description, t.product_codes, t.source_name, t.notes) == (
        "Avery",
        "Labels",
        ["L4736"],
        "Sheet",
        "note ‍",
    )
    # the export of the cleaned type carries the cleaned text
    again = await exchange.export_type(session, "dirty-type", None)
    assert again.type.vendor == "Avery"


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
async def test_import_refuses_over_long_text(session: AsyncSession, field: str, value: Any) -> None:
    d = await _base_doc(session)
    d["type"].update(key="long-type", prefix="LONG", **{field: value})
    before = await _counts(session)
    with pytest.raises(InvalidImportError):
        exchange.parse_import(_raw(d))
    assert await _counts(session) == before


async def test_as_new_key_creates_the_key_even_for_identical_geometry(
    session: AsyncSession,
) -> None:
    """A requested copy is made; OC-12's "identical changes nothing" is for the other modes."""
    d = await _base_doc(session)
    doc = exchange.parse_import(_raw(d))
    result = await exchange.import_type(
        session, doc, mode="as_new_key", new_key="my-copy", new_prefix="MYCOPY", actor="importer"
    )
    assert (result.outcome, result.key, result.version) == ("created_as_new_key", "my-copy", 1)
    assert await _counts(session) == (2, 2)
