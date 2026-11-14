# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SQLModel table for the hardware identity of a printer (#231)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime
from sqlmodel import Column, Field, SQLModel


class PrinterIdentity(SQLModel, table=True):
    """The device behind a printer's address, as the status probes saw it.

    ``hardware_id`` is a serial number, an IPP ``printer-uuid`` or a MAC address (``kind`` says
    which). It lives in its own table so a probe never moves ``printers.updated_at``. The
    ``observed_*`` and ``mismatch_since`` columns hold a differing identity once swap detection
    acts on it; this table's writer in ``hardware_identity`` only sets the stored identity.
    """

    __tablename__ = "printer_identity"

    printer_id: UUID = Field(primary_key=True, foreign_key="printers.id")
    hardware_id: str | None = Field(default=None)
    hardware_id_kind: str | None = Field(default=None)  # serial | ipp_uuid | mac
    hardware_id_seen_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    observed_id: str | None = Field(default=None)
    observed_kind: str | None = Field(default=None)
    mismatch_since: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
