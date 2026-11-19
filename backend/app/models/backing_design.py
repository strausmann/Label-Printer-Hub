# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Backing designs: the vendor print on the back of a sheet's liner (#350, R-350-4).

``strips`` lists the free strips of the back side, where the sheet code may go, as
``{"x", "y", "w", "h"}`` in hundredths of a millimetre (D16), in back-side coordinates: viewed
on the liner, the top is the sheet's top after turning it over along the long edge.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, String, Uuid
from sqlmodel import Column, Field, SQLModel


def _now() -> datetime:
    return datetime.now(UTC)


class BackingDesign(SQLModel, table=True):
    __tablename__ = "backing_designs"
    __table_args__ = (
        CheckConstraint("page_size IN ('A4','Letter')", name="ck_backing_designs_page_size"),
        CheckConstraint("origin IN ('seed','custom','imported')", name="ck_backing_designs_origin"),
    )

    id: UUID = Field(default_factory=uuid4, sa_column=Column(Uuid, primary_key=True))
    key: str = Field(sa_column=Column(String, nullable=False, unique=True))
    name: str = Field(sa_column=Column(String, nullable=False))
    page_size: str = Field(sa_column=Column(String, nullable=False))
    strips: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    origin: str = Field(sa_column=Column(String, nullable=False))
    created_at: datetime = Field(
        default_factory=_now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    updated_at: datetime = Field(
        default_factory=_now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
