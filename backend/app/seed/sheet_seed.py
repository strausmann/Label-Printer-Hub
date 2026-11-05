"""Seed the sheet type archive from the shipped file (spec 9.5, OC-14).

The seeder keeps no state of its own. Every start compares the seed keys and geometry hashes
with the database (one query per table) and acts only where the database is untouched:

- a missing key is inserted with ``origin="seed"``;
- an existing type gets a new version only if every version of it came from the seeder
  (``created_by == "seed"``), no sheet uses it and the seed geometry differs from the current
  version, so a local edit is never overwritten;
- a seed whose prefix belongs to another type is skipped and logged.
"""

from __future__ import annotations

import importlib.resources
import json
import logging
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import col

from app.models.sheet import Sheet, SheetType, SheetTypeVersion
from app.sheets import type_service as ts
from app.sheets.exchange import ExportDoc, geometry_from_doc
from app.sheets.geometry import geometry_hash

logger = logging.getLogger(__name__)

SEED_FILE = importlib.resources.files("app.seed") / "sheet_types.json"
SEED_ACTOR = "seed"


@dataclass
class SeedReport:
    inserted: list[str] = field(default_factory=list)
    versions_added: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)


def load_seed() -> tuple[int, list[ExportDoc]]:
    raw = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    return int(raw["seed_revision"]), [ExportDoc.model_validate(d) for d in raw["types"]]


@dataclass
class _Known:
    types: dict[str, SheetType]
    prefixes: set[str]
    current: dict[UUID, SheetTypeVersion]  # latest version per type
    foreign_versions: set[UUID]  # types with a version that did not come from the seeder
    with_sheets: set[UUID]


async def _load_known(session: AsyncSession) -> _Known:
    types = list((await session.execute(select(SheetType))).scalars())
    versions = list((await session.execute(select(SheetTypeVersion))).scalars())
    used = set(
        (
            await session.execute(
                select(col(Sheet.type_id)).group_by(col(Sheet.type_id)).having(func.count() > 0)
            )
        ).scalars()
    )
    current: dict[UUID, SheetTypeVersion] = {}
    foreign: set[UUID] = set()
    for v in versions:
        if v.created_by != SEED_ACTOR:
            foreign.add(v.type_id)
        latest = current.get(v.type_id)
        if latest is None or v.version > latest.version:
            current[v.type_id] = v
    return _Known(
        types={t.key: t for t in types},
        prefixes={t.prefix for t in types},
        current=current,
        foreign_versions=foreign,
        with_sheets=used,
    )


async def run_sheet_seed(session_factory: async_sessionmaker[AsyncSession]) -> SeedReport:
    revision, docs = load_seed()
    report = SeedReport()
    async with session_factory() as session, ts.write_transaction(session):
        known = await _load_known(session)
        for doc in docs:
            await _seed_one(session, doc, known, report)
        await session.commit()
    logger.info(
        "sheet seed revision %d: %d inserted, %d versions added, %d skipped",
        revision,
        len(report.inserted),
        len(report.versions_added),
        len(report.skipped),
    )
    return report


async def _seed_one(
    session: AsyncSession, doc: ExportDoc, known: _Known, report: SeedReport
) -> None:
    key = doc.type.key
    geometry = geometry_from_doc(doc.version.geometry)
    existing = known.types.get(key)
    if existing is None:
        if doc.type.prefix in known.prefixes:
            logger.warning("seed type %s skipped: prefix %s is taken", key, doc.type.prefix)
            report.skipped[key] = "prefix_taken"
            return
        fields = ts.TypeFields(
            key=key,
            prefix=doc.type.prefix,
            vendor=doc.type.vendor,
            product_codes=list(doc.type.product_codes),
            description=doc.type.description,
            allow_qr=doc.type.allow_qr,
            verified=doc.type.verified,
            source_name=doc.type.source_name,
            source_url=doc.type.source_url,
            notes=doc.type.notes,
        )
        await ts.create_type_locked(
            session, fields, geometry, actor=SEED_ACTOR, origin="seed", change_note="seed"
        )
        known.prefixes.add(doc.type.prefix)
        report.inserted.append(key)
        return
    current = known.current.get(existing.id)
    if current is None or current.geometry_hash == geometry_hash(geometry):
        return
    if existing.id in known.foreign_versions or existing.id in known.with_sheets:
        logger.info("seed type %s left alone: edited locally or in use", key)
        return
    await ts.add_version_locked(
        session, key, geometry, actor=SEED_ACTOR, change_note=f"seed update ({key})"
    )
    report.versions_added.append(key)
