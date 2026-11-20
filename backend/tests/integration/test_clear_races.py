# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The two queue-clear paths cancel only with a conditional state write (#189).

A row the worker took, or that is already printing, must never be written as ``cancelled``;
a job registered with the queue while the clear reads the database must still be cleared.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import app.repositories.jobs as jobs_repo
import httpx
import pytest
from app.api.routes.printers import router as printers_router
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_print, require_read
from app.db.session import get_session
from app.models.job import Job, JobState
from fastapi import FastAPI
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.api.test_queue_cancel_routes import _PAYLOAD, _drain_with_canary, _Env, env

__all__ = ["env"]  # the fixture is shared with the queue-cancel route tests


async def _await_state(env: _Env, job_id: UUID, expected: str) -> None:
    for _ in range(200):
        if await env.db_state(job_id) == expected:
            return
        await asyncio.sleep(0.01)
    assert await env.db_state(job_id) == expected


def _block_printer(env: _Env) -> tuple[asyncio.Event, asyncio.Event]:
    """The printer double holds every print until ``release`` is set."""
    entered = asyncio.Event()
    release = asyncio.Event()

    async def _slow(image: Image.Image, *, tape_mm: int, **options: Any) -> None:
        env.printer.prints += 1
        entered.set()
        await release.wait()

    env.printer.print_image = _slow  # type: ignore[method-assign]
    return entered, release


def _hand_over_before_the_write(
    monkeypatch: pytest.MonkeyPatch, env: _Env, job_id: UUID, entered: asyncio.Event
) -> None:
    """Between the ``has_job`` check and the DB write the worker takes the row.

    Wraps ``jobs_repo.mark_cancelled``: the row is handed to the queue and the worker commits
    ``printing`` first, then the real write runs. A handover right after ``list_active``
    would pass on the unfixed code and prove nothing.
    """
    real = jobs_repo.mark_cancelled

    async def wrapped(session: AsyncSession, jid: UUID, **kwargs: Any) -> Any:
        if jid == job_id and not entered.is_set():
            await env.queue.submit_with_id(
                job_id, env.printer.id, Image.new("1", (300, 76)), tape_mm=24
            )
            await asyncio.wait_for(entered.wait(), timeout=5)
            await _await_state(env, job_id, JobState.PRINTING.value)
        return await real(session, jid, **kwargs)

    monkeypatch.setattr(jobs_repo, "mark_cancelled", wrapped)


@pytest.mark.asyncio
async def test_admin_clear_does_not_cancel_a_row_the_worker_took(
    env: _Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release = _block_printer(env)
    job_id = await env.seed_job(enqueue=False)  # a row the queue does not track
    _hand_over_before_the_write(monkeypatch, env, job_id, entered)

    async with env.client() as c:
        r = await c.post(f"/api/v1/printers/{env.printer.id}/queue/clear")
    assert r.status_code == 204
    assert await env.db_state(job_id) == JobState.PRINTING.value

    release.set()
    await env.queue.wait_for_job(str(job_id), timeout_s=5)
    await env.wait_db_state(job_id, JobState.DONE.value)
    assert env.printer.prints == 1


@pytest.mark.asyncio
async def test_own_clear_does_not_cancel_a_row_the_worker_took(
    env: _Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    key_id = uuid4()
    entered, release = _block_printer(env)
    job = Job(printer_id=env.printer.id, payload=dict(_PAYLOAD), api_key_id=key_id)
    await env.store.save_queued(job)
    _hand_over_before_the_write(monkeypatch, env, job.id, entered)

    app = FastAPI()
    app.include_router(printers_router)
    app.state.print_queue = env.queue
    plain = AuthContext(source="api-key", scope="print", api_key_id=key_id, ip="127.0.0.1")
    for dep in (require_read, require_print):
        app.dependency_overrides[dep] = lambda _c=plain: _c

    async def _session() -> AsyncIterator[AsyncSession]:
        async with env.factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(f"/api/v1/printers/{env.printer.id}/queue/clear")
    assert r.status_code == 204
    assert await env.db_state(job.id) == JobState.PRINTING.value

    release.set()
    await env.queue.wait_for_job(str(job.id), timeout_s=5)
    await env.wait_db_state(job.id, JobState.DONE.value)
    assert env.printer.prints == 1


@pytest.mark.asyncio
async def test_job_registered_during_admin_clear_is_cleared(
    env: _Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    await env.queue.pause_printer(env.printer.id, reason="user", source="user")
    registered: list[UUID] = []
    real = jobs_repo.list_active

    async def register_meanwhile(*args: Any, **kwargs: Any) -> Any:
        rows = await real(*args, **kwargs)  # the answer predates the new job
        registered.append(await env.seed_job())
        return rows

    monkeypatch.setattr(jobs_repo, "list_active", register_meanwhile)
    async with env.client() as c:
        r = await c.post(f"/api/v1/printers/{env.printer.id}/queue/clear")
    assert r.status_code == 204

    await env.queue.resume_printer(env.printer.id)
    await _drain_with_canary(env)
    assert env.printer.prints == 1  # the canary only
    assert await env.db_state(registered[0]) == JobState.CANCELLED.value


@pytest.mark.asyncio
async def test_tape_job_printing_is_never_marked_cancelled(env: _Env) -> None:
    job = Job(printer_id=env.printer.id, payload=dict(_PAYLOAD))
    await env.store.save_queued(job)
    await env.store.mark_printing(job.id)
    async with env.factory() as s:
        assert await jobs_repo.mark_cancelled(s, job.id, states=(JobState.QUEUED.value,)) is None
    assert await env.db_state(job.id) == JobState.PRINTING.value


@pytest.mark.asyncio
async def test_own_clear_ends_a_job_handed_over_during_the_write(
    env: _Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The DB write wins, then the row reaches the queue: memory must end CANCELLED, not be
    vetoed to FAILED by the worker later."""
    key_id = uuid4()
    await env.queue.pause_printer(env.printer.id, reason="user", source="user")
    job = Job(printer_id=env.printer.id, payload=dict(_PAYLOAD), api_key_id=key_id)
    await env.store.save_queued(job)
    real = jobs_repo.mark_cancelled

    async def write_then_hand_over(session: AsyncSession, jid: UUID, **kwargs: Any) -> Any:
        result = await real(session, jid, **kwargs)
        await env.queue.submit_with_id(jid, env.printer.id, Image.new("1", (300, 76)), tape_mm=24)
        return result

    monkeypatch.setattr(jobs_repo, "mark_cancelled", write_then_hand_over)
    app = FastAPI()
    app.include_router(printers_router)
    app.state.print_queue = env.queue
    plain = AuthContext(source="api-key", scope="print", api_key_id=key_id, ip="127.0.0.1")
    for dep in (require_read, require_print):
        app.dependency_overrides[dep] = lambda _c=plain: _c

    async def _session() -> AsyncIterator[AsyncSession]:
        async with env.factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(f"/api/v1/printers/{env.printer.id}/queue/clear")
    assert r.status_code == 204
    assert (await env.queue.get(job.id)).state.value == JobState.CANCELLED.value
    assert await env.db_state(job.id) == JobState.CANCELLED.value
