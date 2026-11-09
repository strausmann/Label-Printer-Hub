"""Pydantic schemas for the Printers aggregate (Phase 6a REST API).

References:
    docs/superpowers/specs/2026-05-16-phase6a-rest-api-design.md — Printers section
    docs/superpowers/plans/2026-05-16-phase6a-rest-api.md — Task 1 Step 1
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.schemas._datetime import serialize_datetime_utc
from app.services.tape_status import TapeColourName


class PauseRead(BaseModel):
    """Why a printer is paused: ``user`` (manual) or ``printer_error`` (automatic)."""

    source: Literal["user", "printer_error"]
    reason_code: str
    since: datetime

    @field_serializer("since")
    def _serialise_since(self, dt: datetime, _info: object) -> str:
        return serialize_datetime_utc(dt, _info)


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
    paused: bool  # DB flag OR queue worker paused — always set explicitly by callers
    pause: PauseRead | None = None  # reason, when the queue knows one
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def _serialise_datetimes(self, dt: datetime, _info: object) -> str:
        return serialize_datetime_utc(dt, _info)


class ReasonRead(BaseModel):
    """One ``printer-state-reasons`` keyword of a page printer (severity suffix removed)."""

    keyword: str
    severity: Literal["report", "warning", "error"]
    blocking: bool


class MarkerRead(BaseModel):
    """One supply (toner, ink, waste container) of a page printer."""

    name: str
    color: str | None
    type: str | None
    level_percent: int | None
    some_remaining: bool
    low: bool
    empty: bool


class TrayStatusRead(BaseModel):
    """A configured tray of a page printer plus what the printer reports as loaded in it."""

    key: str
    label: str
    load_hint: str | None
    enabled: bool
    is_default: bool
    media: str | None = Field(
        default=None, description="Loaded media as the printer reports it; None when not reported"
    )


class TapeRead(BaseModel):
    """The tape loaded in a polled tape printer (``GET /printers/{id}/tape``)."""

    width_mm: int = Field(description="Width of the loaded tape in mm")
    label: str = Field(description='Display label from the printer model, e.g. "62mm DK"')
    media_raw: str | None = Field(
        default=None, description="The media name text as the printer reported it"
    )
    colour: TapeColourName | None = Field(
        default=None, description="Tape colour from the operator's roll record; None if unknown"
    )


class RollRead(BaseModel):
    """The roll recorded for a printer (``GET/PUT /printers/{id}/roll``)."""

    width_mm: int | None = Field(default=None, description="Width of the roll last seen, in mm")
    media_raw: str | None = Field(
        default=None, description="The media name text of the roll as the printer reported it"
    )
    colour: TapeColourName | None = Field(
        default=None, description="Tape colour the operator gave this roll; None if unknown"
    )
    set_at: datetime | None = Field(default=None, description="When the colour was recorded")
    prompt_pending: bool = Field(
        default=False, description="True while the operator is still to be asked for the colour"
    )

    @field_serializer("set_at")
    def _serialise_set_at(self, dt: datetime | None, _info: object) -> str | None:
        return serialize_datetime_utc(dt, _info) if dt is not None else None


class RollColourUpdate(BaseModel):
    """Body of ``PUT /printers/{id}/roll``."""

    model_config = ConfigDict(extra="forbid")

    colour: TapeColourName | None = Field(
        description="The tape colour; null skips the question and clears a recorded colour"
    )
    width_mm: int | None = Field(
        default=None,
        description=(
            "Width of the roll the operator saw. When given and different from the stored "
            "roll, the call answers 409 roll-changed instead of colouring the new roll."
        ),
    )
    media_raw: str | None = Field(
        default=None,
        description="The roll media_raw the operator saw; checked like width_mm when given",
    )


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
    cache row.  ``None`` means no probe has completed yet.  For a page printer
    (``kind="page"``) that went offline it stays the time of the last
    *successful* reading; ``online`` and ``last_error`` tell that it is stale.
    ``last_probe_age_s`` is the age of the cached reading in seconds (for an
    offline page printer: since its last successful reading).
    ``last_error`` is the exception message from the most recent failed probe.
    ``note`` carries a human-readable hint (e.g. "No probe yet").
    ``polled`` is ``False`` when no status producer runs for the printer (SNMP discovery
    off, printer disabled or not wired). ``stale`` is ``True`` when the last probe attempt
    (``printer_status_cache.updated_at``) is older than
    ``max(90, 3 * probe interval, 2 * max backoff)`` seconds (an IPP printer that stopped answering
    is probed with a backoff of up to 300 s, so its bound is 600 s),
    or implausibly in the future. For an unpolled or stale printer ``online`` is
    ``None`` and the cached values (tape, error state, markers, trays) are not returned;
    ``captured_at`` and ``last_probe_age_s`` stay so a client can show how old the last
    reading is.
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
    tape_width_mm: int | None = Field(
        default=None,
        description="Width of the loaded tape in mm; None when no tape is loaded or unknown",
    )
    tape_colour: TapeColourName | None = Field(
        default=None,
        description=(
            "Tape colour from the operator's roll record. The printer reports none over the "
            "network, so this stays None until a roll is recorded."
        ),
    )
    roll_prompt: bool = Field(
        default=False,
        description=(
            "True when the roll changed and the operator is still to be asked for the tape "
            "colour (``PUT /printers/{id}/roll``); False for an unpolled or stale printer"
        ),
    )
    error_state: str | None = Field(
        default=None,
        description="Active error flags as a string; None when printer is ready",
    )
    captured_at: datetime | None = Field(
        default=None,
        description=(
            "UTC timestamp of the probe that produced this reading; None if no probe yet. "
            "A page printer that went offline keeps the time of its last successful reading."
        ),
    )
    last_probe_age_s: int | None = Field(
        default=None,
        description=(
            "Age of the cached reading in seconds; for an offline page printer, "
            "since its last successful reading"
        ),
    )
    last_error: str | None = Field(
        default=None,
        description="Exception message from the most recent failed probe",
    )
    note: str | None = Field(
        default=None,
        description="Human-readable hint, e.g. 'No probe yet'",
    )
    stale: bool = Field(
        default=False,
        description="True when the last probe attempt is older than the staleness bound",
    )
    polled: bool = Field(
        default=True,
        description="False when no status producer runs for this printer",
    )
    # Page printers (IPP) only; all ``None`` for tape printers.
    kind: Literal["tape", "page"] | None = Field(
        default=None, description="'page' for IPP page printers; None for tape printers"
    )
    printer_state: Literal["idle", "printing", "stopped"] | None = None
    state_reasons: list[ReasonRead] | None = None
    markers: list[MarkerRead] | None = None
    trays: list[TrayStatusRead] | None = None
    jobs_ahead: int | None = Field(
        default=None, description="Jobs on the printer ahead of the hub's own"
    )

    @field_serializer("captured_at")
    def _serialise_captured_at(self, dt: datetime | None, _info: object) -> str | None:
        if dt is None:
            return None
        return serialize_datetime_utc(dt, _info)
