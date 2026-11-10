"""#277 over HTTP: the run of a tape batch, continue, and reprint from label N.

The batch row is real; the app's print queue is replaced by one whose printer is the
``TapeRoll`` double (its tape runs out after k labels), so no hardware or seeding is needed.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from app.models.job import Job as DbJob
from app.models.print_batch import PrintBatch
from app.models.printer import Printer
from app.repositories import printers as printers_repo
from app.services.job_store import MemoryJobStore
from app.services.print_queue import PrintQueue
from httpx import AsyncClient
from PIL import Image

from tests.unit.services.test_print_queue_tape_runs import TapeRoll

pytestmark = pytest.mark.asyncio


@dataclass
class Rig:
    client: AsyncClient
    queue: PrintQueue
    printer: TapeRoll
    db: Any
    store: MemoryJobStore

    async def batch(self, n: int) -> str:
        run_id = uuid4()
        ids = [uuid4() for _ in range(n)]
        self.db.add(
            PrintBatch(
                id=run_id,
                printer_id=self.printer.id,
                job_ids=[str(j) for j in ids],
                created_by="t",
            )
        )
        await self.db.commit()
        for i, jid in enumerate(ids):
            await self.store.save_queued(
                DbJob(id=jid, printer_id=self.printer.id, payload={"label_data": {"n": i}})
            )
        await self.queue.enqueue_batch(
            printer_id=self.printer.id,
            images=[Image.new("1", (40, 20), color=1) for _ in ids],
            job_ids=ids,
            tape_mm=12,
            options={},
            run_id=run_id,
        )
        return str(run_id)

    async def until_run(
        self, batch_id: str, cond: Callable[[dict[str, Any] | None], bool]
    ) -> dict[str, Any] | None:
        async with asyncio.timeout(5):
            while True:
                r = await self.client.get(f"/api/v1/batches/{batch_id}")
                assert r.status_code == 200, r.text
                run = r.json()["run"]
                if cond(run):
                    return run  # type: ignore[no-any-return]
                await asyncio.sleep(0.02)


@pytest_asyncio.fixture
async def rig(client: AsyncClient, app_with_fake_auth: Any, db_session: Any) -> AsyncIterator[Rig]:
    await client.get("/healthz")  # the lifespan runs
    row = await printers_repo.create(
        db_session, Printer(name="Tape", slug="tape-run", model="PT-P750W", backend="mock")
    )
    printer = TapeRoll()
    printer.id = row.id
    store = MemoryJobStore()
    queue = PrintQueue([printer], store=store)
    await queue.start()
    inner = app_with_fake_auth._app
    original = inner.state.print_queue
    inner.state.print_queue = queue
    try:
        yield Rig(client=client, queue=queue, printer=printer, db=db_session, store=store)
    finally:
        inner.state.print_queue = original
        await queue.stop(timeout_s=2.0)


def _code(resp: Any) -> str:
    return str(resp.json()["detail"]["error_code"])


async def test_51_labels_wait_for_continue(rig: Rig) -> None:
    batch_id = await rig.batch(51)

    run = await rig.until_run(
        batch_id, lambda r: r is not None and r["state"] == "awaiting_confirmation"
    )
    assert run is not None and (run["current_sub_job"], run["sub_jobs"], run["sub_job_size"]) == (
        2,
        2,
        50,
    )
    assert len(run["job_ids"]) == 51
    assert rig.printer.calls == [10] * 5

    refused = await rig.client.post(f"/api/v1/batches/{batch_id}/reprint", json={"from_label": 1})
    assert refused.status_code == 409 and _code(refused) == "run_not_stopped"

    go = await rig.client.post(f"/api/v1/batches/{batch_id}/continue")
    assert go.status_code == 200, go.text
    await rig.until_run(batch_id, lambda r: r is None)
    assert rig.printer.calls == [10] * 5 + [1]

    done = await rig.client.post(f"/api/v1/batches/{batch_id}/continue")
    assert done.status_code == 404 and _code(done) == "run_not_found"


async def test_a_tape_end_stops_the_run_and_a_reprint_finishes_it(rig: Rig) -> None:
    rig.printer.k = 15
    batch_id = await rig.batch(25)

    run = await rig.until_run(batch_id, lambda r: r is not None and r["state"] == "stopped")
    assert run is not None
    assert (run["unknown_from"], run["unknown_to"], run["stop_code"]) == (11, 20, "tape_empty")

    wait = await rig.client.post(f"/api/v1/batches/{batch_id}/continue")
    assert wait.status_code == 409 and _code(wait) == "run_not_awaiting_confirmation"
    outside = await rig.client.post(f"/api/v1/batches/{batch_id}/reprint", json={"from_label": 22})
    assert outside.status_code == 422 and _code(outside) == "label_out_of_range"

    rig.printer.k = None  # a new tape
    again = await rig.client.post(f"/api/v1/batches/{batch_id}/reprint", json={"from_label": 15})
    assert again.status_code == 200, again.text
    out = again.json()
    assert len(out["new_job_ids"]) == 6 + 5  # 15..20 of the group, 21..25 not started
    assert len(out["confirmed_job_ids"]) == 4  # 11..14 printed, the user says
    await rig.until_run(batch_id, lambda r: r is None)
    for job_id in out["new_job_ids"]:
        assert (await rig.queue.get(UUID(job_id))).state.value == "completed"


async def test_a_batch_without_a_run(rig: Rig) -> None:
    missing = await rig.client.post(f"/api/v1/batches/{uuid4()}/continue")
    assert missing.status_code == 404
    batch_id = await rig.batch(3)
    await rig.until_run(batch_id, lambda r: r is None)
    gone = await rig.client.post(f"/api/v1/batches/{batch_id}/reprint", json={"from_label": 1})
    assert gone.status_code == 404 and _code(gone) == "run_not_found"
