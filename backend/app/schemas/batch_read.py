"""Phase 2: BatchRead Schema für GET /api/batches/{id}."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

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
    all_terminal: bool = False  # wird in model_validator gesetzt

    @model_validator(mode="after")
    def _compute_all_terminal(self) -> BatchSummary:
        """all_terminal = True wenn weder queued noch printing Jobs existieren."""
        self.all_terminal = (self.queued + self.printing) == 0
        return self


class BatchRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    printer_id: UUID
    # R2-C5: PrintBatch.created_by ist str (SSO-Email oder API-Key-ID), kein UUID
    created_by: str | None
    created_at: datetime
    jobs: list[JobRead]
    summary: BatchSummary
