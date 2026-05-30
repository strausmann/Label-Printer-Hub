"""Pydantic schemas for the Printers aggregate (Phase 6a REST API).

References:
    docs/superpowers/specs/2026-05-16-phase6a-rest-api-design.md — Printers section
    docs/superpowers/plans/2026-05-16-phase6a-rest-api.md — Task 1 Step 1
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.schemas._datetime import serialize_datetime_utc


class PrinterRead(BaseModel):
    """Full representation of a Printer row, augmented with the paused flag.

    ``paused`` is joined from the ``printer_state`` table; it defaults to
    ``False`` for printers whose state row was not yet created (safe — the
    DB lifespan helper creates state rows at startup, so this only matters
    in tests or during the very first boot).
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str = ""
    name: str
    model: str
    backend: str
    connection: dict[str, object]
    enabled: bool
    paused: bool  # joined from printer_state — always set explicitly by callers
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def _serialise_datetimes(self, dt: datetime, _info: object) -> str:
        return serialize_datetime_utc(dt, _info)


class PrinterStatus(BaseModel):
    """Printer status sourced from the printer_status_cache table.

    The endpoint reads the cache row written by StatusProbeProducer instead
    of doing a synchronous SNMP probe inline.  This makes the response fast
    (<10 ms) even when the printer is offline.

    ``tape_loaded`` is a human-readable string such as
    ``"12mm laminated black/clear"`` or ``None`` when no tape is inserted.
    ``error_state`` mirrors the active PrinterError flags as a string, or
    ``None`` when the printer is ready.
    ``captured_at`` is the UTC timestamp of the probe that last updated the
    cache row.  ``None`` means no probe has completed yet.
    ``last_probe_age_s`` is the age of the cached reading in seconds.
    ``last_error`` is the exception message from the most recent failed probe.
    ``note`` carries a human-readable hint (e.g. "No probe yet").
    """

    printer_id: UUID
    online: bool | None = Field(
        default=None,
        description="True when the printer responded to the last SNMP probe; None = no probe yet",
    )
    tape_loaded: str | None = Field(
        default=None,
        description='e.g. "12mm laminated black/clear"; None when no tape is loaded',
    )
    error_state: str | None = Field(
        default=None,
        description="Active error flags as a string; None when printer is ready",
    )
    captured_at: datetime | None = Field(
        default=None,
        description="UTC timestamp of the probe that produced this reading; None if no probe yet",
    )
    last_probe_age_s: int | None = Field(
        default=None,
        description="Age of the cached reading in seconds",
    )
    last_error: str | None = Field(
        default=None,
        description="Exception message from the most recent failed probe",
    )
    note: str | None = Field(
        default=None,
        description="Human-readable hint, e.g. 'No probe yet'",
    )

    @field_serializer("captured_at")
    def _serialise_captured_at(self, dt: datetime | None, _info: object) -> str | None:
        if dt is None:
            return None
        return serialize_datetime_utc(dt, _info)
