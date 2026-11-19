# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""How a page printer's tray takes paper (#350, R-350-5).

Its own table, not a column of ``printer_trays``: the tray list is replaced on every printer
save, and a column there would be lost. ``print_side`` is the face that gets printed as the
sheet lies in the tray; ``leading_edge`` is the edge of the printed image that lands at the
sheet edge put in first.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Uuid
from sqlmodel import Column, Field, SQLModel


def _now() -> datetime:
    return datetime.now(UTC)


class PrinterTrayLoading(SQLModel, table=True):
    __tablename__ = "printer_tray_loading"
    __table_args__ = (
        CheckConstraint("print_side IN ('up','down')", name="ck_printer_tray_loading_print_side"),
        CheckConstraint(
            "leading_edge IN ('top','bottom')", name="ck_printer_tray_loading_leading_edge"
        ),
    )

    printer_id: UUID = Field(sa_column=Column(Uuid, ForeignKey("printers.id"), primary_key=True))
    tray_key: str = Field(sa_column=Column(String, primary_key=True))
    print_side: str = Field(sa_column=Column(String, nullable=False))
    leading_edge: str = Field(sa_column=Column(String, nullable=False))
    updated_at: datetime = Field(
        default_factory=_now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    updated_by: str | None = Field(default=None, sa_column=Column(String, nullable=True))
