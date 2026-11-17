# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Sheet type export and import (spec 9.2, 9.3, OC-12).

One JSON document per type and version, all lengths in millimetres. Import treats the document
as hostile input: size check first, strict schema, the geometry rules of ``validate_geometry``,
and error details that name field paths only, never input values.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sheet import SheetType
from app.repositories import sheet_types as repo
from app.sheets import type_service as ts
from app.sheets.errors import (
    BackingDesignNotFoundError,
    BackingDesignPageSizeMismatchError,
    IdCellOutOfRangeError,
    ImportTooLargeError,
    InvalidGeometryError,
    InvalidImportError,
    TypeExistsError,
)
from app.sheets.geometry import (
    PAGE_SIZES,
    Geometry,
    geometry_hash,
    hmm_to_mm,
    mm_to_hmm,
    validate_geometry,
)
from app.sheets.naming import KEY_PATTERN, PREFIX_PATTERN
from app.sheets.text import check_http_url

logger = logging.getLogger(__name__)

MAX_IMPORT_BYTES = 65536
_MAX_REPORTED_ERRORS = 20
_MAX_MM = 1000.0  # far beyond any sheet; keeps hostile magnitudes out of the converter

_Mm = Annotated[float, Field(strict=True, ge=0, le=_MAX_MM, allow_inf_nan=False)]
_Mm_opt = Annotated[float | None, Field(strict=True, ge=0, le=_MAX_MM, allow_inf_nan=False)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GeometryMm(_Strict):
    page_size: Literal["A4", "Letter"]
    page_w: _Mm_opt = None  # derived from the page size when left out
    page_h: _Mm_opt = None
    label_w: _Mm
    label_h: _Mm
    cols: Annotated[int, Field(strict=True, ge=1, le=400)]
    rows: Annotated[int, Field(strict=True, ge=1, le=400)]
    pitch_x: _Mm
    pitch_y: _Mm
    margin_top: _Mm
    margin_left: _Mm
    corner_radius: _Mm_opt = None
    shape: Literal["rectangle", "round"]


class StripMm(_Strict):
    """A free strip on the back of the liner, in mm, in back-side coordinates (R-350-4)."""

    x_mm: _Mm
    y_mm: _Mm
    w_mm: _Mm
    h_mm: _Mm


MAX_STRIPS = 8


class BackingDesignDoc(_Strict):
    """A backing design inside a sheet type document (R-350-8)."""

    key: Annotated[str, Field(max_length=64, pattern=KEY_PATTERN.pattern)]
    name: Annotated[str, Field(min_length=1, max_length=200)]
    page_size: Literal["A4", "Letter"]
    strips: Annotated[list[StripMm], Field(max_length=MAX_STRIPS)]


# The keys a version-2 document adds to ``type`` (#350). Export writes them only when they are
# not the default, so an untouched type stays a version-1 document an older hub still imports.
PLACEMENT_KEYS = ("id_placement", "id_cell", "backing_design")


class TypeDoc(_Strict):
    key: Annotated[str, Field(max_length=64, pattern=KEY_PATTERN.pattern)]
    prefix: Annotated[str, Field(max_length=10, pattern=PREFIX_PATTERN.pattern)]
    vendor: Annotated[str, Field(max_length=200)] | None = None
    product_codes: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=40)]], Field(max_length=50)
    ] = []
    description: Annotated[str, Field(max_length=200)] | None = None
    allow_qr: bool
    verified: bool = False
    source_name: Annotated[str, Field(max_length=200)] | None = None
    source_url: Annotated[str, Field(max_length=500)] | None = None
    notes: Annotated[str, Field(max_length=2000)] | None = None
    id_placement: Literal["auto", "margin", "back_side", "cell"] = "auto"
    id_cell: Annotated[int, Field(strict=True, ge=1, le=10000)] | None = None
    backing_design: BackingDesignDoc | None = None

    @field_validator("source_url")
    @classmethod
    def _http_only(cls, value: str | None) -> str | None:
        return None if value is None else check_http_url(value)


