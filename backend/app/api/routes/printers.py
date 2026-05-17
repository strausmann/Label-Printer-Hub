"""REST endpoints for the Printers aggregate (Phase 6a).

All seven endpoints are backed by the Phase 5 DB repositories.  The status
probe path wraps the synchronous-style network I/O in ``asyncio.to_thread``
as required by the Brother PT raster spec (sync I/O must not block the
FastAPI event loop).

Routes
------
GET  /api/printers                — list all printers + paused flag
GET  /api/printers/{id}/status    — force fresh ESC i S probe; upserts cache
GET  /api/printers/{id}/tape      — current tape spec via TapeRegistry
GET  /api/printers/{id}/queue     — jobs in QUEUED or PRINTING state
POST /api/printers/{id}/pause     — set paused=True  (204 No Content)
POST /api/printers/{id}/resume    — set paused=False (204 No Content)
POST /api/printers/{id}/queue/clear — bulk-cancel QUEUED jobs (204 No Content)

References:
    docs/superpowers/specs/2026-05-16-phase6a-rest-api-design.md — Printers section
    docs/superpowers/plans/2026-05-16-phase6a-rest-api.md — Task 1
"""

from __future__ import annotations

import dataclasses
import logging
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import AuthContext, check_printer_access
from app.auth.scope_deps import require_print, require_read
from app.db.session import get_session
from app.models.job import JobState
from app.repositories import jobs as jobs_repo
from app.repositories import printer_state as printer_state_repo
from app.repositories import printer_status_cache as cache_repo
from app.repositories import printers as printers_repo
from app.schemas.printer import PrinterRead, PrinterStatus
from app.services.status_block import MediaType, PrinterError, StatusBlockParser
from app.services.tape_registry import TapeRegistry, UnknownTapeError

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/printers", tags=["printers"])

# Type alias for the session dependency
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ReadAuthDep = Annotated[AuthContext, Depends(require_read)]
PrintAuthDep = Annotated[AuthContext, Depends(require_print)]


# ---------------------------------------------------------------------------
# Helper: 404 on unknown printer
# ---------------------------------------------------------------------------


async def _get_printer_or_404(session: AsyncSession, printer_id: UUID) -> Any:
    """Return the Printer row or raise HTTP 404 with a ProblemDetail-style body."""
    printer = await printers_repo.get(session, printer_id)
    if printer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"printer {printer_id} not found",
        )
    return printer


# ---------------------------------------------------------------------------
# GET /api/printers
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[PrinterRead],
    summary="List all printers",
    description=(
        "Returns every registered printer.  The ``paused`` flag is joined "
        "from ``printer_state``; it is ``false`` when no state row exists yet."
    ),
)
async def list_printers(session: SessionDep, _auth: ReadAuthDep) -> list[PrinterRead]:
    """List all printers with their pause state."""
    printers = await printers_repo.list_all(session)
    result: list[PrinterRead] = []
    for p in printers:
        state = await printer_state_repo.get(session, p.id)
        paused = state.paused if state is not None else False
        result.append(
            PrinterRead(
                id=p.id,
                name=p.name,
                model=p.model,
                backend=p.backend,
                connection=dict(p.connection),
                enabled=p.enabled,
                paused=paused,
                created_at=p.created_at,
                updated_at=p.updated_at,
            )
        )
    return result


# ---------------------------------------------------------------------------
# GET /api/printers/{id}/status
# ---------------------------------------------------------------------------


def _probe_status_sync(host: str, port: int = 9100) -> dict[str, Any]:
    """Synchronous ESC i S probe — runs in a thread via asyncio.to_thread.

    Opens a blocking TCP socket, sends ESC i S, reads the 32-byte reply
    and parses it.  Returns a dict with the parsed fields needed for
    PrinterStatus and the cache write-back.

    Raises:
        OSError: if the TCP connection fails (printer offline / unreachable).
        StatusQueryFailedError: if the reply is malformed.
    """
    import socket

    from app.services.status_block import STATUS_BLOCK_SIZE

    esc_i_s = b"\x1b\x69\x53"
    sock = socket.create_connection((host, port), timeout=5.0)
    try:
        sock.sendall(esc_i_s)
        raw = b""
        while len(raw) < STATUS_BLOCK_SIZE:
            chunk = sock.recv(STATUS_BLOCK_SIZE - len(raw))
            if not chunk:
                break
            raw += chunk
    finally:
        sock.close()

    block = StatusBlockParser.parse(raw)
    return {
        "raw": raw,
        "block": block,
    }


