# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SQLModel tables for the sheet archive (spec 7.1).

All lengths are integer hundredths of a millimetre (D16). ``sheet_cells.job_id`` is a plain
UUID column and deliberately not a foreign key (OC-39): a cell must survive its job row.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    false,
)
from sqlmodel import Column, Field, SQLModel


def _now() -> datetime:
    return datetime.now(UTC)


def _dt(*, nullable: bool = False) -> Column[Any]:
    return Column(DateTime(timezone=True), nullable=nullable)


class SheetType(SQLModel, table=True):
    __tablename__ = "sheet_types"
    __table_args__ = (
        CheckConstraint("origin IN ('seed','custom','imported')", name="ck_sheet_types_origin"),
    )

    id: UUID = Field(default_factory=uuid4, sa_column=Column(Uuid, primary_key=True))
    key: str = Field(sa_column=Column(String, nullable=False, unique=True))
    prefix: str = Field(sa_column=Column(String, nullable=False, unique=True))
    vendor: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    product_codes: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    description: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    allow_qr: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    verified: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    origin: str = Field(sa_column=Column(String, nullable=False))
    source_name: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    source_url: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    notes: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    archived_at: datetime | None = Field(default=None, sa_column=_dt(nullable=True))
    created_at: datetime = Field(default_factory=_now, sa_column=_dt())
    updated_at: datetime = Field(default_factory=_now, sa_column=_dt())
    created_by: str | None = Field(default=None, sa_column=Column(String, nullable=True))


class SheetTypeVersion(SQLModel, table=True):
    """Immutable after insert; geometry in hundredths of a millimetre (D16)."""

    __tablename__ = "sheet_type_versions"
    __table_args__ = (
        UniqueConstraint("type_id", "version", name="uq_sheet_type_versions_type_version"),
        CheckConstraint("shape IN ('rectangle','round')", name="ck_sheet_type_versions_shape"),
        CheckConstraint("page_size IN ('A4','Letter')", name="ck_sheet_type_versions_page_size"),
    )

    id: UUID = Field(default_factory=uuid4, sa_column=Column(Uuid, primary_key=True))
    type_id: UUID = Field(sa_column=Column(Uuid, ForeignKey("sheet_types.id"), nullable=False))
    version: int = Field(sa_column=Column(Integer, nullable=False))
    page_size: str = Field(sa_column=Column(String, nullable=False))
    page_w: int = Field(sa_column=Column(Integer, nullable=False))  # D16
    page_h: int = Field(sa_column=Column(Integer, nullable=False))  # D16
    label_w: int = Field(sa_column=Column(Integer, nullable=False))  # D16
    label_h: int = Field(sa_column=Column(Integer, nullable=False))  # D16
    cols: int = Field(sa_column=Column(Integer, nullable=False))
    rows: int = Field(sa_column=Column(Integer, nullable=False))
    pitch_x: int = Field(sa_column=Column(Integer, nullable=False))  # D16
    pitch_y: int = Field(sa_column=Column(Integer, nullable=False))  # D16
    margin_top: int = Field(sa_column=Column(Integer, nullable=False))  # D16
    margin_left: int = Field(sa_column=Column(Integer, nullable=False))  # D16
    corner_radius: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))  # D16
    shape: str = Field(sa_column=Column(String, nullable=False))
    geometry_hash: str = Field(sa_column=Column(String, nullable=False))
    created_at: datetime = Field(default_factory=_now, sa_column=_dt())
    created_by: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    change_note: str | None = Field(default=None, sa_column=Column(String, nullable=True))


class SheetIdCounter(SQLModel, table=True):
    """Per-prefix counter; never decremented, never reset (spec 7.1)."""

    __tablename__ = "sheet_id_counters"

    prefix: str = Field(sa_column=Column(String, primary_key=True))
    next_value: int = Field(sa_column=Column(Integer, nullable=False))


class Sheet(SQLModel, table=True):
    __tablename__ = "sheets"
    __table_args__ = (
        CheckConstraint("state IN ('active','discarded')", name="ck_sheets_state"),
        CheckConstraint(
            "id_placement IN ('cell','margin','manual')", name="ck_sheets_id_placement"
        ),
        Index("ix_sheets_type_state", "type_id", "state"),
    )

    id: UUID = Field(default_factory=uuid4, sa_column=Column(Uuid, primary_key=True))
    code: str = Field(sa_column=Column(String, nullable=False, unique=True))
    type_id: UUID = Field(sa_column=Column(Uuid, ForeignKey("sheet_types.id"), nullable=False))
    # D14: the version is pinned for the life of the sheet.
    type_version_id: UUID = Field(
        sa_column=Column(Uuid, ForeignKey("sheet_type_versions.id"), nullable=False)
    )
    state: str = Field(default="active", sa_column=Column(String, nullable=False))
    discarded_at: datetime | None = Field(default=None, sa_column=_dt(nullable=True))
    discarded_by: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    id_placement: str = Field(sa_column=Column(String, nullable=False))
    id_printed: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    # The feed-direction mark (spec 10.2a) has its own flag, independent of ``id_printed``.
    feed_mark_printed: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=false()),
    )
    note: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    created_at: datetime = Field(default_factory=_now, sa_column=_dt())
    created_by: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    last_used_at: datetime | None = Field(default=None, sa_column=_dt(nullable=True))


class SheetCell(SQLModel, table=True):
    """One row per non-free cell; a free cell has no row."""

    __tablename__ = "sheet_cells"
    __table_args__ = (
        CheckConstraint("state IN ('reserved','used','unconfirmed')", name="ck_sheet_cells_state"),
        Index("ix_sheet_cells_source_ref", "source", "ref"),
        Index("ix_sheet_cells_job_id", "job_id"),
    )

    sheet_id: UUID = Field(sa_column=Column(Uuid, ForeignKey("sheets.id"), primary_key=True))
    cell_no: int = Field(sa_column=Column(Integer, primary_key=True, autoincrement=False))
    state: str = Field(sa_column=Column(String, nullable=False))
    # Plain column, not a foreign key (OC-39): the cell outlives its job row.
    job_id: UUID | None = Field(default=None, sa_column=Column(Uuid, nullable=True))
    source: str = Field(sa_column=Column(String, nullable=False))
    purpose: str | None = Field(
        default=None, sa_column=Column(String, nullable=True)
    )  # <= 120 chars
    ref: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    marked_by_hand: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    updated_at: datetime = Field(default_factory=_now, sa_column=_dt())
    updated_by: str | None = Field(default=None, sa_column=Column(String, nullable=True))


class SheetWriteLock(SQLModel, table=True):
    """Single-row table; writing it first takes SQLite's write lock (see sheets.locking)."""

    __tablename__ = "sheet_write_lock"
    __table_args__ = (CheckConstraint("id = 1", name="ck_sheet_write_lock_single_row"),)

    id: int = Field(default=1, sa_column=Column(Integer, primary_key=True, autoincrement=False))
    seq: int = Field(sa_column=Column(Integer, nullable=False))