class VersionDoc(_Strict):
    version: Annotated[int, Field(strict=True, ge=1, le=1_000_000)]
    geometry: GeometryMm


class ExportDoc(_Strict):
    format: Literal["label-printer-hub.sheet-type"]
    format_version: Literal[1, 2]
    type: TypeDoc
    version: VersionDoc
    exported_at: datetime
    exported_by_hub: Annotated[str, Field(max_length=64)]

    @model_validator(mode="after")
    def _version_1_has_no_placement(self) -> ExportDoc:
        """A version-1 document carries none of the version-2 keys (R-350-8)."""
        if self.format_version == 1 and self.type.model_fields_set & set(PLACEMENT_KEYS):
            raise ValueError("format_version 1 does not know id_placement or backing_design")
        return self

    def to_json(self) -> dict[str, Any]:
        """The document as JSON: the version-2 keys only when they carry something."""
        data = self.model_dump(mode="json")
        defaults = {"id_placement": "auto", "id_cell": None, "backing_design": None}
        for name, default in defaults.items():
            if data["type"].get(name) == default:
                del data["type"][name]
        return data


@dataclass
class ImportResult:
    outcome: Literal["created", "unchanged", "version_added", "created_as_new_key"]
    key: str
    version: int


def geometry_to_doc(g: Geometry) -> GeometryMm:
    return GeometryMm(
        page_size=g.page_size,
        page_w=hmm_to_mm(g.page_w),
        page_h=hmm_to_mm(g.page_h),
        label_w=hmm_to_mm(g.label_w),
        label_h=hmm_to_mm(g.label_h),
        cols=g.cols,
        rows=g.rows,
        pitch_x=hmm_to_mm(g.pitch_x),
        pitch_y=hmm_to_mm(g.pitch_y),
        margin_top=hmm_to_mm(g.margin_top),
        margin_left=hmm_to_mm(g.margin_left),
        corner_radius=None if g.corner_radius is None else hmm_to_mm(g.corner_radius),
        shape=g.shape,
    )


def geometry_from_doc(g: GeometryMm) -> Geometry:
    """Convert millimetres to hundredths (D16); more than two decimals is refused."""
    table_w, table_h = PAGE_SIZES[g.page_size]
    return Geometry(
        page_size=g.page_size,
        page_w=table_w if g.page_w is None else mm_to_hmm(g.page_w, field="page_w"),
        page_h=table_h if g.page_h is None else mm_to_hmm(g.page_h, field="page_h"),
        label_w=mm_to_hmm(g.label_w, field="label_w"),
        label_h=mm_to_hmm(g.label_h, field="label_h"),
        cols=g.cols,
        rows=g.rows,
        pitch_x=mm_to_hmm(g.pitch_x, field="pitch_x"),
        pitch_y=mm_to_hmm(g.pitch_y, field="pitch_y"),
        margin_top=mm_to_hmm(g.margin_top, field="margin_top"),
        margin_left=mm_to_hmm(g.margin_left, field="margin_left"),
        corner_radius=(
            None if g.corner_radius is None else mm_to_hmm(g.corner_radius, field="corner_radius")
        ),
        shape=g.shape,
    )