def _tape_label(block: Any) -> str | None:
    """Derive a human-readable tape description from a parsed StatusBlock."""
    if block.media_width_mm == 0:
        return None
    media_name = block.media_type.name.replace("_", " ").lower()
    tape_color = block.tape_color.name.replace("_", " ").lower()
    text_color = block.text_color.name.replace("_", " ").lower()
    return f"{block.media_width_mm}mm {media_name} {tape_color}/{text_color}"


def _error_label(block: Any) -> str | None:
    """Return active error flags as a string, or None when no errors."""
    active = [
        flag.name or str(int(flag))
        for flag in PrinterError
        if flag in block.errors and flag != PrinterError.NONE
    ]
    return ", ".join(active) if active else None


@router.get(
    "/{printer_id}/status",
    response_model=PrinterStatus,
    summary="Return the latest cached printer status",
    description=(
        "Returns the most recent status written by the background SNMP probe worker. "
        "The response is served from ``printer_status_cache`` — no synchronous SNMP "
        "probe is performed, so the response always returns in <10 ms. "
        "When no probe has completed yet ``online`` is ``null`` and ``note`` explains why. "
        "Returns 404 when the printer is not registered."
    ),
)
async def get_printer_status(
    printer_id: UUID,
    session: SessionDep,
    _auth: ReadAuthDep,
) -> PrinterStatus:
    """Return the latest cached status for a printer; no sync SNMP probe."""
    await _get_printer_or_404(session, printer_id)
    if _auth is not None:
        check_printer_access(_auth, printer_id)

    row = await cache_repo.get(session, printer_id)
    if row is None or row.captured_at is None:
        return PrinterStatus(
            printer_id=printer_id,
            online=None,
            captured_at=None,
            note="No probe yet — wait up to 30s for first probe cycle",
        )

    parsed = row.parsed or {}
    captured = row.captured_at
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=UTC)
    age_s = int((datetime.now(UTC) - captured).total_seconds())

    loaded_tape_mm = parsed.get("loaded_tape_mm")
    tape_loaded = f"{loaded_tape_mm}mm" if loaded_tape_mm else None

    error_flags = parsed.get("error_flags") or []
    error_state = ", ".join(error_flags) if error_flags else None

    return PrinterStatus(
        printer_id=printer_id,
        online=parsed.get("online"),
        tape_loaded=tape_loaded,
        error_state=error_state,
        captured_at=row.captured_at,
        last_probe_age_s=age_s,
        last_error=parsed.get("last_error"),
    )


# ---------------------------------------------------------------------------
# GET /api/printers/{id}/tape
# ---------------------------------------------------------------------------


@router.get(
    "/{printer_id}/tape",
    summary="Get the current tape spec",
    description=(
        "Returns the tape specification for the tape currently loaded in the "
        "printer, derived from the cached status block.  Returns 404 if the "
        "printer has no cached status or no tape is loaded."
    ),
)
async def get_printer_tape(
    printer_id: UUID,
    session: SessionDep,
    _auth: ReadAuthDep,
) -> dict[str, object]:
    """Return the current tape spec for a printer."""
    await _get_printer_or_404(session, printer_id)

    cache = await cache_repo.get(session, printer_id)
    if cache is None or cache.parsed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no cached status for printer {printer_id}; call /status first",
        )

    parsed = cache.parsed
    width_mm = int(parsed.get("media_width_mm", 0))
    if width_mm == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no tape loaded in printer {printer_id}",
        )

    try:
        media_type = MediaType[str(parsed.get("media_type", "UNKNOWN"))]
    except KeyError:
        media_type = MediaType.UNKNOWN

    tape_registry = TapeRegistry()
    try:
        spec = tape_registry.lookup_pt(width_mm, media_type)
    except UnknownTapeError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return dataclasses.asdict(spec)


