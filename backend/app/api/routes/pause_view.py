# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The pause state of a printer as a route shows it.

Shared by the printer routes and the test-print route, so neither imports the other.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Request

from app.schemas.printer import PauseRead


def pause_view(
    request: Request, printer_id: UUID, db_paused: bool
) -> tuple[bool, PauseRead | None]:
    """Combine the DB flag with the queue worker state (automatic pauses)."""
    queue = getattr(request.app.state, "print_queue", None)
    if queue is None:
        return db_paused, None
    info = queue.pause_info(printer_id)
    pause = (
        PauseRead(source=info.source, reason_code=info.reason_code, since=info.since)
        if info is not None
        else None
    )
    return db_paused or queue.is_paused(printer_id), pause