async def export_type(session: AsyncSession, key: str, version: int | None) -> ExportDoc:
    from app.main import HUB_VERSION  # deferred: app.main imports the routers

    t = await ts.get_type(session, key)
    v = (
        await ts.current_version(session, t.id)
        if version is None
        else await ts.get_version(session, key, version)
    )
    placement: dict[str, Any] = {}
    if t.id_placement != "auto":
        placement["id_placement"] = t.id_placement
    if t.id_cell is not None:
        placement["id_cell"] = t.id_cell
    if t.backing_design_id is not None:
        from app.models.backing_design import BackingDesign
        from app.sheets.backing_design_service import to_doc

        design = await session.get(BackingDesign, t.backing_design_id)
        if design is not None:
            placement["backing_design"] = to_doc(design)
    return ExportDoc(
        format="label-printer-hub.sheet-type",
        # R-350-8: an untouched type stays a version-1 document an older hub still imports.
        format_version=2 if placement else 1,
        type=TypeDoc(
            key=t.key,
            prefix=t.prefix,
            vendor=t.vendor,
            product_codes=list(t.product_codes),
            description=t.description,
            allow_qr=t.allow_qr,
            verified=t.verified,
            source_name=t.source_name,
            source_url=t.source_url,
            notes=t.notes,
            **placement,
        ),
        version=VersionDoc(version=v.version, geometry=geometry_to_doc(ts.version_geometry(v))),
        exported_at=datetime.now(UTC),
        exported_by_hub=HUB_VERSION[:64],
    )


def _refuse_constant(_name: str) -> Any:
    raise ValueError("non-finite number")


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for k, v in pairs:
        if k in result:
            raise ValueError("duplicate object key")
        result[k] = v
    return result


def _error_paths(exc: ValidationError) -> list[str]:
    """Field paths only. Names the client chose (unknown fields) are never echoed."""
    paths: list[str] = []
    for err in exc.errors(include_input=False, include_context=False, include_url=False):
        loc = [str(part) for part in err["loc"]]
        if err["type"] == "extra_forbidden" and loc:
            loc[-1] = "<unknown field>"
        path = ".".join(loc) or "<document>"
        if path not in paths:
            paths.append(path)
        if len(paths) >= _MAX_REPORTED_ERRORS:
            break
    return paths


def parse_import(raw: bytes) -> ExportDoc:
    """Parse and validate an import document; every failure is a fixed-message 4xx."""
    if len(raw) > MAX_IMPORT_BYTES:
        raise ImportTooLargeError()
    try:
        data = json.loads(raw, parse_constant=_refuse_constant, object_pairs_hook=_no_duplicates)
    except (ValueError, RecursionError):  # JSONDecodeError and UnicodeDecodeError are ValueErrors
        # RecursionError: 64 KB allow ~32 000 nesting levels, which overflow the parser.
        raise InvalidImportError(["<document>"]) from None
    if not isinstance(data, dict):
        raise InvalidImportError(["<document>"])
    try:
        doc = ExportDoc.model_validate(data)
    except ValidationError as exc:
        raise InvalidImportError(_error_paths(exc)) from None
    try:
        geometry = geometry_from_doc(doc.version.geometry)
        validate_geometry(geometry)  # stated page size must match
    except InvalidGeometryError as exc:
        field = (exc.detail or {}).get("field", "geometry")
        raise InvalidImportError([f"version.geometry.{field}"]) from None
    _check_placement(doc, geometry)
    return doc


def _check_placement(doc: ExportDoc, geometry: Geometry) -> None:
    """The version-2 keys of a document: the ID cell on its grid, the design on its page."""
    t = doc.type
    total = geometry.cols * geometry.rows
    if t.id_cell is not None and t.id_cell > total:
        raise IdCellOutOfRangeError(t.id_cell, total)
    design = t.backing_design
    if design is None:
        return
    from app.sheets.backing_design_service import strips_from_mm, validate_strips

    try:
        validate_strips(strips_from_mm(design.strips), design.page_size)
    except InvalidGeometryError as exc:
        field = (exc.detail or {}).get("field", "strips")
        raise InvalidImportError([f"type.backing_design.{field}"]) from None
    if design.page_size != geometry.page_size:
        raise BackingDesignPageSizeMismatchError()


def _type_fields(doc: ExportDoc, key: str, prefix: str) -> ts.TypeFields:
    t = doc.type
    return ts.TypeFields(
        key=key,
        prefix=prefix,
        vendor=t.vendor,
        product_codes=list(t.product_codes),
        description=t.description,
        allow_qr=t.allow_qr,
        verified=False,  # D19: a stranger's claim is not a verification on this hub
        source_name=t.source_name,
        source_url=t.source_url,
        notes=t.notes,
    )


