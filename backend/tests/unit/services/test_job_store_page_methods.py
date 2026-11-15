# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""JobStore additions for page jobs (both stores): set_result, mark_failed_code, cancel from
printing, and mark_done keeping the stored result."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest_asyncio
from app.models.job import Job, JobState
from app.services.job_store import JobStore, MemoryJobStore
from app.services.job_store_sqlite import SQLiteJobStore


@pytest_asyncio.fixture(params=["memory", "sqlite"])
async def store(request: Any, async_session_factory: Any) -> AsyncIterator[JobStore]:
    if request.param == "memory":
        yield MemoryJobStore()
    else:
        yield SQLiteJobStore(async_session_factory)


async def _printing(store: JobStore) -> Job:
    job = Job(printer_id=uuid4(), payload={"kind": "calibration_page"})
    await store.save_queued(job)
    assert await store.mark_printing(job.id)
    return job


async def test_set_result_replaces_result(store: JobStore) -> None:
    job = await _printing(store)
    await store.set_result(job.id, {"phase": "uploading", "started": False})
    await store.set_result(job.id, {"phase": "tracking", "ipp_job_id": 4, "started": False})
    row = await store.get(job.id)
    assert row is not None
    assert row.result == {"phase": "tracking", "ipp_job_id": 4, "started": False}
    await store.set_result(uuid4(), {"x": 1})  # unknown id: silent no-op


async def test_mark_done_keeps_result(store: JobStore) -> None:
    job = await _printing(store)
    await store.set_result(job.id, {"ipp_job_id": 2, "started": True})
    await store.mark_done(job.id)
    row = await store.get(job.id)
    assert row is not None and row.state == JobState.DONE.value
    assert row.result == {"ipp_job_id": 2, "started": True}


async def test_mark_failed_code_stores_code_message_and_detail(store: JobStore) -> None:
    job = await _printing(store)
    await store.set_result(job.id, {"started": False})
    await store.mark_failed_code(
        job.id, "ipp_rejected", "The printer refused the document.", {"ipp_status": "x"}
    )
    row = await store.get(job.id)
    assert row is not None
    assert row.state == JobState.FAILED.value
    assert row.error == "ipp_rejected: The printer refused the document."
    assert row.result == {"started": False, "error_detail": {"ipp_status": "x"}}
    assert row.finished_at is not None
    # terminal rows stay as they are
    await store.mark_failed_code(job.id, "other", "Other.", None)
    row = await store.get(job.id)
    assert row is not None and row.error.startswith("ipp_rejected")  # type: ignore[union-attr]
    await store.mark_failed_code(uuid4(), "x", "y", None)


async def test_mark_cancelled_from_printing_only_when_allowed(store: JobStore) -> None:
    job = await _printing(store)
    await store.mark_cancelled(job.id)
    assert (await store.get(job.id)).state == JobState.PRINTING.value  # type: ignore[union-attr]
    await store.mark_cancelled(job.id, allow_printing=True)
    row = await store.get(job.id)
    assert row is not None and row.state == JobState.CANCELLED.value
    assert row.finished_at is not None


async def test_mark_failed_code_with_result_replaces_result_in_the_same_write(
    store: JobStore,
) -> None:
    job = await _printing(store)
    await store.set_result(job.id, {"phase": "uploading", "started": False})
    await store.mark_failed_code(
        job.id,
        "interrupted",
        "The page may have been sent.",
        {"why": "x"},
        result={"phase": "ended", "started": True},
    )
    row = await store.get(job.id)
    assert row is not None and row.state == JobState.FAILED.value
    assert row.result == {"phase": "ended", "started": True, "error_detail": {"why": "x"}}
    await store.mark_failed_code(job.id, "other", "Other.", None, result={"phase": "later"})
    again = await store.get(job.id)
    assert again is not None and again.result == row.result  # terminal: untouched


async def test_sqlite_mark_failed_code_with_result_is_one_commit(
    async_session_factory: Any,
) -> None:
    """A crash between two commits would leave ``printing`` with ``phase=ended``."""
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    store = SQLiteJobStore(async_session_factory)
    job = await _printing(store)
    commits: list[str] = []

    def _count(_session: Any) -> None:
        commits.append("commit")

    event.listen(Session, "after_commit", _count)
    try:
        await store.mark_failed_code(
            job.id,
            "interrupted",
            "m",
            {"why": "x"},
            result={"phase": "ended", "started": True},
        )
    finally:
        event.remove(Session, "after_commit", _count)
    assert len(commits) == 1