# ---------------------------------------------------------------------------
# GET /api/printers/{id}/queue
# ---------------------------------------------------------------------------


@router.get(
    "/{printer_id}/queue",
    summary="Get the active job queue for a printer",
    description=(
        "Returns all jobs in ``queued`` or ``printing`` state for this "
        "printer, ordered by creation time."
    ),
)
async def get_printer_queue(
    printer_id: UUID,
    session: SessionDep,
    _auth: ReadAuthDep,
) -> list[dict[str, object]]:
    """Return queued and printing jobs for a printer."""
    await _get_printer_or_404(session, printer_id)

    active_jobs = await jobs_repo.list_active(session)
    printer_jobs = [j for j in active_jobs if j.printer_id == printer_id]

    return [
        {
            "id": str(j.id),
            "printer_id": str(j.printer_id),
            "template_key": j.template_key,
            "state": j.state,
            "payload": j.payload,
            "created_at": j.created_at.isoformat(),
        }
        for j in printer_jobs
    ]


# ---------------------------------------------------------------------------
# POST /api/printers/{id}/pause
# ---------------------------------------------------------------------------


@router.post(
    "/{printer_id}/pause",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Pause job dispatch for a printer",
    description=(
        "Sets ``printer_state.paused = true`` for this printer.  "
        "New jobs can still be queued but the worker will not dispatch them "
        "until the printer is resumed.  Idempotent — pausing an already-paused "
        "printer returns 204 without error."
    ),
)
async def pause_printer(
    printer_id: UUID,
    session: SessionDep,
    _auth: PrintAuthDep,
) -> None:
    """Pause a printer."""
    await _get_printer_or_404(session, printer_id)
    if _auth is not None:
        check_printer_access(_auth, printer_id)
    await printer_state_repo.set_paused(session, printer_id, True)


# ---------------------------------------------------------------------------
# POST /api/printers/{id}/resume
# ---------------------------------------------------------------------------


@router.post(
    "/{printer_id}/resume",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Resume job dispatch for a printer",
    description=(
        "Sets ``printer_state.paused = false``.  Idempotent — resuming an "
        "already-active printer returns 204 without error."
    ),
)
async def resume_printer(
    printer_id: UUID,
    session: SessionDep,
    _auth: PrintAuthDep,
) -> None:
    """Resume a printer."""
    await _get_printer_or_404(session, printer_id)
    if _auth is not None:
        check_printer_access(_auth, printer_id)
    await printer_state_repo.set_paused(session, printer_id, False)


# ---------------------------------------------------------------------------
# POST /api/printers/{id}/queue/clear
# ---------------------------------------------------------------------------


@router.post(
    "/{printer_id}/queue/clear",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel all queued jobs for a printer",
    description=(
        "Bulk-cancels every job in ``queued`` state for this printer.  "
        "Jobs in ``printing`` state are intentionally **not** cancelled — "
        "a mid-print abort is unsafe over TCP/9100 because the raster data is "
        "already on the wire.  Returns 204 even when there are no queued jobs."
    ),
)
async def clear_printer_queue(
    printer_id: UUID,
    session: SessionDep,
    _auth: PrintAuthDep,
) -> None:
    """Cancel all QUEUED (not PRINTING) jobs for a printer."""
    await _get_printer_or_404(session, printer_id)
    if _auth is not None:
        check_printer_access(_auth, printer_id)

    active_jobs = await jobs_repo.list_active(session)
    queued_jobs = [
        j for j in active_jobs if j.printer_id == printer_id and j.state == JobState.QUEUED.value
    ]

    for job in queued_jobs:
        await jobs_repo.mark_cancelled(session, job.id)