async def import_type(
    session: AsyncSession,
    doc: ExportDoc,
    *,
    mode: Literal["strict", "new_version", "as_new_key"] = "strict",
    new_key: str | None = None,
    new_prefix: str | None = None,
    actor: str,
) -> ImportResult:
    """Apply an import document (spec 9.3, OC-12).

    ``new_key`` belongs to ``mode="as_new_key"`` and is refused in every other mode; an
    unknown document key never silently ignores it. ``new_prefix`` replaces the prefix of the
    document whenever a type is created.
    """
    geometry = geometry_from_doc(doc.version.geometry)
    if mode == "as_new_key" and new_key is None:
        raise InvalidImportError(["new_key"])
    if mode != "as_new_key" and new_key is not None:
        raise InvalidImportError(["new_key"])
    note = f"Imported from version {doc.version.version} of an export"
    wanted = geometry_hash(geometry)
    # The write lock comes first: reading before it and upgrading later can fail with
    # "database is locked", and a concurrent identical import would see a stale answer.
    async with ts.write_transaction(session):
        existing: SheetType | None = await repo.get_by_key(session, doc.type.key)
        if existing is None:
            if new_key is not None:  # as_new_key only means something for an existing key
                raise InvalidImportError(["new_key"])
            created, _ = await ts.create_type_locked(
                session,
                _type_fields(doc, doc.type.key, new_prefix or doc.type.prefix),
                geometry,
                actor=actor,
                origin="imported",
                change_note=note,
            )
            await _apply_placement(session, created, doc)
            await session.commit()
            return ImportResult("created", doc.type.key, 1)

        existing_key = existing.key  # read before a rollback expires the row
        if mode != "as_new_key":  # a requested copy is made even for identical geometry
            for version, _count in await ts.list_versions_with_sheet_counts(session, existing.id):
                if version.geometry_hash == wanted:  # identical geometry changes nothing (OC-12)
                    found = version.version
                    await session.rollback()  # nothing written: release the lock
                    return ImportResult("unchanged", existing_key, found)

        if mode == "strict":
            raise TypeExistsError()
        if mode == "new_version":
            added = await ts.add_version_locked(
                session, existing_key, geometry, actor=actor, change_note=note
            )
            await session.commit()
            return ImportResult("version_added", existing_key, added.version)
        if new_key is None:  # refused above; kept as a real check for the type narrowing
            raise InvalidImportError(["new_key"])
        copy, _ = await ts.create_type_locked(
            session,
            _type_fields(doc, new_key, new_prefix or doc.type.prefix),
            geometry,
            actor=actor,
            origin="imported",
            change_note=note,
        )
        await _apply_placement(session, copy, doc)
        await session.commit()
        return ImportResult("created_as_new_key", new_key, 1)


async def _apply_placement(session: AsyncSession, t: SheetType, doc: ExportDoc) -> None:
    """Give a type created by an import the document's placement and backing design (R-350-8).

    A design key that exists here is linked as stored (the local strips win); an unknown one
    is created with ``origin="imported"``. Only a type the import creates gets them: a type
    that exists keeps the settings chosen on this hub.
    """
    from app.models.backing_design import BackingDesign
    from app.sheets import backing_design_service as bds

    t.id_placement = doc.type.id_placement
    t.id_cell = doc.type.id_cell
    wanted = doc.type.backing_design
    if wanted is None:
        await session.flush()
        return
    try:
        design: BackingDesign = await bds.get(session, wanted.key)
    except BackingDesignNotFoundError:
        design = await bds.create_locked(
            session,
            key=wanted.key,
            name=wanted.name,
            page_size=wanted.page_size,
            strips=bds.strips_from_mm(wanted.strips),
            origin="imported",
        )
    if design.page_size != doc.version.geometry.page_size:
        raise BackingDesignPageSizeMismatchError()
    t.backing_design_id = design.id
    await session.flush()
