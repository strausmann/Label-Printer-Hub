# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""``GET /api/v1/jobs?order=newest`` and ``retry_of`` on retried jobs (#255, notification sources).

A retried job's payload names the job it repeats, for every kind (tape, test page, sheet page);
a retry of a retry points to its direct parent, never further back. The list can run newest
first so a client sees the latest jobs when there are more than the limit.
"""

# ruff: noqa: F811  # the ``env`` fixture is imported and used as a test argument

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.models.job import Job, JobState
from sqlalchemy import select, update
from sqlmodel import col

from tests.integration.api.test_page_job_retry import (
    _fail_cleanly,
    _job,
    _retried_detail,
    _retry,
)
from tests.integration.api.test_sheet_print_api import _body, _sheet, running
from tests.integration.api.test_test_print_api import Env, _public_url, env  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _payload(e: Env, job_id: str) -> dict[str, Any]:
    async with e.factory() as s:
        row = (await s.execute(select(Job).where(col(Job.id) == UUID(job_id)))).scalar_one()
    return dict(row.payload)


async def _fail(e: Env, job_id: str) -> None:
    async with e.factory() as s:
        await s.execute(
            update(Job).where(col(Job.id) == UUID(job_id)).values(state=JobState.FAILED.value)
        )
        await s.commit()


async def _retry_job(e: Env, job_id: str) -> str:
    async with e.client() as c:
        r = await c.post(f"/api/v1/jobs/{job_id}/retry")
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def _tape_job(e: Env) -> str:
    r = await e.post(e.tape_id)
    assert r.status_code == 202, r.text
    job_id = str(r.json()["job_id"])
    await e.done(job_id)
    await _fail(e, job_id)
    return job_id


# ---------------------------------------------------------------------------- list order


async def _seed(e: Env, count: int) -> list[UUID]:
    """``count`` finished jobs of the env's key, one every few minutes within 24 h."""
    start = datetime.now(UTC) - timedelta(hours=23)
    step = timedelta(hours=22) / count
    ids: list[UUID] = []
    async with e.factory() as s:
        for i in range(count):
            row = Job(
                printer_id=e.tape_id,
                template_key="label-v1",
                payload={"n": i},
                state=JobState.DONE.value,
                api_key_id=e.auth.api_key_id,
                created_at=start + step * i,
            )
            s.add(row)
            ids.append(row.id)
        await s.commit()
    return ids


async def _list(e: Env, query: str) -> list[dict[str, Any]]:
    async with e.client() as c:
        r = await c.get(f"/api/v1/jobs?{query}")
    assert r.status_code == 200, r.text
    return list(r.json())


async def test_list_jobs_newest_returns_the_latest_200(env: Env) -> None:
    ids = await _seed(env, 250)

    rows = await _list(env, "order=newest&limit=200")

    got = [r["id"] for r in rows]
    assert len(got) == 200
    assert got[0] == str(ids[-1])  # the newest first
    assert got == [str(i) for i in reversed(ids[50:])]
    assert not {str(i) for i in ids[:50]} & set(got)  # the oldest 50 are absent


async def test_list_jobs_default_order_unchanged(env: Env) -> None:
    ids = await _seed(env, 250)

    rows = await _list(env, "limit=200")

    assert [r["id"] for r in rows] == [str(i) for i in ids[:200]]  # oldest first, as before


async def test_list_jobs_bad_order_422(env: Env) -> None:
    async with env.client() as c:
        r = await c.get("/api/v1/jobs?order=sideways")
    assert r.status_code == 422


async def test_list_jobs_newest_keeps_the_key_ownership_restriction(env: Env) -> None:
    mine = await _seed(env, 3)
    async with env.factory() as s:
        s.add(
            Job(
                printer_id=env.tape_id,
                template_key="label-v1",
                payload={},
                state=JobState.DONE.value,
                api_key_id=uuid4(),  # another key's job, the newest of all
                created_at=datetime.now(UTC),
            )
        )
        await s.commit()
    env.auth.scope = "print"

    rows = await _list(env, "order=newest")

    assert [r["id"] for r in rows] == [str(i) for i in reversed(mine)]


# ---------------------------------------------------------------------------- retry_of


async def test_tape_retry_records_retry_of(env: Env) -> None:
    first = await _tape_job(env)

    second = await _retry_job(env, first)

    assert (await _payload(env, second))["retry_of"] == first


async def test_retry_of_retry_points_to_its_parent(env: Env) -> None:
    a = await _tape_job(env)
    b = await _retry_job(env, a)
    await env.done(b)
    await _fail(env, b)

    c = await _retry_job(env, b)

    assert (await _payload(env, c))["retry_of"] == b  # the direct parent, not a copied value
    assert (await _payload(env, c))["retry_of"] != a


async def test_retry_of_survives_rerender(env: Env) -> None:
    first = await _tape_job(env)
    printed_before = len(env.tape.printed)

    second = await _retry_job(env, first)
    await env.done(second)

    assert len(env.tape.printed) == printed_before + 1  # the retried tape job printed
    assert (await _payload(env, second))["retry_of"] == first


async def test_page_retry_records_retry_of(env: Env) -> None:
    r = await env.post(env.page_id)
    first = str(r.json()["job_id"])
    await env.done(first)

    second = await _retry_job(env, first)
    await env.done(second)

    assert (await _payload(env, second))["retry_of"] == first
    assert (await _payload(env, first)).get("retry_of") is None


async def test_sheet_page_retry_records_retry_of() -> None:
    async with running() as rig:
        code = await _sheet(used=4)
        first_id, _ = await _fail_cleanly(rig, _body(code, 3))

        resp = await _retry(rig, first_id)

        assert resp.status_code == 201, resp.text
        assert (await rig.job_payload(resp.json()["id"]))["retry_of"] == first_id
        await _retried_detail(rig, resp)
        assert (await _job(first_id)).payload.get("retry_of") is None


async def test_first_submitted_page_payload_has_no_retry_of_key(env: Env) -> None:
    r = await env.post(env.page_id)
    first = str(r.json()["job_id"])
    await env.done(first)

    assert "retry_of" not in await _payload(env, first)
