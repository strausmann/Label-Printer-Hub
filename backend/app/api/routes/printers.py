# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""REST endpoints for the Printers aggregate (Phase 6a).

All seven endpoints are backed by the Phase 5 DB repositories.  The status
probe path wraps the synchronous-style network I/O in ``asyncio.to_thread``
as required by the Brother PT raster spec (sync I/O must not block the
FastAPI event loop).

Routes
------
GET  /api/v1/printers                — list all printers + paused flag
GET  /api/v1/printers/{id}/status    — force fresh ESC i S probe; upserts cache
GET  /api/v1/printers/{id}/tape      — current tape spec via TapeRegistry
GET  /api/v1/printers/{id}/queue     — jobs in QUEUED or PRINTING state
POST /api/v1/printers/{id}/pause     — set paused=True  (204 No Content)
POST /api/v1/printers/{id}/resume    — set paused=False (204 No Content)
POST /api/v1/printers/{id}/queue/clear — bulk-cancel QUEUED jobs (204 No Content)

References:
    docs/superpowers/specs/2026-05-16-phase6a-rest-api-design.md — Printers section
    docs/superpowers/plans/2026-05-16-phase6a-rest-api.md — Task 1
"""

from __future__ import annotations

import contextlib
import logging
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.api.dependencies.printer_runtime import get_printer_runtime
from app.api.routes.pause_view import pause_view
from app.auth.dependencies import AuthContext, check_printer_access
from app.auth.ownership import may_see, owner_only
from app.auth.scope_deps import require_print, require_read
from app.config import get_settings
from app.db.session import get_session
from app.models.job import JobState
from app.models.printer_identity import PrinterIdentity
from app.models.printer_tray import PrinterTray
from app.printer_backends.ipp.attributes import IppStatusRecord
from app.repositories import jobs as jobs_repo
from app.repositories import printer_identity as identity_repo
from app.repositories import printer_roll as roll_repo
from app.repositories import printer_state as printer_state_repo
from app.repositories import printer_status_cache as cache_repo
from app.repositories import printers as printers_repo
from app.schemas.label_layout import LayoutDefault, parse_layout_defaults
from app.schemas.printer import (
    MarkerRead,
    PrinterRead,
    PrinterStatus,
    ReasonRead,
    TapeRead,
    TrayStatusRead,
)
from app.schemas.problem import DetailError
from app.services.print_queue import PrinterAlreadyActiveError
from app.services.printer_admin_service import snmp_view
from app.services.printer_runtime import PrinterRuntime
from app.services.status_block import PrinterError
from app.services.status_freshness import backoff_of, is_stale, stale_after_s
from app.services.tape_status import read_tape_status

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/printers", tags=["printers"])


def _connection_view(printer: Any, auth: AuthContext | None) -> dict[str, object]:
    """The ``connection`` a caller may see.

    For an ``ipp`` printer the URI is connection detail (spec 14, 18): only admin callers
    see it; everyone else gets ``{"tls_verify": ...}``. Tape rows show ``snmp.community_set``
    instead of the SNMP community, for every caller (#296).
    """
    connection = dict(printer.connection or {})
    if printer.backend != "ipp":
        return snmp_view(connection)
    if auth is not None and auth.scope == "admin":
        return connection
    return {"tls_verify": bool(connection.get("tls_verify", True))}


def _layout_defaults_view(printer: Any) -> dict[str, LayoutDefault]:
    """The stored layout defaults per tape width (string keys), without the invalid entries.

    Not sensitive: it is what the print dialog preselects. Page printers store none.
    """
    return {
        str(width): value for width, value in parse_layout_defaults(printer.layout_defaults).items()
    }


def _is_admin(auth: AuthContext | None) -> bool:
    return auth is not None and auth.scope == "admin"


def _identity_fields(row: PrinterIdentity | None) -> dict[str, Any]:
    """Field by field, never through ``from_attributes``; the stored and the flagged device."""
    if row is None:
        return {}
    return {
        "hardware_id": row.hardware_id,
        "hardware_id_kind": row.hardware_id_kind,
        "hardware_id_seen_at": row.hardware_id_seen_at,
        "observed_id": row.observed_id,
        "observed_kind": row.observed_kind,
    }


async def _identity_view(
    session: AsyncSession, printer_id: UUID, auth: AuthContext | None
) -> dict[str, Any]:
    """The hardware identity fields, for admin callers only (#231, M1).

    The serial is inventory data: every other caller gets ``null`` and no read happens.
    """
    if not _is_admin(auth):
        return {}
    return _identity_fields(await identity_repo.get(session, printer_id))


# Type alias for the session dependency
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ReadAuthDep = Annotated[AuthContext, Depends(require_read)]
RuntimeDep = Annotated[PrinterRuntime | None, Depends(get_printer_runtime)]
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


def roll_colour(roll: Any, loaded_width_mm: int | None) -> str | None:
    """The operator's colour of the loaded roll; None when unknown or for another width."""
    if roll is None or not loaded_width_mm or roll.width_mm != loaded_width_mm:
        return None
    return roll.colour  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# GET /api/v1/printers
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[PrinterRead],
    summary="List all printers",
    description=(
        "Returns every registered printer.  The ``paused`` flag is joined "
        "from ``printer_state``; it is ``false`` when no state row exists yet.  "
        "Pass ``?slug=<slug>`` to filter to a single printer by exact slug match "
        "(returns 404 when no printer with that slug exists)."
    ),
)
async def list_printers(
    request: Request,
    session: SessionDep,
    _auth: ReadAuthDep,
    slug: Annotated[str | None, Query(description="Filter by exact slug")] = None,
) -> list[PrinterRead]:
    """List all printers with their pause state, optionally filtered by slug."""
    if slug is not None:
        printer = await printers_repo.get_by_slug(session, slug)
        if printer is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error_code": "printer_not_found",
                    "error_message": f"slug={slug!r} not found",
                },
            )
        printers = [printer]
    else:
        printers = await printers_repo.list_all(session)
    # Per-printer ACL (#146): an empty allowed list means all printers.  A
    # foreign printer found by slug yields the same 404 as an unknown slug so
    # its existence is not disclosed.
    allowed = set(_auth.allowed_printer_ids) if _auth is not None else set()
    if allowed:
        printers = [p for p in printers if str(p.id) in allowed]
        if slug is not None and not printers:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error_code": "printer_not_found",
                    "error_message": f"slug={slug!r} not found",
                },
            )
    identities = (
        await identity_repo.get_many(session, [p.id for p in printers]) if _is_admin(_auth) else {}
    )
    result: list[PrinterRead] = []
    for p in printers:
        state = await printer_state_repo.get(session, p.id)
        paused, pause = pause_view(request, p.id, state.paused if state is not None else False)
        result.append(
            PrinterRead(
                id=p.id,
                name=p.name,
                slug=p.slug,
                model=p.model,
                backend=p.backend,
                connection=_connection_view(p, _auth),
                enabled=p.enabled,
                paused=paused,
                pause=pause,
                created_at=p.created_at,
                updated_at=p.updated_at,
                layout_defaults=_layout_defaults_view(p),
                **_identity_fields(identities.get(p.id)),
            )
        )
    return result


