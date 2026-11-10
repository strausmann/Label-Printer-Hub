"""Phase 2: BatchRead Schema für GET /api/v1/batches/{id}."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from app.schemas._datetime import serialize_datetime_utc
from app.schemas.job import JobRead


class BatchSummary(BaseModel):
    """Aggregierte Zähler über alle Jobs eines Batches.

    all_terminal wird aus queued + printing berechnet — kein DB-Round-trip nötig.
    Hangar's Result-Page nutzt all_terminal um zu entscheiden, ob ein
    SSE-Stream für Live-Updates geöffnet werden muss.
    """

    model_config = ConfigDict(populate_by_name=True)

    total: int
    queued: int
    printing: int
    done: int
    failed: int  # zählt FAILED + FAILED_RESTART
    cancelled: int
    all_terminal: bool = False  # wird in model_validator gesetzt

    @model_validator(mode="after")
    def _compute_all_terminal(self) -> BatchSummary:
        """all_terminal = True wenn weder queued noch printing Jobs existieren."""
        self.all_terminal = (self.queued + self.printing) == 0
        return self


class TapeRunRead(BaseModel):
    """A tape batch that is printing, waits for a confirmation, or stopped (#277).

    Positions are 1-based in print order (`job_ids`).
    """

    state: Literal["printing", "awaiting_confirmation", "stopped"] = Field(
        description=(
            "`awaiting_confirmation`: the next sub-job starts after `POST .../continue`. "
            "`stopped`: a group failed (the tape ran out, for example); its outcome is unknown, "
            "the labels after it were not started; `POST .../reprint` picks it up."
        )
    )
    current_sub_job: int = Field(description="The sub-job printing or waiting, 1-based.")
    sub_jobs: int
    sub_job_size: int
    sub_job_starts: list[int] = Field(
        description="Where each sub-job starts in `job_ids` (0-based); a reprint re-splits."
    )
    job_ids: list[str] = Field(description="The job of every label, in print order.")
    confirmed_job_ids: list[str] = Field(
        description="Labels of an unknown group the user confirmed as printed (a reprint)."
    )
    unknown_from: int | None = Field(description="First label of the unknown group.")
    unknown_to: int | None = Field(description="Last label of the unknown group.")
    stop_code: str | None = Field(description="Why the run stopped, e.g. `tape_empty`.")


class ReprintRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_label: int = Field(
        ge=1,
        le=100_000,
        description="Reprint from this label (1-based) to the end of the unknown group.",
    )


class ReprintResponse(BaseModel):
    new_job_ids: list[str]
    confirmed_job_ids: list[str]
    job_ids: list[str] = Field(description="The run's labels in print order after the reprint.")
    run: TapeRunRead | None = Field(description="The run after the reprint; `null` if done.")


class BatchRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    printer_id: UUID
    # R2-C5: PrintBatch.created_by ist str (SSO-Email oder API-Key-ID), kein UUID
    created_by: str | None
    created_at: datetime
    jobs: list[JobRead]
    summary: BatchSummary
    run: TapeRunRead | None = Field(
        default=None, description="The tape run while it has something to show (#277)."
    )

    @field_serializer("created_at")
    def _serialise_created_at(self, dt: datetime, _info: object) -> str:
        return serialize_datetime_utc(dt, _info)
