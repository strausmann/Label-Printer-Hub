# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""GET /api/v1/batches/{id}: only jobs that exist are listed (P7-1, #215).

A batch row can keep an id whose ``jobs`` row was never written (the page was refused after the
batch was created and the settle write failed) or was evicted later. The read lists the jobs
that exist and counts only those.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.models.print_batch import PrintBatch
from app.models.printer import Printer
from app.repositories import jobs as jobs_repo
from app.repositories import printers as printers_repo

from tests.integration.api.test_sheet_types_api import _factory, _insert_key

pytestmark = pytest.mark.asyncio


async def test_batch_read_omits_jobs_without_a_row(api_client_with_seed) -> None:
    client = api_client_with_seed
    await client.get("/healthz")
    reader = {"X-Label-Hub-Key": await _insert_key(["admin"])}
    ghost = uuid4()
    async with _factory()() as s:
        printer = await printers_repo.create(
            s, Printer(name="P", slug=f"p-{uuid4().hex[:6]}", model="m", backend="mock")
        )
        job = await jobs_repo.create_queued(s, printer_id=printer.id, template_key="t", payload={})
        batch = PrintBatch(
            printer_id=printer.id, job_ids=[str(ghost), str(job.id)], created_by="someone"
        )
        s.add(batch)
        await s.commit()
        batch_id, job_id = batch.id, job.id

    resp = await client.get(f"/api/v1/batches/{batch_id}", headers=reader)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [j["id"] for j in body["jobs"]] == [str(job_id)]
    assert body["summary"]["total"] == 1
    assert str(ghost) not in resp.text