# ---------------------------------------------------------------------------
# GET /api/v1/printers/{id}
# ---------------------------------------------------------------------------


@router.get(
    "/{printer_id}",
    response_model=PrinterRead,
    summary="Get printer detail",
    description=(
        "Returns full metadata for a single printer, including the ``paused`` "
        "flag joined from ``printer_state``. Returns 404 when the printer is "
        "not registered."
    ),
)
async def get_printer(
    request: Request,
    printer_id: UUID,
    session: SessionDep,
    _auth: ReadAuthDep,
) -> PrinterRead:
    """Return full printer metadata for a single printer."""
    printer = await _get_printer_or_404(session, printer_id)
    if _auth is not None:
        check_printer_access(_auth, printer_id)
    state = await printer_state_repo.get(session, printer_id)
    paused, pause = pause_view(request, printer_id, state.paused if state is not None else False)
    return PrinterRead(
        id=printer.id,
        name=printer.name,
        model=printer.model,
        backend=printer.backend,
        connection=_connection_view(printer, _auth),
        enabled=printer.enabled,
        paused=paused,
        pause=pause,
        created_at=printer.created_at,
        updated_at=printer.updated_at,
        layout_defaults=_layout_defaults_view(printer),
        **await _identity_view(session, printer_id, _auth),
    )


