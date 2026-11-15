# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""What the hub knows about a page printer, read the one way every caller reads it.

The status cache holds the printer's last answer. A printer that never answered carries the
producer's placeholder (offline, empty summary); that is *unknown*, not "reports nothing". The
capabilities endpoint and the sheet print path both ask here, so they agree on what unknown
means: ``render_dpi`` 600 (OC-26) and ``margins_hmm`` ``None``, which the planner counts as 5.0 mm
on every side (OC-16).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.printer_status_cache import PrinterStatusCache
from app.printer_backends.ipp.attributes import IppStatusRecord, Margins
from app.services.producers.ipp_status_producer import _empty_summary

__all__ = [
    "DEFAULT_RENDER_DPI",
    "MAX_RENDER_DPI",
    "PrinterFacts",
    "StatusRead",
    "facts_of",
    "load_printer_facts",
    "read_status",
]

MAX_RENDER_DPI: Final = 600
DEFAULT_RENDER_DPI: Final = 600  # OC-26: unknown resolution


@dataclass(frozen=True)
class StatusRead:
    """``record`` is ``None`` when the cache holds nothing usable; ``never_answered`` says that
    this is the producer's placeholder."""

    record: IppStatusRecord | None
    never_answered: bool


@dataclass(frozen=True)
class PrinterFacts:
    resolutions_dpi: list[int]
    margins_hmm: Margins | None
    render_dpi: int


def read_status(parsed: Mapping[str, Any]) -> StatusRead:
    """Validate a cache row's ``parsed`` dict; the placeholder reads as no record at all."""
    try:
        record: IppStatusRecord | None = IppStatusRecord.model_validate(parsed)
    except ValidationError:
        return StatusRead(None, False)
    if record is not None and not record.online and record.summary == _empty_summary():
        return StatusRead(None, True)
    return StatusRead(record, False)


def facts_of(status: StatusRead) -> PrinterFacts:
    """Resolutions, hardware margins and the job's render resolution (highest, at most 600)."""
    summary = status.record.summary if status.record else None
    dpis = list(summary.resolutions_dpi) if summary else []
    usable = [d for d in dpis if d > 0]
    return PrinterFacts(
        resolutions_dpi=dpis,
        margins_hmm=summary.margins_hmm if summary else None,
        render_dpi=min(max(usable), MAX_RENDER_DPI) if usable else DEFAULT_RENDER_DPI,
    )


async def load_printer_facts(session: AsyncSession, printer_id: UUID) -> PrinterFacts:
    row = await session.get(PrinterStatusCache, printer_id)
    return facts_of(read_status((row.parsed if row is not None else None) or {}))
