# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Backing designs: the vendor print on the back of a liner and its free strips (R-350-4).

A design is checked on every write (create, patch, import, seed): at most ``MAX_STRIPS``
strips, each at least 1 mm wide and tall and inside the page. A hostile document can therefore
never push the code strip off the page. Writes take the sheet write lock, so a delete cannot
race a sheet type that links the design.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.backing_design import BackingDesign
from app.models.sheet import SheetType
from app.repositories.write_lock import write_transaction
from app.sheets.errors import (
    BackingDesignExistsError,
    BackingDesignInUseError,
    BackingDesignNotFoundError,
    InvalidFieldError,
)
from app.sheets.exchange import MAX_STRIPS, BackingDesignDoc, StripMm
from app.sheets.geometry import PAGE_SIZES, hmm_to_mm, mm_to_hmm
from app.sheets.naming import KEY_PATTERN
from app.sheets.text import log_value
from app.sheets.type_service import clean_text

__all__ = [
    "MIN_STRIP_HMM",
    "create_locked",
    "delete",
    "get",
    "list_with_usage",
    "patch",
    "strips_from_mm",
    "strips_to_mm",
    "to_doc",
    "types_in_use",
    "validate_strips",
]

logger = logging.getLogger(__name__)

MIN_STRIP_HMM = 100  # 1 mm
NAME_MAX = 200


def _now() -> datetime:
    return datetime.now(UTC)


def validate_strips(strips: list[dict[str, int]], page_size: str) -> None:
    """Refuse a strip list the page cannot hold; the error names ``strips.<i>``."""
    if len(strips) > MAX_STRIPS:
        raise InvalidFieldError("strips", "too many")
    page_w, page_h = PAGE_SIZES[page_size]
    for i, s in enumerate(strips):
        x, y, w, h = s["x"], s["y"], s["w"], s["h"]
        if w < MIN_STRIP_HMM or h < MIN_STRIP_HMM:
            raise InvalidFieldError(f"strips.{i}", "smaller than 1 mm")
        if x < 0 or y < 0 or x + w > page_w or y + h > page_h:
            raise InvalidFieldError(f"strips.{i}", "outside the page")


def strips_from_mm(strips: list[StripMm]) -> list[dict[str, int]]:
    """Millimetres (two decimals at most) to stored hundredths, named by field path."""
    out: list[dict[str, int]] = []
    for i, s in enumerate(strips):
        out.append(
            {
                "x": mm_to_hmm(s.x_mm, field=f"strips.{i}.x_mm"),
                "y": mm_to_hmm(s.y_mm, field=f"strips.{i}.y_mm"),
                "w": mm_to_hmm(s.w_mm, field=f"strips.{i}.w_mm"),
                "h": mm_to_hmm(s.h_mm, field=f"strips.{i}.h_mm"),
            }
        )
    return out


def strips_to_mm(strips: list[dict[str, Any]]) -> list[StripMm]:
    return [
        StripMm(
            x_mm=hmm_to_mm(int(s["x"])),
            y_mm=hmm_to_mm(int(s["y"])),
            w_mm=hmm_to_mm(int(s["w"])),
            h_mm=hmm_to_mm(int(s["h"])),
        )
        for s in strips
    ]


def to_doc(design: BackingDesign) -> BackingDesignDoc:
    return BackingDesignDoc(
        key=design.key,
        name=design.name,
        page_size=design.page_size,  # type: ignore[arg-type]
        strips=strips_to_mm(design.strips),
    )


def _clean_name(name: str) -> str:
    cleaned = clean_text("name", name, NAME_MAX)
    if not cleaned:
        raise InvalidFieldError("name", "must not be empty")
    return cleaned


async def get(session: AsyncSession, key: str) -> BackingDesign:
    found = (
        await session.execute(select(BackingDesign).where(col(BackingDesign.key) == key))
    ).scalar_one_or_none()
    if found is None:
        raise BackingDesignNotFoundError()
    return found


async def types_in_use(session: AsyncSession, design_id: Any) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(SheetType)
        .where(col(SheetType.backing_design_id) == design_id)
    )
    return int(result.scalar_one())


async def list_with_usage(session: AsyncSession) -> list[tuple[BackingDesign, int]]:
    """Every design by key, with the number of sheet types that point to it."""
    designs = list(
        (await session.execute(select(BackingDesign).order_by(col(BackingDesign.key)))).scalars()
    )
    counts = dict(
        (
            await session.execute(
                select(col(SheetType.backing_design_id), func.count())
                .where(col(SheetType.backing_design_id).is_not(None))
                .group_by(col(SheetType.backing_design_id))
            )
        ).all()
    )
    return [(d, int(counts.get(d.id, 0))) for d in designs]


async def create_locked(
    session: AsyncSession,
    *,
    key: str,
    name: str,
    page_size: str,
    strips: list[dict[str, int]],
    origin: Literal["seed", "custom", "imported"],
) -> BackingDesign:
    """Insert a design inside a transaction that already holds the write lock."""
    if not KEY_PATTERN.fullmatch(key):
        raise InvalidFieldError("key", "invalid format")
    if page_size not in PAGE_SIZES:
        raise InvalidFieldError("page_size", "unknown page size")
    validate_strips(strips, page_size)
    clean = _clean_name(name)
    exists = (
        await session.execute(select(col(BackingDesign.id)).where(col(BackingDesign.key) == key))
    ).first()
    if exists is not None:
        raise BackingDesignExistsError()
    design = BackingDesign(key=key, name=clean, page_size=page_size, strips=strips, origin=origin)
    session.add(design)
    await session.flush()
    return design


async def create(
    session: AsyncSession,
    *,
    key: str,
    name: str,
    page_size: str,
    strips: list[dict[str, int]],
) -> BackingDesign:
    validate_strips(strips, page_size)  # cheap refusals before the lock
    async with write_transaction(session):
        design = await create_locked(
            session, key=key, name=name, page_size=page_size, strips=strips, origin="custom"
        )
        await session.commit()
    logger.info("backing design %s created", log_value(key))
    return design


async def patch(session: AsyncSession, key: str, changes: dict[str, Any]) -> BackingDesign:
    """Change the name or the strips; the page size of a design is fixed."""
    async with write_transaction(session):
        design = await get(session, key)
        if "name" in changes:
            design.name = _clean_name(changes["name"])
        if "strips" in changes:
            validate_strips(changes["strips"], design.page_size)
            design.strips = list(changes["strips"])
        design.updated_at = _now()
        await session.commit()
    logger.info("backing design %s edited", log_value(key))
    return design


async def delete(session: AsyncSession, key: str) -> None:
    """Delete a design no sheet type uses (409 ``backing_design_in_use`` otherwise)."""
    async with write_transaction(session):
        design = await get(session, key)
        used = await types_in_use(session, design.id)
        if used:
            raise BackingDesignInUseError(used)
        await session.delete(design)
        await session.commit()
    logger.info("backing design %s deleted", log_value(key))