# ---------------------------------------------------------------------------
# GET /api/v1/printers/{id}/status
# ---------------------------------------------------------------------------


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


async def _page_status(
    session: AsyncSession,
    printer_id: UUID,
    parsed: dict[str, Any],
    captured_at: datetime,
    age_s: int,
) -> PrinterStatus:
    """Status of an IPP page printer from the cache row written by ``IppStatusProducer``."""
    last_error = parsed.get("last_error")
    try:
        record = IppStatusRecord.model_validate(parsed)
    except ValidationError:
        return PrinterStatus(
            printer_id=printer_id,
            online=parsed.get("online"),
            kind="page",
            captured_at=captured_at,
            last_probe_age_s=age_s,
            last_error=last_error,
        )
    rows = (
        (
            await session.execute(
                select(PrinterTray)
                .where(col(PrinterTray.printer_id) == printer_id)
                .order_by(col(PrinterTray.tray_key))
            )
        )
        .scalars()
        .all()
    )
    # The printer's own order (``media-source-supported``); a configured tray it does not list
    # (``auto``) follows, in key order (the sort is stable and the rows are already by key).
    position = {t.key: i for i, t in enumerate(record.trays)}
    rows = sorted(rows, key=lambda t: position.get(t.tray_key, len(position)))
    media = {t.key: t.media for t in record.trays}
    return PrinterStatus(
        printer_id=printer_id,
        online=record.online,
        tape_loaded=None,
        error_state=record.blocking_reason,
        captured_at=captured_at,
        last_probe_age_s=age_s,
        last_error=last_error,
        kind="page",
        printer_state=record.printer_state,
        state_reasons=[ReasonRead(**r.model_dump()) for r in record.reasons],
        markers=[MarkerRead(**m.model_dump()) for m in record.markers],
        trays=[
            TrayStatusRead(
                key=t.tray_key,
                label=t.label,
                load_hint=t.load_hint,
                enabled=t.enabled,
                is_default=t.is_default,
                media=media.get(t.tray_key),
            )
            for t in rows
        ],
        jobs_ahead=record.jobs_ahead,
    )


@router.get(
    "/{printer_id}/status",
    response_model=PrinterStatus,
    summary="Return the latest cached printer status",
    description=(
        "Returns the most recent status written by the background probe worker "
        "(SNMP for tape printers, IPP for page printers; page printers add ``kind``, "
        "``printer_state``, reasons, markers, trays and ``jobs_ahead``). "
        "The response is served from ``printer_status_cache``. "
        "When no probe has completed yet ``online`` is ``null`` and ``note`` explains why. "
        "Reads the hub's cache only; never contacts the printer. "
        "Returns 404 when the printer is not registered."
    ),
    responses={404: {"model": DetailError, "description": "The printer is not registered."}},
)
async def get_printer_status(
    printer_id: UUID,
    session: SessionDep,
    _auth: ReadAuthDep,
    runtime: RuntimeDep = None,
) -> PrinterStatus:
    """Return the latest cached status for a printer; the cache only, no probe."""
    await _get_printer_or_404(session, printer_id)
    if _auth is not None:
        check_printer_access(_auth, printer_id)
    status_ = await _cached_status(session, printer_id, runtime)
    # #231: the flag is on every branch of the status (probed, stale, not polled, never probed);
    # the identity values are not part of this response.
    identity = await identity_repo.get(session, printer_id)
    status_.identity_mismatch = identity is not None and identity.mismatch_since is not None
    return status_


