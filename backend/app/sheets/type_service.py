"""Sheet type service: create, edit, versioned geometry, archive, delete (spec 7.1).

Every write starts with ``acquire_sheet_write_lock`` and commits inside; any failure rolls the
transaction back, so a rejected request leaves nothing behind.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.sheet import SheetType, SheetTypeVersion
from app.repositories import sheet_types as repo
from app.sheets.errors import (
    InvalidFieldError,
    InvalidGeometryError,
    PrefixLockedError,
    PrefixTakenError,
    SheetTypeInUseError,
    SheetTypeNotFoundError,
    TypeExistsError,
)
from app.sheets.geometry import Geometry, geometry_hash, normalise, validate_geometry
from app.sheets.locking import acquire_sheet_write_lock
from app.sheets.naming import KEY_PATTERN, PREFIX_PATTERN, default_allow_qr
from app.sheets.text import check_http_url, sanitise_text

logger = logging.getLogger(__name__)

_SIZE_TOLERANCE_HMM = 50  # 0.5 mm, compared as integers (D16)
_EDITABLE = frozenset(
    {
        "vendor",
        "product_codes",
        "description",
        "allow_qr",
        "verified",
        "source_name",
        "source_url",
        "notes",
        "prefix",
    }
)


@dataclass
class TypeFields:
    key: str
    prefix: str
    vendor: str | None
    product_codes: list[str]
    description: str | None
    allow_qr: bool | None  # None: derived from the geometry (OC-28)
    verified: bool = False
    source_name: str | None = None
    source_url: str | None = None
    notes: str | None = None


def _now() -> datetime:
    return datetime.now(UTC)


@asynccontextmanager
async def write_transaction(session: AsyncSession) -> AsyncIterator[None]:
    """One write transaction: lock first, roll back on any failure.

    Callers that decide before they write (import) enter this once and use the ``*_locked``
    functions inside; those assume the lock is already held and neither lock nor commit.
    """
    try:
        await acquire_sheet_write_lock(session)
        yield
    except BaseException:
        await session.rollback()
        raise


def version_geometry(v: SheetTypeVersion) -> Geometry:
    return Geometry(
        page_size=v.page_size,  # type: ignore[arg-type]
        page_w=v.page_w,
        page_h=v.page_h,
        label_w=v.label_w,
        label_h=v.label_h,
        cols=v.cols,
        rows=v.rows,
        pitch_x=v.pitch_x,
        pitch_y=v.pitch_y,
        margin_top=v.margin_top,
        margin_left=v.margin_left,
        corner_radius=v.corner_radius,
        shape=v.shape,  # type: ignore[arg-type]
    )


def _new_version(
    type_id: UUID, n: int, g: Geometry, *, actor: str, change_note: str | None
) -> SheetTypeVersion:
    g = normalise(g)
    return SheetTypeVersion(
        type_id=type_id,
        version=n,
        page_size=g.page_size,
        page_w=g.page_w,
        page_h=g.page_h,
        label_w=g.label_w,
        label_h=g.label_h,
        cols=g.cols,
        rows=g.rows,
        pitch_x=g.pitch_x,
        pitch_y=g.pitch_y,
        margin_top=g.margin_top,
        margin_left=g.margin_left,
        corner_radius=g.corner_radius,
        shape=g.shape,
        geometry_hash=geometry_hash(g),
        created_by=actor,
        change_note=change_note,
    )


def mm_to_hmm_rounded(value: float) -> int:
    """Filter input in mm to whole hundredths; any float noise rounds away."""
    return round(Decimal(str(value)) * 100)


def _check_prefix(prefix: object) -> None:
    if not isinstance(prefix, str) or not PREFIX_PATTERN.match(prefix):
        raise InvalidFieldError("prefix", "invalid format")


_NULLABLE_TEXT = frozenset({"vendor", "description", "source_name", "source_url", "notes"})
# Free text is cleaned before it is stored; same bounds as the export document (spec 9.2).
TEXT_LIMITS = {"vendor": 200, "description": 200, "source_name": 200, "notes": 2000}
PRODUCT_CODE_MAX = 40
PRODUCT_CODES_MAX = 50  # the export document's limit (``TypeDoc.product_codes``)
SOURCE_URL_MAX = 500
CHANGE_NOTE_MAX = 500


# Fields that may hold several lines; every other text is a single line (spec 18).
MULTILINE_FIELDS = frozenset({"description", "notes", "change_note"})


def clean_text(field: str, value: str, max_len: int) -> str:
    """``sanitise_text`` with the error mapped to a 422 that names the field."""
    try:
        return sanitise_text(value, max_len=max_len, multiline=field in MULTILINE_FIELDS)
    except ValueError:
        raise InvalidFieldError(field, "too long") from None


def _clean_optional(field: str, value: str | None) -> str | None:
    """Text that is nothing after cleaning is no text: ``None``, never an empty string."""
    return None if value is None else clean_text(field, value, TEXT_LIMITS[field]) or None


def _clean_url(value: str | None) -> str | None:
    """``source_url`` is http(s) only (the same check as import and the API schema)."""
    if value is None:
        return None
    if len(value) > SOURCE_URL_MAX:
        raise InvalidFieldError("source_url", "too long")
    try:
        return check_http_url(value)
    except ValueError as exc:
        raise InvalidFieldError("source_url", str(exc)) from None


def _clean_codes(codes: list[str]) -> list[str]:
    if len(codes) > PRODUCT_CODES_MAX:
        raise InvalidFieldError("product_codes", "too many")
    cleaned = (clean_text("product_codes", c, PRODUCT_CODE_MAX) for c in codes)
    return [c for c in cleaned if c]  # an entry that cleans to nothing is dropped


def _clean_change_note(note: str | None) -> str | None:
    return None if note is None else clean_text("change_note", note, CHANGE_NOTE_MAX) or None


def _clean_fields(fields: TypeFields) -> TypeFields:
    return replace(
        fields,
        vendor=_clean_optional("vendor", fields.vendor),
        description=_clean_optional("description", fields.description),
        source_name=_clean_optional("source_name", fields.source_name),
        notes=_clean_optional("notes", fields.notes),
        source_url=_clean_url(fields.source_url),
        product_codes=_clean_codes(fields.product_codes),
    )


def _clean_patch_value(name: str, value: Any) -> Any:
    if name in TEXT_LIMITS:
        return _clean_optional(name, value)
    if name == "source_url":
        return _clean_url(value)
    if name == "product_codes":
        return _clean_codes(value)
    return value


_BOOLEAN = frozenset({"allow_qr", "verified"})


def _check_patch_value(name: str, value: object) -> None:
    """Reject a value the column cannot hold before anything is written."""
    if name in _BOOLEAN:
        if not isinstance(value, bool):
            raise InvalidFieldError(name, "must be true or false")
    elif name in _NULLABLE_TEXT:
        if value is not None and not isinstance(value, str):
            raise InvalidFieldError(name, "must be text or null")
    elif name == "product_codes":
        if not (isinstance(value, list) and all(isinstance(c, str) for c in value)):
            raise InvalidFieldError(name, "must be a list of strings")
    elif name == "prefix":
        _check_prefix(value)


async def get_type(session: AsyncSession, key: str) -> SheetType:
    found = await repo.get_by_key(session, key)
    if found is None:
        raise SheetTypeNotFoundError()
    return found


async def current_version(session: AsyncSession, type_id: UUID) -> SheetTypeVersion:
    found = await repo.current_version(session, type_id)
    if found is None:  # a type without a version breaks the model invariant
        raise SheetTypeNotFoundError()
    return found


async def get_version(session: AsyncSession, key: str, n: int) -> SheetTypeVersion:
    t = await get_type(session, key)
    found = await repo.get_version(session, t.id, n)
    if found is None:
        raise SheetTypeNotFoundError()
    return found


async def list_versions_with_sheet_counts(
    session: AsyncSession, type_id: UUID
) -> list[tuple[SheetTypeVersion, int]]:
    return await repo.versions_with_sheet_counts(session, type_id)


async def create_type_locked(
    session: AsyncSession,
    fields: TypeFields,
    geometry: Geometry,
    *,
    actor: str,
    origin: Literal["seed", "custom", "imported"],
    change_note: str | None,
) -> tuple[SheetType, SheetTypeVersion]:
    """Insert type and version 1 inside a transaction that already holds the write lock."""
    fields = _clean_fields(fields)
    change_note = _clean_change_note(change_note)
    if not KEY_PATTERN.match(fields.key):
        raise InvalidFieldError("key", "invalid format")
    _check_prefix(fields.prefix)
    validate_geometry(normalise(geometry))
    if await repo.get_by_key(session, fields.key) is not None:
        raise TypeExistsError()
    if await repo.get_by_prefix(session, fields.prefix) is not None:
        raise PrefixTakenError()
    allow_qr = default_allow_qr(geometry) if fields.allow_qr is None else fields.allow_qr
    t = SheetType(
        key=fields.key,
        prefix=fields.prefix,
        vendor=fields.vendor,
        product_codes=list(fields.product_codes),
        description=fields.description,
        allow_qr=allow_qr,
        verified=fields.verified,
        origin=origin,
        source_name=fields.source_name,
        source_url=fields.source_url,
        notes=fields.notes,
        created_by=actor,
    )
    session.add(t)
    await session.flush()
    v = _new_version(t.id, 1, geometry, actor=actor, change_note=change_note)
    session.add(v)
    return t, v


async def create_type(
    session: AsyncSession,
    fields: TypeFields,
    geometry: Geometry,
    *,
    actor: str,
    origin: Literal["seed", "custom", "imported"] = "custom",
    change_note: str | None = None,
) -> tuple[SheetType, SheetTypeVersion]:
    # Cheap input checks first so a bad request does not take the write lock.
    if not KEY_PATTERN.match(fields.key):
        raise InvalidFieldError("key", "invalid format")
    _check_prefix(fields.prefix)
    validate_geometry(normalise(geometry))
    _clean_fields(fields)
    _clean_change_note(change_note)
    async with write_transaction(session):
        t, v = await create_type_locked(
            session, fields, geometry, actor=actor, origin=origin, change_note=change_note
        )
        await session.commit()
    return t, v


async def patch_type(
    session: AsyncSession, key: str, changes: dict[str, Any], *, actor: str
) -> SheetType:
    for name, value in changes.items():
        if name not in _EDITABLE:
            raise InvalidFieldError(name, "not editable")
        _check_patch_value(name, value)
    changes = {name: _clean_patch_value(name, value) for name, value in changes.items()}
    async with write_transaction(session):
        t = await get_type(session, key)
        new_prefix = changes.get("prefix")
        if new_prefix is not None and new_prefix != t.prefix:
            if await repo.count_sheets(session, t.id) > 0:
                raise PrefixLockedError()  # OC-5
            if await repo.get_by_prefix(session, new_prefix) is not None:
                raise PrefixTakenError()
        changed = False
        for name, value in changes.items():
            new = list(value) if name == "product_codes" else value
            if getattr(t, name) != new:
                setattr(t, name, new)
                changed = True
        if changed:
            t.updated_at = _now()
        await session.commit()
    logger.info("sheet type %s edited by %s: %s", key, actor, sorted(changes))
    return t


async def add_version_locked(
    session: AsyncSession, key: str, geometry: Geometry, *, actor: str, change_note: str
) -> SheetTypeVersion:
    """Add the next version inside a transaction that already holds the write lock."""
    change_note = _clean_change_note(change_note) or ""
    if not change_note:
        raise InvalidFieldError("change_note", "must not be empty")
    validate_geometry(normalise(geometry))
    t = await get_type(session, key)
    latest = await current_version(session, t.id)
    if latest.geometry_hash == geometry_hash(geometry):
        raise InvalidGeometryError("geometry", "unchanged")
    v = _new_version(t.id, latest.version + 1, geometry, actor=actor, change_note=change_note)
    session.add(v)
    t.updated_at = _now()
    return v


async def add_version(
    session: AsyncSession, key: str, geometry: Geometry, *, actor: str, change_note: str
) -> SheetTypeVersion:
    validate_geometry(normalise(geometry))
    _clean_change_note(change_note)
    async with write_transaction(session):
        v = await add_version_locked(session, key, geometry, actor=actor, change_note=change_note)
        await session.commit()
    return v


async def _set_archived(session: AsyncSession, key: str, archived: bool, actor: str) -> SheetType:
    async with write_transaction(session):
        t = await get_type(session, key)
        if archived and t.archived_at is None:
            t.archived_at = _now()
        elif not archived:
            t.archived_at = None
        t.updated_at = _now()
        await session.commit()
    logger.info("sheet type %s %s by %s", key, "archived" if archived else "restored", actor)
    return t


async def archive_type(session: AsyncSession, key: str, *, actor: str) -> SheetType:
    return await _set_archived(session, key, True, actor)


async def unarchive_type(session: AsyncSession, key: str, *, actor: str) -> SheetType:
    return await _set_archived(session, key, False, actor)


async def delete_type(session: AsyncSession, key: str, *, actor: str) -> None:
    async with write_transaction(session):
        t = await get_type(session, key)
        if t.origin != "custom":
            # OC-10: only custom types without sheets are deleted; the rest is archived.
            raise SheetTypeInUseError(f"{t.origin}_type")
        if await repo.count_sheets(session, t.id) > 0:
            raise SheetTypeInUseError("has_sheets")
        await session.execute(delete(SheetTypeVersion).where(col(SheetTypeVersion.type_id) == t.id))
        await session.delete(t)
        await session.commit()
    logger.info("sheet type %s deleted by %s", key, actor)


async def list_types(
    session: AsyncSession,
    *,
    page: str | None,
    vendor: str | None,
    q: str | None,
    w: float | None,
    h: float | None,
    include_archived: bool,
) -> list[SheetType]:
    rows = await repo.list_with_current_version(
        session, vendor=vendor, include_archived=include_archived
    )
    needle = q.lower() if q else None
    w_hmm = None if w is None else mm_to_hmm_rounded(w)
    h_hmm = None if h is None else mm_to_hmm_rounded(h)
    out: list[SheetType] = []
    for t, v in rows:
        if page is not None and v.page_size != page:
            continue
        if w_hmm is not None and abs(v.label_w - w_hmm) > _SIZE_TOLERANCE_HMM:
            continue
        if h_hmm is not None and abs(v.label_h - h_hmm) > _SIZE_TOLERANCE_HMM:
            continue
        if needle is not None:
            haystack = [t.key, t.description or "", *t.product_codes]
            if not any(needle in part.lower() for part in haystack):
                continue
        out.append(t)
    return out
