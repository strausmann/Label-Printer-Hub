# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Trays of a page printer (spec 7.1, 11.1): one row per IPP ``media-source`` or ``auto``.

Rows are written when the printer is saved (replace-all). The foreign key has no
``ON DELETE`` action on purpose: printers are soft-disabled, never deleted, so a
hard delete of a printer that still has trays is refused instead of silently
dropping them.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String, Uuid
from sqlmodel import Column, Field, SQLModel


class PrinterTray(SQLModel, table=True):
    __tablename__ = "printer_trays"

    printer_id: UUID = Field(sa_column=Column(Uuid, ForeignKey("printers.id"), primary_key=True))
    tray_key: str = Field(sa_column=Column(String, primary_key=True))
    """IPP ``media-source`` keyword, or ``auto`` (send no ``media-source``)."""
    label: str = Field(sa_column=Column(String, nullable=False))
    load_hint: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    enabled: bool = Field(default=True, sa_column=Column(Boolean, nullable=False))
    is_default: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
