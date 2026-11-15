# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SQLModel table for the roll (tape cassette) currently recorded for a printer (#229)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, text
from sqlmodel import Column, Field, SQLModel


class PrinterRoll(SQLModel, table=True):
    """The roll identity ``(width_mm, media_raw)`` last seen, and the colour the operator gave it.

    The printer reports no tape colour over the network, so the colour is operator input that
    belongs to one roll: a changed identity clears it and raises ``prompt_pending``.
    """

    __tablename__ = "printer_roll"

    printer_id: UUID = Field(primary_key=True, foreign_key="printers.id")
    width_mm: int | None = Field(default=None)
    media_raw: str | None = Field(default=None)
    colour: str | None = Field(default=None)
    set_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    prompt_pending: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("0")),
    )
    changed_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
