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
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sheet import SheetType
from app.repositories import sheet_types as repo
from app.sheets import type_service as ts
from app.sheets.errors import (
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

    @field_validator("source_url")
    @classmethod
    def _http_only(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("only http and https URLs are allowed")
        if any(ch.isspace() or ord(ch) < 32 for ch in value):
            raise ValueError("control characters are not allowed")
        return value


class VersionDoc(_Strict):
    version: Annotated[int, Field(strict=True, ge=1, le=1_000_000)]
    geometry: GeometryMm


class ExportDoc(_Strict):
    format: Literal["label-printer-hub.sheet-type"]
    format_version: Literal[1]
    type: TypeDoc
    version: VersionDoc
    exported_at: datetime
    exported_by_hub: Annotated[str, Field(max_length=64)]


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
    return ExportDoc(
        format="label-printer-hub.sheet-type",
        format_version=1,
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
        validate_geometry(geometry_from_doc(doc.version.geometry))  # stated page size must match
    except InvalidGeometryError as exc:
        field = (exc.detail or {}).get("field", "geometry")
        raise InvalidImportError([f"version.geometry.{field}"]) from None
    return doc


def _type_fields(doc: ExportDoc, key: str, prefix: str) -> ts.TypeFields:
    t = doc.type
    return ts.TypeFields(
        key=key,
        prefix=prefix,
        vendor=t.vendor,
        product_codes=list(t.product_codes),
        description=t.description,
        allow_qr=t.allow_qr,
        verified=False,  # a stranger's claim is not a verification on this hub
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
    geometry = geometry_from_doc(doc.version.geometry)
    existing: SheetType | None = await repo.get_by_key(session, doc.type.key)
    note = f"Imported from version {doc.version.version} of an export"
    if existing is None:
        await ts.create_type(
            session,
            _type_fields(doc, doc.type.key, new_prefix or doc.type.prefix),
            geometry,
            actor=actor,
            origin="imported",
            change_note=note,
        )
        return ImportResult("created", doc.type.key, 1)

    wanted = geometry_hash(geometry)
    for version, _count in await ts.list_versions_with_sheet_counts(session, existing.id):
        if version.geometry_hash == wanted:
            return ImportResult("unchanged", existing.key, version.version)

    if mode == "strict":
        raise TypeExistsError()
    if mode == "new_version":
        added = await ts.add_version(session, existing.key, geometry, actor=actor, change_note=note)
        return ImportResult("version_added", existing.key, added.version)
    if new_key is None:
        raise InvalidImportError(["new_key"])  # as_new_key without a key
    await ts.create_type(
        session,
        _type_fields(doc, new_key, new_prefix or doc.type.prefix),
        geometry,
        actor=actor,
        origin="imported",
        change_note=note,
    )
    return ImportResult("created_as_new_key", new_key, 1)