async def _cached_status(
    session: AsyncSession, printer_id: UUID, runtime: PrinterRuntime | None
) -> PrinterStatus:
    polled = runtime is not None and runtime.is_polled(printer_id)
    row = await cache_repo.get(session, printer_id)
    if row is None or row.captured_at is None:
        return PrinterStatus(
            printer_id=printer_id,
            online=None,
            captured_at=None,
            note=(
                "No probe yet — wait up to 30s for first probe cycle" if polled else "Not polled"
            ),
            polled=polled,
        )

    parsed = row.parsed or {}
    captured = row.captured_at
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=UTC)
    now = datetime.now(UTC)
    age_s = int((now - captured).total_seconds())

    interval_s = get_settings().sse_probe_interval_s
    backoff_s = backoff_of(parsed)
    stale = polled and is_stale(row.updated_at, now, interval_s, backoff_s)
    if not polled or stale:
        # The cached values describe a printer nobody has looked at for a while (or at all):
        # returning them next to "no tape" is the bug this guards against. ``last_error`` is one
        # of those values: it belongs to an old probe, so it is not repeated here.
        return PrinterStatus(
            printer_id=printer_id,
            online=None,
            captured_at=row.captured_at,
            last_probe_age_s=age_s,
            last_error=None,
            note=(
                "Not polled"
                if not polled
                else f"Status older than {int(stale_after_s(interval_s, backoff_s))} s"
            ),
            kind="page" if parsed.get("kind") == "page" else None,
            stale=stale,
            polled=polled,
        )

    if parsed.get("kind") == "page":
        return await _page_status(session, printer_id, parsed, row.captured_at, age_s)

    tape = read_tape_status(parsed)
    # The hub cannot see a tape through a printer it cannot reach (rows written before the
    # producer cleared it may still hold the last one).
    loaded_tape_mm = None if tape.get("online") is False else tape.get("loaded_tape_mm")
    tape_loaded = f"{loaded_tape_mm}mm" if loaded_tape_mm else None

    error_flags = tape.get("error_flags") or []
    error_state = ", ".join(error_flags) if error_flags else None
    roll = await roll_repo.get(session, printer_id)

    return PrinterStatus(
        printer_id=printer_id,
        online=tape.get("online"),
        tape_loaded=tape_loaded,
        tape_width_mm=loaded_tape_mm,
        tape_colour=roll_colour(roll, loaded_tape_mm),  # type: ignore[arg-type]
        roll_prompt=bool(
            roll is not None
            and roll.prompt_pending
            and loaded_tape_mm
            and roll.width_mm == loaded_tape_mm
        ),
        error_state=error_state,
        captured_at=row.captured_at,
        last_probe_age_s=age_s,
        last_error=tape.get("last_error"),
        polled=polled,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/printers/{id}/tape
# ---------------------------------------------------------------------------


@router.get(
    "/{printer_id}/tape",
    summary="Get the tape loaded in a printer",
    response_model=TapeRead,
    responses={
        404: {
            "model": DetailError,
            "description": (
                "No tape to report: the printer is unknown, has no cached status "
                "(``no cached status for printer ...``), is not polled (``Not polled``), "
                "its status is stale (``Status older than N s``, as in the status note), "
                "it is offline (``printer offline``: the hub cannot see a tape through a "
                "printer it cannot reach), or no tape is loaded "
                '(``no tape loaded in printer ...``). The body is ``{"detail": "<text>"}``.'
            ),
        }
    },
    description=(
        "Returns the width, display label and raw media text of the tape loaded in the "
        "printer, read from the status cache that the SNMP status producer writes. "
        "``colour`` comes from the operator's roll record and is null until one exists. "
        "Answers 404 when there is no tape to report; see the 404 response."
    ),
)
async def get_printer_tape(
    printer_id: UUID,
    session: SessionDep,
    _auth: ReadAuthDep,
    runtime: RuntimeDep = None,
) -> TapeRead:
    """Return the tape loaded in a polled, reachable tape printer."""
    await _get_printer_or_404(session, printer_id)
    if _auth is not None:
        check_printer_access(_auth, printer_id)

    cache = await cache_repo.get(session, printer_id)
    if cache is None or cache.parsed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no cached status for printer {printer_id}; call /status first",
        )

    parsed = cache.parsed
    interval_s = get_settings().sse_probe_interval_s
    backoff_s = backoff_of(parsed)
    if runtime is None or not runtime.is_polled(printer_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not polled")
    if is_stale(cache.updated_at, datetime.now(UTC), interval_s, backoff_s):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Status older than {int(stale_after_s(interval_s, backoff_s))} s",
        )
    tape = read_tape_status(parsed)
    if tape.get("online") is False:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="printer offline")
    width_mm = tape.get("loaded_tape_mm")
    if not width_mm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no tape loaded in printer {printer_id}",
        )
    return TapeRead(
        width_mm=width_mm,
        label=runtime.describe_tape_for(printer_id, width_mm).label,
        media_raw=tape.get("media_raw"),
        colour=roll_colour(await roll_repo.get(session, printer_id), width_mm),  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# GET /api/v1/printers/{id}/queue
# ---------------------------------------------------------------------------


@router.get(
    "/{printer_id}/queue",
    summary="Get the active job queue for a printer",
    description=(
        "Returns all jobs in ``queued`` or ``printing`` state for this "
        "printer, ordered by creation time.  An API key without ``admin`` scope sees "
        "only the jobs it submitted."
    ),
)
async def get_printer_queue(
    printer_id: UUID,
    session: SessionDep,
    _auth: ReadAuthDep,
) -> list[dict[str, object]]:
    """Return queued and printing jobs for a printer."""
    await _get_printer_or_404(session, printer_id)
    if _auth is not None:
        check_printer_access(_auth, printer_id)

    active_jobs = await jobs_repo.list_active(session)
    # #294: a plain API key sees its own jobs only.
    printer_jobs = [
        j for j in active_jobs if j.printer_id == printer_id and may_see(_auth, j.api_key_id)
    ]

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
# POST /api/v1/printers/{id}/pause
# ---------------------------------------------------------------------------


@router.post(
    "/{printer_id}/pause",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Pause job dispatch for a printer",
    description=(
        "Sets ``printer_state.paused = true`` and pauses the queue worker.  "
        "New jobs can still be queued but the worker will not dispatch them "
        "until the printer is resumed.  Idempotent — pausing an already-paused "
        "printer returns 204 without error."
    ),
)
async def pause_printer(
    request: Request,
    printer_id: UUID,
    session: SessionDep,
    _auth: PrintAuthDep,
) -> None:
    """Pause a printer."""
    await _get_printer_or_404(session, printer_id)
    if _auth is not None:
        check_printer_access(_auth, printer_id)
    await printer_state_repo.set_paused(session, printer_id, True)
    # Keep the queue worker in sync: the DB flag alone never stopped dispatch.
    queue = getattr(request.app.state, "print_queue", None)
    if queue is not None:
        # KeyError: printer not known to the queue (e.g. added after start)
        with contextlib.suppress(KeyError):
            await queue.pause_printer(printer_id, reason="user", source="user")


# ---------------------------------------------------------------------------
# POST /api/v1/printers/{id}/resume
# ---------------------------------------------------------------------------


@router.post(
    "/{printer_id}/resume",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Resume job dispatch for a printer",
    description=(
        "Sets ``printer_state.paused = false`` and releases the queue worker, "
        "including an automatic pause after a printer error.  Idempotent — resuming an "
        "already-active printer returns 204 without error."
    ),
)
async def resume_printer(
    request: Request,
    printer_id: UUID,
    session: SessionDep,
    _auth: PrintAuthDep,
) -> None:
    """Resume a printer."""
    await _get_printer_or_404(session, printer_id)
    if _auth is not None:
        check_printer_access(_auth, printer_id)
    await printer_state_repo.set_paused(session, printer_id, False)
    # Also release an automatically paused worker (this is how the user clears
    # the stuck state after fixing the printer).
    queue = getattr(request.app.state, "print_queue", None)
    if queue is not None:
        with contextlib.suppress(KeyError, PrinterAlreadyActiveError):
            await queue.resume_printer(printer_id)


# ---------------------------------------------------------------------------
# POST /api/v1/printers/{id}/queue/clear
# ---------------------------------------------------------------------------


async def _clear_own_queued_jobs(
    session: AsyncSession, queue: Any, printer_id: UUID, auth: AuthContext
) -> None:
    """Cancel the QUEUED jobs of ``auth``'s key on ``printer_id``; leave every other job."""
    active_jobs = await jobs_repo.list_active(session)
    for job in active_jobs:
        if (
            job.printer_id != printer_id
            or job.state != JobState.QUEUED.value
            or not may_see(auth, job.api_key_id)
        ):
            continue
        if queue is not None and queue.has_job(job.id):
            # The in-memory state decides, as for a single cancel: a job the worker already
            # took (or a page job at the printer) is left alone, like the full clear does.
            with contextlib.suppress(KeyError):  # evicted meanwhile: nothing left to cancel
                live = await queue.get(job.id)
                if live.state.value == JobState.QUEUED.value:
                    await queue.cancel(str(job.id))
            continue
        await jobs_repo.mark_cancelled(session, job.id)


@router.post(
    "/{printer_id}/queue/clear",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel all queued jobs for a printer",
    description=(
        "Bulk-cancels every job in ``queued`` state for this printer, including "
        "jobs that are waiting while the printer is paused; none of them is sent "
        "to the printer.  "
        "Jobs in ``printing`` state are intentionally **not** cancelled — "
        "a mid-print abort is unsafe over TCP/9100 because the raster data is "
        "already on the wire; a page job the IPP printer already holds is left to "
        "finish as well (cancel it with ``POST /api/v1/jobs/{id}/cancel``).  "
        "An API key without ``admin`` scope cancels only the queued jobs it submitted; "
        "the jobs of other keys and of browser or SSO users stay queued.  "
        "Returns 204 even when there are no queued jobs."
    ),
)
async def clear_printer_queue(
    request: Request,
    printer_id: UUID,
    session: SessionDep,
    _auth: PrintAuthDep,
) -> None:
    """Cancel all QUEUED (not PRINTING) jobs for a printer."""
    await _get_printer_or_404(session, printer_id)
    if _auth is not None:
        check_printer_access(_auth, printer_id)

    queue = getattr(request.app.state, "print_queue", None)
    if owner_only(_auth):
        # #294: a plain API key clears only its own queued jobs, never another key's.
        await _clear_own_queued_jobs(session, queue, printer_id, _auth)
        return

    # The queue worker gates on its in-memory job state, so cancel there first
    # (this also persists the cancellation); a DB-only update would still print.
    if queue is not None:
        # KeyError: printer not known to the queue (e.g. added after start)
        with contextlib.suppress(KeyError):
            await queue.clear_queue(printer_id)

    # Rows the queue does not track (e.g. webhook-created) are cancelled in the DB.
    # Rows it does track are authoritative: cancelled above, or already printing.
    active_jobs = await jobs_repo.list_active(session)
    queued_jobs = [
        j
        for j in active_jobs
        if j.printer_id == printer_id
        and j.state == JobState.QUEUED.value
        and not (queue is not None and queue.has_job(j.id))
    ]

    for job in queued_jobs:
        await jobs_repo.mark_cancelled(session, job.id)
