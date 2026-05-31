"""Phase 2: GET /api/batches/{id} — Snapshot für Hangar Result-Page Initial-Render."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_read
from app.db.session import get_session
from app.models.job import JobState
from app.repositories import jobs as jobs_repo
from app.repositories import print_batches as batches_repo
from app.schemas.batch_read import BatchRead, BatchSummary
from app.schemas.job import JobRead

router = APIRouter(prefix="/api/batches", tags=["batches"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ReadAuthDep = Annotated[AuthContext, Depends(require_read)]


@router.get("/{batch_id}", response_model=BatchRead)
async def get_batch(
    batch_id: UUID,
    session: SessionDep,
    _auth: ReadAuthDep,
) -> BatchRead:
    """Snapshot eines Batches + aller aktuellen Job-States.

    Wird von Hangar's /admin/print/result/{batch_id} für das initiale
    Rendering genutzt. summary.all_terminal == False bedeutet, dass Hangar
    einen SSE-Stream zu /api/events?batch_id=... öffnen sollte für
    Live-Updates.
    """
    batch = await batches_repo.get(session, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")

    # batch.job_ids is list[str] — convert to UUID for repo query
    job_uuids = [UUID(jid) for jid in batch.job_ids]
    fetched_jobs = await jobs_repo.list_by_ids(session, job_uuids)
    job_map = {str(j.id): j for j in fetched_jobs}

    # Reihenfolge entspricht batch.job_ids; cleanup-evicted Jobs werden übersprungen
    ordered = [job_map[jid] for jid in batch.job_ids if jid in job_map]

    summary = BatchSummary(
        total=len(ordered),
        queued=sum(1 for j in ordered if j.state == JobState.QUEUED.value),
        printing=sum(1 for j in ordered if j.state == JobState.PRINTING.value),
        done=sum(1 for j in ordered if j.state == JobState.DONE.value),
        failed=sum(
            1 for j in ordered if j.state in (JobState.FAILED.value, JobState.FAILED_RESTART.value)
        ),
    )

    return BatchRead(
        id=batch.id,
        printer_id=batch.printer_id,
        created_by=batch.created_by,
        created_at=batch.created_at,
        jobs=[JobRead.model_validate(j) for j in ordered],
        summary=summary,
    )
