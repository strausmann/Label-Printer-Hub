"""The roll record of a printer: read it, and give its tape colour (#229).

The printer reports no tape colour over the network. The hub detects a roll change from the
probe (``RollTracker``) and asks the operator; ``PUT`` is the answer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import AuthContext, check_printer_access
from app.auth.scope_deps import require_print, require_read
from app.db.session import get_session
from app.repositories import printer_roll as roll_repo
from app.repositories import printers as printers_repo
from app.schemas.printer import RollColourUpdate, RollRead
from app.schemas.problem import ProblemDetail
from app.services.event_bus import EventBus
from app.services.roll_tracker import publish_roll_event

router = APIRouter(prefix="/api/v1/printers", tags=["printers"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ReadAuthDep = Annotated[AuthContext, Depends(require_read)]
PrintAuthDep = Annotated[AuthContext, Depends(require_print)]


def _conflict(type_: str, title: str, detail: str) -> HTTPException:
    problem = ProblemDetail(type=type_, title=title, status=status.HTTP_409_CONFLICT, detail=detail)
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail=problem.model_dump(exclude_none=True)
    )


async def _require_printer(session: AsyncSession, printer_id: UUID) -> None:
    if await printers_repo.get(session, printer_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"printer {printer_id} not found")


def _view(roll: object | None) -> RollRead:
    if roll is None:
        return RollRead()
    return RollRead.model_validate(roll, from_attributes=True)


@router.get(
    "/{printer_id}/roll",
    response_model=RollRead,
    summary="Get the roll recorded for a printer",
    description=(
        "Returns the roll identity last seen by the status probe, the tape colour the operator "
        "gave it and whether the operator is still to be asked. All fields are empty until the "
        "first probe. Answers 404 for an unknown printer."
    ),
)
async def get_roll(printer_id: UUID, session: SessionDep, _auth: ReadAuthDep) -> RollRead:
    """Return the stored roll record."""
    await _require_printer(session, printer_id)
    if _auth is not None:
        check_printer_access(_auth, printer_id)
    return _view(await roll_repo.get(session, printer_id))


@router.put(
    "/{printer_id}/roll",
    response_model=RollRead,
    summary="Set the tape colour of the loaded roll",
    responses={
        409: {
            "description": (
                "``no-roll-loaded``: no tape is recorded for the printer. ``roll-changed``: "
                "the sent ``width_mm`` differs from the stored roll, so the roll changed "
                "after the operator looked; ask again."
            )
        }
    },
    description=(
        "Records the tape colour of the roll in the printer and ends the prompt. ``colour`` "
        "null is both skip and clear. Send the ``width_mm`` the operator saw: a roll change "
        "detected meanwhile answers 409 ``roll-changed`` instead of colouring the new roll."
    ),
)
async def put_roll(
    printer_id: UUID,
    body: RollColourUpdate,
    request: Request,
    session: SessionDep,
    _auth: PrintAuthDep,
) -> RollRead:
    """Set (or clear) the colour of the current roll."""
    await _require_printer(session, printer_id)
    if _auth is not None:
        check_printer_access(_auth, printer_id)
    roll = await roll_repo.get(session, printer_id)
    if roll is None or roll.width_mm is None:
        raise _conflict(
            "no-roll-loaded", "No roll is loaded", f"Printer {printer_id} has no tape recorded"
        )
    expected = roll.width_mm
    if body.width_mm is not None and body.width_mm != expected:
        raise _changed(printer_id, body.width_mm, expected)
    if body.media_raw is not None and body.media_raw != roll.media_raw:
        raise _conflict(
            "roll-changed",
            "The roll changed",
            f"Printer {printer_id} now holds a different roll of {expected} mm",
        )
    stored = await roll_repo.set_colour(
        session,
        printer_id,
        colour=body.colour,
        width_mm=expected,
        media_raw=body.media_raw,
        now=datetime.now(UTC),
    )
    session.expire_all()
    if not stored:
        # The roll changed between the read above and the write.
        current = await roll_repo.get(session, printer_id)
        if current is None or current.width_mm is None:
            raise _conflict(
                "no-roll-loaded", "No roll is loaded", f"Printer {printer_id} has no tape"
            )
        raise _changed(printer_id, expected, current.width_mm)
    roll = await roll_repo.get(session, printer_id)
    bus: EventBus | None = getattr(request.app.state, "event_bus", None)
    publish_roll_event(
        bus,
        printer_id,
        width_mm=expected,
        media_raw=roll.media_raw if roll else None,
        prompt_pending=False,
    )
    return _view(roll)


def _changed(printer_id: UUID, sent: int, stored: int) -> HTTPException:
    return _conflict(
        "roll-changed",
        "The roll changed",
        f"Printer {printer_id} now holds a {stored} mm roll, not the {sent} mm one",
    )
