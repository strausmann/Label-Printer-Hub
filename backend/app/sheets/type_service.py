"""Sheet type service: create, edit, versioned geometry, archive, delete (spec 7.1).

Every write starts with ``acquire_sheet_write_lock`` and commits inside; any failure rolls the
transaction back, so a rejected request leaves nothing behind.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.sheet import SheetType, SheetTypeVersion
from app.repositories import sheet_types as repo
from app.sheets.errors import (
    InvalidGeometryError,
    PrefixLockedError,
    PrefixTakenError,
    SheetTypeInUseError,
    SheetTypeNotFoundError,
    TypeExistsError,
)
from app.sheets.geometry import Geometry, geometry_hash, hmm_to_mm, normalise, validate_geometry
from app.sheets.locking import acquire_sheet_write_lock
from app.sheets.naming import KEY_PATTERN, PREFIX_PATTERN, default_allow_qr

logger = logging.getLogger(__name__)

_SIZE_TOLERANCE_MM = 0.5
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
async def _write(session: AsyncSession) -> AsyncIterator[None]:
    """One write transaction: lock first, roll back on any failure."""
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


def _check_prefix(prefix: str) -> None:
    if not PREFIX_PATTERN.match(prefix):
        raise InvalidGeometryError("prefix", "invalid format")


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


async def create_type(
    session: AsyncSession,
    fields: TypeFields,
    geometry: Geometry,
    *,
    actor: str,
    origin: Literal["seed", "custom", "imported"] = "custom",
    change_note: str | None = None,
) -> tuple[SheetType, SheetTypeVersion]:
    if not KEY_PATTERN.match(fields.key):
        raise InvalidGeometryError("key", "invalid format")
    _check_prefix(fields.prefix)
    validate_geometry(normalise(geometry))
    async with _write(session):
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
        await session.commit()
    return t, v


async def patch_type(
    session: AsyncSession, key: str, changes: dict[str, Any], *, actor: str
) -> SheetType:
    for name, value in changes.items():
        if name not in _EDITABLE:
            raise InvalidGeometryError(name, "not editable")
        if name == "product_codes" and not (
            isinstance(value, list) and all(isinstance(c, str) for c in value)
        ):
            raise InvalidGeometryError(name, "must be a list of strings")
    async with _write(session):
        t = await get_type(session, key)
        new_prefix = changes.get("prefix")
        if new_prefix is not None and new_prefix != t.prefix:
            _check_prefix(new_prefix)
            if await repo.count_sheets(session, t.id) > 0:
                raise PrefixLockedError()  # OC-5
            if await repo.get_by_prefix(session, new_prefix) is not None:
                raise PrefixTakenError()
        for name, value in changes.items():
            if name == "prefix" and value is None:
                continue
            setattr(t, name, list(value) if name == "product_codes" else value)
        t.updated_at = _now()
        await session.commit()
    logger.info("sheet type %s edited by %s: %s", key, actor, sorted(changes))
    return t


async def add_version(
    session: AsyncSession, key: str, geometry: Geometry, *, actor: str, change_note: str
) -> SheetTypeVersion:
    validate_geometry(normalise(geometry))
    async with _write(session):
        t = await get_type(session, key)
        latest = await current_version(session, t.id)
        if latest.geometry_hash == geometry_hash(geometry):
            raise InvalidGeometryError("geometry", "unchanged")
        v = _new_version(t.id, latest.version + 1, geometry, actor=actor, change_note=change_note)
        session.add(v)
        t.updated_at = _now()
        await session.commit()
    return v


async def _set_archived(session: AsyncSession, key: str, archived: bool, actor: str) -> SheetType:
    async with _write(session):
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
    async with _write(session):
        t = await get_type(session, key)
        if t.origin != "custom":
            raise SheetTypeInUseError("seed_type")  # OC-10: seed types are only archived
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
    out: list[SheetType] = []
    for t, v in rows:
        if page is not None and v.page_size != page:
            continue
        if w is not None and abs(hmm_to_mm(v.label_w) - w) > _SIZE_TOLERANCE_MM:
            continue
        if h is not None and abs(hmm_to_mm(v.label_h) - h) > _SIZE_TOLERANCE_MM:
            continue
        if needle is not None:
            haystack = [t.key, t.description or "", *t.product_codes]
            if not any(needle in part.lower() for part in haystack):
                continue
        out.append(t)
    return out
