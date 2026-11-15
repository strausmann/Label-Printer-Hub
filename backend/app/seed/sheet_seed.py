# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Seed the sheet type archive from the shipped file (spec 9.5, OC-14).

The seeder keeps no state of its own. Every start compares the seed keys and geometry hashes
with the database (one query per table) and acts only where the database is untouched:

- a missing key is inserted with ``origin="seed"``;
- an existing type gets a new version only if every version of it came from the seeder
  (``created_by == "system:seed"``), no sheet uses it and the seed geometry differs from the current
  version, so a local edit is never overwritten;
- a seed whose prefix belongs to another type is skipped and logged;
- a seed whose version number is lower than the type's current version is an older seed (a
  downgraded hub) and is ignored, so it never adds a version that reverts the geometry (264-11);
- each entry runs in its own savepoint: one that fails is logged and skipped, the others are
  stored (264-10).

Two top-level maps of the seed file carry the exceptions (spec 10i, #334):

- ``adopt``: a key that may already exist as a user's own type. Once per revision the type is
  taken over as shipped (``origin="seed"``, verified); a different current geometry becomes the
  next version, never replacing an older one. The prefix, vendor, product codes, description
  and QR switch stay the user's.
- ``corrections``: a shipped type whose shipped geometry changed. Only a type still on the old
  shipped geometry gets the new one as its next version, whatever sheets use it; a locally
  edited geometry is left alone.

Both are recorded in ``app_settings`` (``internal.seed.adopted`` / ``internal.seed.corrected``,
``{key: revision}``), so a second start does nothing; each takeover leaves one notice in
``internal.notices`` for the notification centre. All of it happens inside the entry's savepoint.
"""

from __future__ import annotations

import functools
import hashlib
import importlib.resources
import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from importlib.resources.abc import Traversable
from typing import Any, Final, Literal, NamedTuple
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import col

from app.models.app_setting import AppSetting
from app.models.sheet import Sheet, SheetType, SheetTypeVersion
from app.sheets import type_service as ts
from app.sheets.exchange import ExportDoc, geometry_from_doc
from app.sheets.geometry import geometry_hash
from app.sheets.text import log_value

logger = logging.getLogger(__name__)

SEED_FILE = importlib.resources.files("app.seed") / "sheet_types.json"
SEED_ACTOR = "system:seed"  # the "system:" prefix is reserved; API actors cannot carry it

# Seeder state in ``app_settings``. The settings registry does not know these keys, so the
# settings store ignores them and the settings API never lists them.
ADOPTED_KEY: Final = "internal.seed.adopted"
CORRECTED_KEY: Final = "internal.seed.corrected"
NOTICES_KEY: Final = "internal.notices"
NOTICE_MAX_AGE: Final = timedelta(days=30)

_PACK_SIZE = re.compile(r"-\d+$")


@dataclass
class SeedReport:
    inserted: list[str] = field(default_factory=list)
    versions_added: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)
    adopted: list[str] = field(default_factory=list)
    corrected: list[str] = field(default_factory=list)


class SeedAdoption(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    revision: int
    change_note: str


class SeedCorrection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    revision: int
    previous_geometry_hash: str
    previous_notes_sha256: str
    change_note: str


class SeedFile(NamedTuple):
    revision: int
    docs: list[ExportDoc]
    adopt: dict[str, SeedAdoption]
    corrections: dict[str, SeedCorrection]


def load_seed(path: Traversable = SEED_FILE) -> SeedFile:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return SeedFile(
        revision=int(raw["seed_revision"]),
        docs=[ExportDoc.model_validate(d) for d in raw["types"]],
        adopt={k: SeedAdoption.model_validate(v) for k, v in raw.get("adopt", {}).items()},
        corrections={
            k: SeedCorrection.model_validate(v) for k, v in raw.get("corrections", {}).items()
        },
    )


def notice_code(product_codes: Sequence[str]) -> str:
    """The first product code without its pack-size suffix (``L4731REV-25`` -> ``L4731REV``)."""
    return _PACK_SIZE.sub("", product_codes[0]) if product_codes else ""


@functools.cache
def shipped_source_urls() -> dict[str, str]:
    """The source URL of every seed type as shipped, by key (a type without one is left out)."""
    return {d.type.key: d.type.source_url for d in load_seed().docs if d.type.source_url}


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
    seed = load_seed()
    report = SeedReport()
    async with session_factory() as session, ts.write_transaction(session):
        known = await _load_known(session)
        for doc in seed.docs:
            try:
                async with session.begin_nested():
                    await _seed_one(session, doc, seed, known, report)
            except Exception:
                key = log_value(doc.type.key)
                logger.exception("seed type %s skipped: it could not be stored", key)
                report.skipped[doc.type.key] = "error"
        await session.commit()
    logger.info(
        "sheet seed revision %d: %d inserted, %d versions added, %d adopted, %d corrected, "
        "%d skipped",
        seed.revision,
        len(report.inserted),
        len(report.versions_added),
        len(report.adopted),
        len(report.corrected),
        len(report.skipped),
    )
    return report


def _row_edited(row: SheetType, doc: ExportDoc) -> bool:
    """Row edits make no version, so they are compared with the seed values (spec 9.5)."""
    t = doc.type
    return (
        row.prefix != t.prefix
        or row.vendor != t.vendor
        or row.product_codes != list(t.product_codes)
        or row.description != t.description
        or row.verified != t.verified
        or row.allow_qr != t.allow_qr
        or row.source_name != t.source_name
        or row.source_url != t.source_url
        or row.notes != t.notes
    )


async def _setting_map(session: AsyncSession, setting_key: str) -> dict[str, Any]:
    row = await session.get(AppSetting, setting_key)
    if row is None or row.value_json is None:
        return {}
    try:
        value = json.loads(row.value_json)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


async def _write_setting(session: AsyncSession, setting_key: str, value: Any) -> None:
    row = await session.get(AppSetting, setting_key)
    text = json.dumps(value, sort_keys=True)
    if row is None:
        session.add(AppSetting(key=setting_key, value_json=text))
    else:
        row.value_json = text
        row.updated_at = datetime.now(UTC)
    await session.flush()


async def _mark(session: AsyncSession, setting_key: str, key: str, revision: int) -> None:
    current = await _setting_map(session, setting_key)
    current[key] = revision
    await _write_setting(session, setting_key, current)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


async def _append_notice(
    session: AsyncSession,
    *,
    kind: Literal["sheet_type_verified", "sheet_type_updated"],
    key: str,
    code: str,
    revision: int,
    now: datetime,
) -> None:
    """Append one notice and drop the ones older than ``NOTICE_MAX_AGE`` in the same write."""
    row = await session.get(AppSetting, NOTICES_KEY)
    records: list[Any] = []
    if row is not None and row.value_json is not None:
        try:
            loaded = json.loads(row.value_json)
        except ValueError:
            loaded = []
        records = loaded if isinstance(loaded, list) else []
    cutoff = now - NOTICE_MAX_AGE
    kept = [r for r in records if _notice_is_recent(r, cutoff)]
    kept.append(
        {
            "id": f"sheet-type-verified:{key}:{revision}",
            "kind": kind,
            "key": key,
            "code": code,
            "at": _iso(now),
        }
    )
    await _write_setting(session, NOTICES_KEY, kept)


def _notice_is_recent(record: object, cutoff: datetime) -> bool:
    if not isinstance(record, dict):
        return False
    try:
        at = datetime.fromisoformat(str(record["at"]))
    except (KeyError, ValueError):
        return False
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    return at >= cutoff


def _type_fields(doc: ExportDoc) -> ts.TypeFields:
    t = doc.type
    return ts.TypeFields(
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
    )


async def _adopt_one(
    session: AsyncSession,
    doc: ExportDoc,
    adoption: SeedAdoption,
    known: _Known,
    report: SeedReport,
) -> None:
    """Take an existing type of a shipped key over as shipped (spec 10i, R-334-3)."""
    key = doc.type.key
    existing = known.types[key]
    current = known.current.get(existing.id)
    if current is None:  # a type without a version breaks the model invariant
        return
    geometry = geometry_from_doc(doc.version.geometry)
    previous_origin, previous_version = existing.origin, current.version
    added = current.geometry_hash != geometry_hash(geometry)
    if added:
        current = await ts.add_version_locked(
            session, key, geometry, actor=SEED_ACTOR, change_note=adoption.change_note
        )
        known.current[existing.id] = current
    # prefix, vendor, product codes, description and the QR switch stay the user's (OC-5)
    existing.origin = "seed"
    existing.verified = True
    existing.source_name = doc.type.source_name
    existing.source_url = doc.type.source_url
    existing.notes = doc.type.notes
    existing.updated_at = datetime.now(UTC)
    await session.flush()
    await _mark(session, ADOPTED_KEY, key, adoption.revision)
    await _append_notice(
        session,
        kind="sheet_type_updated" if added else "sheet_type_verified",
        key=key,
        code=notice_code(existing.product_codes) or key,
        revision=adoption.revision,
        now=datetime.now(UTC),
    )
    logger.warning(
        "sheet type adopted as shipped: key=%s previous origin=%s version %d -> %d hash=%s",
        log_value(key),
        previous_origin,
        previous_version,
        current.version,
        current.geometry_hash,
    )
    report.adopted.append(key)
    if added:
        report.versions_added.append(key)


async def _correct_one(
    session: AsyncSession,
    doc: ExportDoc,
    correction: SeedCorrection,
    known: _Known,
    report: SeedReport,
) -> None:
    """Move a type still on the old shipped geometry to the corrected one (R-334-7)."""
    key = doc.type.key
    existing = known.types[key]
    current = known.current.get(existing.id)
    if current is None:
        return
    geometry = geometry_from_doc(doc.version.geometry)
    if current.geometry_hash == geometry_hash(geometry):
        await _mark(session, CORRECTED_KEY, key, correction.revision)  # already corrected
        return
    if existing.origin != "seed":
        return  # never a shipped type here: nothing to correct and nothing worth a line per start
    if current.geometry_hash != correction.previous_geometry_hash:
        logger.info("seed correction skipped for %s: geometry edited locally", log_value(key))
        return
    added = await ts.add_version_locked(
        session, key, geometry, actor=SEED_ACTOR, change_note=correction.change_note
    )
    known.current[existing.id] = added
    existing.verified = True
    if (
        hashlib.sha256((existing.notes or "").encode()).hexdigest()
        == correction.previous_notes_sha256
    ):
        existing.source_name = doc.type.source_name  # the row still holds the revision-1 text
        existing.source_url = doc.type.source_url
        existing.notes = doc.type.notes
    existing.updated_at = datetime.now(UTC)
    await session.flush()
    await _mark(session, CORRECTED_KEY, key, correction.revision)
    await _append_notice(
        session,
        kind="sheet_type_updated",
        key=key,
        code=notice_code(existing.product_codes) or key,
        revision=correction.revision,
        now=datetime.now(UTC),
    )
    logger.warning(
        "seed type corrected: key=%s version %d -> %d hash %s -> %s",
        log_value(key),
        current.version,
        added.version,
        current.geometry_hash,
        added.geometry_hash,
    )
    report.corrected.append(key)
    report.versions_added.append(key)


async def _seed_one(
    session: AsyncSession, doc: ExportDoc, seed: SeedFile, known: _Known, report: SeedReport
) -> None:
    key = doc.type.key
    geometry = geometry_from_doc(doc.version.geometry)
    existing = known.types.get(key)
    adoption = seed.adopt.get(key)
    if existing is None:
        if doc.type.prefix in known.prefixes:
            logger.warning("seed type %s skipped: prefix %s is taken", key, doc.type.prefix)
            report.skipped[key] = "prefix_taken"
            return
        await ts.create_type_locked(
            session, _type_fields(doc), geometry, actor=SEED_ACTOR, origin="seed",
            change_note="seed",
        )  # fmt: skip
        if adoption is not None:  # a fresh insert is already as shipped: nothing to adopt later
            await _mark(session, ADOPTED_KEY, key, adoption.revision)
        known.prefixes.add(doc.type.prefix)
        report.inserted.append(key)
        return
    if (
        adoption is not None
        and (await _setting_map(session, ADOPTED_KEY)).get(key, 0) < adoption.revision
    ):
        await _adopt_one(session, doc, adoption, known, report)
        return
    correction = seed.corrections.get(key)
    if (
        correction is not None
        and (await _setting_map(session, CORRECTED_KEY)).get(key, 0) < correction.revision
    ):
        await _correct_one(session, doc, correction, known, report)
        return
    current = known.current.get(existing.id)
    if current is None or current.geometry_hash == geometry_hash(geometry):
        return
    if doc.version.version < current.version:
        logger.info(
            "seed type %s left alone: the seed has version %d, the database %d",
            key,
            doc.version.version,
            current.version,
        )
        return
    if (
        existing.id in known.foreign_versions
        or existing.id in known.with_sheets
        or existing.origin != "seed"
        or _row_edited(existing, doc)
    ):
        logger.info("seed type %s left alone: edited locally or in use", key)
        return
    await ts.add_version_locked(
        session, key, geometry, actor=SEED_ACTOR, change_note=f"seed update ({key})"
    )
    report.versions_added.append(key)
