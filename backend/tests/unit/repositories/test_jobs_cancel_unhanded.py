# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""``cancel_queued_unhanded``: the guarded cancel of a row the queue does not hold (review I-1)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from app.models.job import Job, JobState
from app.repositories import jobs as jobs_repo


async def _row(db_session: Any, payload: dict[str, Any], state: str = "queued") -> Job:
    job = Job(printer_id=uuid4(), template_key=None, payload=payload, state=state)
    db_session.add(job)
    await db_session.commit()
    return job


@pytest.mark.parametrize(
    ("payload", "state", "cancelled"),
    [
        ({"content_type": "qr_only", "rendered_tape_mm": 24}, "queued", True),  # a plain row
        ({"deferred": True, "label_data": {}}, "queued", True),  # deferred, not completed yet
        ({"deferred": True, "deferred_kind": "sheet_page", "label_data": {}}, "queued", True),
        ({"deferred": True, "rendered_tape_mm": 24}, "queued", False),  # tape payload completed
        ({"kind": "sheet_page", "detail": {}}, "queued", False),  # page payload: the queue's
        ({"deferred": True, "label_data": {}}, "printing", False),
        ({"deferred": True, "label_data": {}}, "cancelled", False),
    ],
)
async def test_only_a_row_the_queue_cannot_hold_is_cancelled(
    db_session: Any, payload: dict[str, Any], state: str, cancelled: bool
) -> None:
    job = await _row(db_session, payload, state)
    result = await jobs_repo.cancel_queued_unhanded(db_session, job.id)
    stored = await db_session.get(Job, job.id, populate_existing=True)
    if cancelled:
        assert result is not None and result.state == JobState.CANCELLED.value
        assert stored.state == JobState.CANCELLED.value and stored.finished_at is not None
    else:
        assert result is None
        assert stored.state == state
