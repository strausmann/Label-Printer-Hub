# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Every print path records who printed and from where (263-79).

Real lifespan, real API keys, a mock tape printer; no dependency overrides. The recorded
``api_key_id`` is the key that owns the job (#294) and ``source_ip`` is the peer address.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import app.models  # noqa: F401
import pytest
import pytest_asyncio
from app.config import get_settings
from app.models.api_key import ApiKey
from app.models.job import Job as DbJob
from app.models.printer import Printer
from app.repositories import printers as printers_repo
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from tests.integration.api.test_sheet_types_api import _factory, _insert_key

pytestmark = pytest.mark.asyncio

PEER = "127.0.0.1"  # the peer the ASGI test transport reports
_BODY = {
    "content_type": "qr_two_lines",
    "data": {"title": "T", "primary_id": "ID-1", "qr_payload": "https://e.invalid"},
}


@pytest_asyncio.fixture
async def hub() -> AsyncIterator[dict[str, Any]]:
    from app.integrations import IntegrationRegistry, _discover_plugins  # type: ignore[attr-defined]
    from app.main import create_app

    if not IntegrationRegistry.names():
        _discover_plugins()
    get_settings.cache_clear()
    async with _factory()() as s:
        printer = await printers_repo.create(
            s, Printer(name="Tape A", slug="tape-a", model="PT-P750W", backend="mock")
        )
        printer_id = printer.id
    app = create_app()
    inner = app._app
    async with (
        inner.router.lifespan_context(inner),
        AsyncClient(transport=ASGITransport(app=inner), base_url="http://t") as c,
    ):
        yield {"client": c, "app": inner, "printer": printer_id}
    get_settings.cache_clear()


async def _key(scopes: list[str]) -> tuple[dict[str, str], UUID]:
    plaintext = await _insert_key(scopes)
    async with _factory()() as s:
        row = (
            await s.execute(select(ApiKey).where(ApiKey.key_prefix == plaintext[:16]))  # type: ignore[arg-type]
        ).scalar_one()
    return {"X-Label-Hub-Key": plaintext}, row.id


async def _rows(*job_ids: str) -> list[DbJob]:
    async with _factory()() as s:
        result = await s.execute(select(DbJob).where(DbJob.id.in_([UUID(j) for j in job_ids])))  # type: ignore[attr-defined]
        return list(result.scalars())


async def _all_rows() -> list[DbJob]:
    async with _factory()() as s:
        return list((await s.execute(select(DbJob))).scalars())


async def test_print_job_records_key_and_ip(hub: dict[str, Any]) -> None:
    headers, key_id = await _key(["print"])

    resp = await hub["client"].post("/api/v1/print", json=_BODY, headers=headers)

    assert resp.status_code == 202, resp.text
    [row] = await _rows(resp.json()["job_id"])
    assert (row.api_key_id, row.source_ip) == (key_id, PEER)


async def test_session_print_records_the_key_it_signed_in_with(hub: dict[str, Any]) -> None:
    """A browser session derived from a key carries that key's id (the owner)."""
    headers, key_id = await _key(["print"])
    async with AsyncClient(transport=ASGITransport(app=hub["app"]), base_url="http://t") as browser:
        signed = await browser.post(
            "/api/v1/auth/session", json={"key": headers["X-Label-Hub-Key"]}
        )
        assert signed.status_code == 204, signed.text
        resp = await browser.post(
            "/api/v1/print", json=_BODY, headers={"X-CSRF-Token": browser.cookies["lph_csrf"]}
        )
    assert resp.status_code == 202, resp.text
    [row] = await _rows(resp.json()["job_id"])
    assert (row.api_key_id, row.source_ip) == (key_id, PEER)


async def test_tape_test_print_records_key_and_ip(hub: dict[str, Any]) -> None:
    headers, key_id = await _key(["print"])

    resp = await hub["client"].post(
        f"/api/v1/printers/{hub['printer']}/test-print", headers=headers
    )

    assert resp.status_code == 202, resp.text
    [row] = await _rows(resp.json()["job_id"])
    assert (row.api_key_id, row.source_ip) == (key_id, PEER)


async def test_batch_sub_jobs_record_key(hub: dict[str, Any]) -> None:
    """Every row of a tape run, copies included, names the key and the address."""
    headers, key_id = await _key(["print"])
    item = {**_BODY, "options": {"copies": 2}}

    resp = await hub["client"].post(
        "/api/v1/print/tape-a/batch", json={"items": [item, _BODY]}, headers=headers
    )

    assert resp.status_code == 202, resp.text
    rows = await _all_rows()
    assert len(rows) == 3, "two copies of the first item and one of the second"
    assert {(r.api_key_id, r.source_ip) for r in rows} == {(key_id, PEER)}


async def test_retry_records_the_caller(hub: dict[str, Any]) -> None:
    """The clone of a retried job belongs to the key that retried it, with its address."""
    headers, key_id = await _key(["print"])
    first = await hub["client"].post("/api/v1/print", json=_BODY, headers=headers)
    assert first.status_code == 202, first.text
    job_id = first.json()["job_id"]
    async with asyncio.timeout(5):
        while (await _rows(job_id))[0].state not in ("done", "failed"):
            await asyncio.sleep(0.02)
    async with _factory()() as s:
        row = await s.get(DbJob, UUID(job_id))
        assert row is not None
        row.state = "failed"
        await s.commit()
    before = {r.id for r in await _all_rows()}

    retry = await hub["client"].post(f"/api/v1/jobs/{job_id}/retry", headers=headers)

    assert 200 <= retry.status_code < 300, retry.text
    [clone] = [r for r in await _all_rows() if r.id not in before]
    assert (clone.api_key_id, clone.source_ip) == (key_id, PEER)
