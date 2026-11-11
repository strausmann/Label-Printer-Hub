"""#277: who may act on a held tape run — real API keys, no dependency overrides.

A read key gets 403 on continue / reprint / discard; a print key limited to another printer
gets 404 (the batch is invisible to it) and an empty held list; a print key for the printer
may act.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import bcrypt
import httpx
import pytest
import pytest_asyncio
from app.models.api_key import ApiKey
from app.models.job import Job as DbJob
from app.models.print_batch import PrintBatch
from app.models.printer import Printer
from app.repositories import printers as printers_repo
from app.services.job_store import MemoryJobStore
from app.services.print_queue import PrintQueue
from PIL import Image

from tests.integration.api.test_sheet_types_api import _factory, _insert_key
from tests.unit.services.test_print_queue_tape_runs import TapeRoll

pytestmark = pytest.mark.asyncio

ACTIONS = (("continue", None), ("reprint", {"from_label": 11}), ("discard", None))


async def _key_with_id(scopes: list[str], printers: list[str] | None = None) -> tuple[str, UUID]:
    """A real API key: its plaintext and its id (the owner recorded on a batch)."""
    plaintext = f"lh_pat_{uuid4().hex}"
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    async with _factory()() as s:
        key = ApiKey(
            name=f"run-owner-{uuid4().hex[:6]}",
            key_hash=hashed,
            key_prefix=plaintext[:16],
            scopes=scopes,
            allowed_printer_ids=printers or [],
            enabled=True,
            rate_limit_per_minute=6000,
        )
        s.add(key)
        await s.commit()
        return plaintext, key.id


@pytest_asyncio.fixture
async def held(api_client_with_seed: httpx.AsyncClient) -> AsyncIterator[dict[str, Any]]:
    """A stopped run (the tape ended inside group 2) on printer A; printer B exists too."""
    client = api_client_with_seed
    await client.get("/healthz")
    async with _factory()() as s:
        a = await printers_repo.create(
            s, Printer(name="Tape A", slug=f"a-{uuid4().hex[:6]}", model="PT-P750W", backend="mock")
        )
        b = await printers_repo.create(
            s, Printer(name="Tape B", slug=f"b-{uuid4().hex[:6]}", model="PT-P750W", backend="mock")
        )
        a_id, b_id = a.id, b.id
    printer = TapeRoll(15)
    printer.id = a_id
    store = MemoryJobStore()
    queue = PrintQueue([printer], store=store)
    await queue.start()
    run_id = uuid4()
    ids = [uuid4() for _ in range(25)]
    owner_plain, owner_id = await _key_with_id(["print"], [str(a_id)])
    async with _factory()() as s:
        s.add(
            PrintBatch(
                id=run_id,
                printer_id=a_id,
                job_ids=[str(j) for j in ids],
                created_by=str(owner_id),  # what POST /print/{printer}/batch records
            )
        )
        await s.commit()
    slot = queue.claim_run_slot(a_id, owner_id, per_printer=5, per_key=20)
    for i, jid in enumerate(ids):
        await store.save_queued(DbJob(id=jid, printer_id=a_id, payload={"n": i}))
    await queue.enqueue_batch(
        printer_id=a_id,
        images=[Image.new("1", (40, 20), color=1) for _ in ids],
        job_ids=ids,
        tape_mm=12,
        options={},
        run_id=run_id,
        slot=slot,
    )
    async with asyncio.timeout(5):
        while (info := queue.run_info(run_id)) is None or info.state != "stopped":
            await asyncio.sleep(0.02)
    inner = client._transport.app._app  # type: ignore[attr-defined]
    original = inner.state.print_queue
    inner.state.print_queue = queue
    try:
        yield {
            "client": client,
            "run": str(run_id),
            "a": a_id,
            "b": b_id,
            "queue": queue,
            "owner": _key(owner_plain),
        }
    finally:
        inner.state.print_queue = original
        await queue.stop(timeout_s=2.0)


def _key(plain: str) -> dict[str, str]:
    return {"X-Label-Hub-Key": plain}


async def _post(h: dict[str, Any], action: str, body: Any, headers: dict[str, str]) -> Any:
    url = f"/api/v1/batches/{h['run']}/{action}"
    return await h["client"].post(url, json=body, headers=headers)


async def test_a_read_key_may_not_act(held: dict[str, Any]) -> None:
    read = _key(await _insert_key(["read"]))
    for action, body in ACTIONS:
        resp = await _post(held, action, body, read)
        assert resp.status_code == 403, (action, resp.text)
    assert held["queue"].run_info(UUID(held["run"])).state == "stopped"


async def test_a_key_of_another_printer_sees_no_batch(held: dict[str, Any]) -> None:
    other = _key(await _insert_key(["print"], [str(held["b"])]))
    for action, body in ACTIONS:
        resp = await _post(held, action, body, other)
        assert resp.status_code == 404, (action, resp.text)
    listed = await held["client"].get("/api/v1/batches/runs/held", headers=other)
    assert listed.status_code == 200 and listed.json() == []
    assert held["queue"].run_info(UUID(held["run"])).state == "stopped"


async def test_another_print_key_of_the_printer_gets_404_and_an_empty_list(
    held: dict[str, Any],
) -> None:
    """Security review: only the key that submitted the batch acts on its run; for another
    key of the same printer the batch does not exist, and the held list does not show it."""
    other = _key(await _insert_key(["print"], [str(held["a"])]))
    for action, body in ACTIONS:
        resp = await _post(held, action, body, other)
        assert resp.status_code == 404, (action, resp.text)
        assert resp.json() == {"detail": "Batch not found"}  # the same answer as a missing one
    listed = await held["client"].get("/api/v1/batches/runs/held", headers=other)
    assert listed.status_code == 200 and listed.json() == []
    assert held["queue"].run_info(UUID(held["run"])).state == "stopped"


async def test_an_admin_key_lists_and_may_act_on_any_run(held: dict[str, Any]) -> None:
    admin = _key(await _insert_key(["admin"]))
    listed = await held["client"].get("/api/v1/batches/runs/held", headers=admin)
    assert [r["batch_id"] for r in listed.json()] == [held["run"]]
    gone = await _post(held, "discard", None, admin)
    assert gone.status_code == 204, gone.text


async def test_the_owner_may_continue_and_reprint(held: dict[str, Any]) -> None:
    resp = await _post(held, "continue", None, held["owner"])
    assert resp.status_code == 409, resp.text  # reached the run: it is stopped, not waiting
    resp = await _post(held, "reprint", {"from_label": 11}, held["owner"])
    assert resp.status_code == 200, resp.text


async def test_a_print_key_of_the_printer_lists_and_discards(held: dict[str, Any]) -> None:
    mine = held["owner"]
    listed = await held["client"].get("/api/v1/batches/runs/held", headers=mine)
    assert listed.status_code == 200
    (run,) = listed.json()
    assert (run["batch_id"], run["state"], run["stop_kind"]) == (held["run"], "stopped", "unknown")
    assert (run["reprint_from"], run["reprint_to"]) == (11, 21)

    gone = await _post(held, "discard", None, mine)
    assert gone.status_code == 204, gone.text
    assert held["queue"].run_info(UUID(held["run"])) is None
    again = await _post(held, "discard", None, mine)
    assert again.status_code == 404
