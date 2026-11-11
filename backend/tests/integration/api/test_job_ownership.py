"""#294: a job belongs to the API key that submitted it.

A plain API key (no ``admin`` scope) sees and acts on its own jobs only. Another key of the
same printer, and any key for a job without an owner key (browser sessions, SSO, webhooks,
recovery, rows from before 1.5.x), gets the same 404 as for a job that does not exist.
Browser sessions, SSO users and admin keys keep full access. All keys are fake test values.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import app.models  # noqa: F401
import bcrypt
import pytest
from app.config import get_settings
from app.models.api_key import ApiKey
from app.models.job import Job, JobState
from app.models.printer import Printer
from sqlalchemy import func, select

pytestmark = pytest.mark.asyncio

FAKE_TRUST_TOKEN = "fake-trust-token-294"


def _factory():
    import app.db.engine as _engine_module

    return _engine_module.async_session


async def _key(scopes: list[str], printers: list[str] | None = None) -> tuple[str, UUID]:
    plaintext = f"lh_pat_{uuid4().hex}"
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    async with _factory()() as s:
        row = ApiKey(
            name=f"owner-{uuid4().hex[:6]}",
            key_hash=hashed,
            key_prefix=plaintext[:16],
            scopes=scopes,
            allowed_printer_ids=printers or [],
            enabled=True,
            rate_limit_per_minute=6000,
        )
        s.add(row)
        await s.commit()
        return plaintext, row.id


async def _printer() -> UUID:
    async with _factory()() as s:
        slug = f"own-{uuid4().hex[:8]}"
        printer = Printer(
            name=slug,
            slug=slug,
            model="PT-P750W",
            backend="ptouch",
            connection={"host": "192.0.2.60", "port": 9100},
        )
        s.add(printer)
        await s.commit()
        await s.refresh(printer)
        return printer.id


async def _job(printer_id: UUID, owner: UUID | None, state: str) -> UUID:
    async with _factory()() as s:
        job = Job(printer_id=printer_id, payload={}, state=state, api_key_id=owner)
        s.add(job)
        await s.commit()
        await s.refresh(job)
        return job.id


def _h(plain: str) -> dict[str, str]:
    return {"X-Label-Hub-Key": plain}


@pytest.fixture
async def world(api_client_with_seed) -> dict[str, Any]:
    # Start the lifespan first: its recovery fails QUEUED rows it finds at start-up.
    assert (await api_client_with_seed.get("/healthz")).status_code == 200
    printer = await _printer()
    owner_plain, owner_id = await _key(["print"], [str(printer)])
    other_plain, other_id = await _key(["print"], [str(printer)])
    admin_plain, _ = await _key(["admin"])
    return {
        "printer": printer,
        "owner": _h(owner_plain),
        "owner_plain": owner_plain,
        "owner_id": owner_id,
        "other": _h(other_plain),
        "other_id": other_id,
        "admin": _h(admin_plain),
        "own_failed": await _job(printer, owner_id, JobState.FAILED.value),
        "own_queued": await _job(printer, owner_id, JobState.QUEUED.value),
        "foreign_failed": await _job(printer, other_id, JobState.FAILED.value),
        "foreign_queued": await _job(printer, other_id, JobState.QUEUED.value),
        "orphan_failed": await _job(printer, None, JobState.FAILED.value),
        "orphan_queued": await _job(printer, None, JobState.QUEUED.value),
    }


def _not_found(job_id: UUID) -> bytes:
    """The body of a 404 for ``job_id``: the same for a missing and for a hidden job."""
    return f'{{"detail":"job {job_id} not found"}}'.encode()


async def _jobs_on(printer: UUID) -> int:
    async with _factory()() as s:
        return int(
            await s.scalar(select(func.count()).select_from(Job).where(Job.printer_id == printer))
            or 0
        )


async def _state(job_id: UUID) -> str:
    async with _factory()() as s:
        job = await s.get(Job, job_id)
        assert job is not None
        return job.state


async def test_missing_job_body_is_the_reference(api_client_with_seed) -> None:
    """The reference the hidden-job assertions compare with: a missing id's 404 body."""
    plain, _ = await _key(["print"])
    missing = uuid4()
    resp = await api_client_with_seed.get(f"/api/v1/jobs/{missing}", headers=_h(plain))
    assert resp.status_code == 404
    assert resp.content == _not_found(missing)


async def test_the_owner_reads_cancels_and_retries_its_job(api_client_with_seed, world) -> None:
    c = api_client_with_seed
    got = await c.get(f"/api/v1/jobs/{world['own_failed']}", headers=world["owner"])
    assert got.status_code == 200, got.text
    cancelled = await c.post(f"/api/v1/jobs/{world['own_queued']}/cancel", headers=world["owner"])
    assert cancelled.status_code == 200, cancelled.text
    assert await _state(world["own_queued"]) == JobState.CANCELLED.value
    before = await _jobs_on(world["printer"])
    retried = await c.post(f"/api/v1/jobs/{world['own_failed']}/retry", headers=world["owner"])
    # Past the owner check: the clone is created (the queue may not know the test printer).
    assert retried.status_code != 404, retried.text
    assert await _jobs_on(world["printer"]) == before + 1


async def test_the_retry_clone_belongs_to_the_retrying_key(api_client_with_seed, world) -> None:
    c = api_client_with_seed
    before = await _jobs_on(world["printer"])
    await c.post(f"/api/v1/jobs/{world['own_failed']}/retry", headers=world["owner"])
    assert await _jobs_on(world["printer"]) == before + 1
    async with _factory()() as s:
        newest = (
            await s.execute(
                select(Job)
                .where(Job.printer_id == world["printer"])
                .order_by(Job.created_at.desc())  # type: ignore[attr-defined]
                .limit(1)
            )
        ).scalar_one()
    assert newest.api_key_id == world["owner_id"]


@pytest.mark.parametrize("which", ["foreign", "orphan"])
async def test_another_key_gets_the_missing_job_answer(api_client_with_seed, world, which) -> None:
    """Another key of the printer, or any key for a job without an owner key: 404, the body
    byte-identical to a job that does not exist, and nothing changes."""
    c = api_client_with_seed
    failed, queued = world[f"{which}_failed"], world[f"{which}_queued"]
    before = await _jobs_on(world["printer"])
    for method, path, job_id in (
        ("get", f"/api/v1/jobs/{failed}", failed),
        ("post", f"/api/v1/jobs/{queued}/cancel", queued),
        ("post", f"/api/v1/jobs/{failed}/retry", failed),
        ("post", f"/api/v1/jobs/{queued}/pause", queued),
        ("post", f"/api/v1/jobs/{queued}/resume", queued),
    ):
        resp = await getattr(c, method)(path, headers=world["owner"])
        assert resp.status_code == 404, (path, resp.text)
        assert resp.content == _not_found(job_id), path
    assert await _state(queued) == JobState.QUEUED.value
    assert await _jobs_on(world["printer"]) == before  # no retry clone


async def test_the_job_list_of_a_key_shows_its_own_jobs_only(api_client_with_seed, world) -> None:
    resp = await api_client_with_seed.get("/api/v1/jobs?limit=200", headers=world["owner"])
    assert resp.status_code == 200, resp.text
    ids = {j["id"] for j in resp.json()}
    assert ids == {str(world["own_failed"]), str(world["own_queued"])}
    filtered = await api_client_with_seed.get(
        f"/api/v1/jobs?printer_id={world['printer']}&state=failed", headers=world["owner"]
    )
    assert {j["id"] for j in filtered.json()} == {str(world["own_failed"])}


def _all(world: dict[str, Any]) -> set[str]:
    return {
        str(world[k])
        for k in (
            "own_failed",
            "own_queued",
            "foreign_failed",
            "foreign_queued",
            "orphan_failed",
            "orphan_queued",
        )
    }


async def test_an_admin_key_sees_and_acts_on_every_job(api_client_with_seed, world) -> None:
    c = api_client_with_seed
    listed = await c.get(f"/api/v1/jobs?printer_id={world['printer']}", headers=world["admin"])
    assert {j["id"] for j in listed.json()} == _all(world)
    for job in ("foreign_failed", "orphan_failed"):
        assert (
            await c.get(f"/api/v1/jobs/{world[job]}", headers=world["admin"])
        ).status_code == 200
    for job in ("foreign_queued", "orphan_queued"):
        resp = await c.post(f"/api/v1/jobs/{world[job]}/cancel", headers=world["admin"])
        assert resp.status_code == 200, resp.text
    resp = await c.post(f"/api/v1/jobs/{world['orphan_failed']}/retry", headers=world["admin"])
    assert resp.status_code != 404, resp.text


async def test_a_browser_session_of_a_key_keeps_full_access(api_client_with_seed, world) -> None:
    """Unchanged: a signed-in browser (even one signed in with a print key) acts on all jobs
    of its printers, as for tape runs."""
    c = api_client_with_seed
    signed = await c.post("/api/v1/auth/session", json={"key": world["owner_plain"]})
    assert signed.status_code in (200, 201, 204), signed.text
    listed = await c.get(f"/api/v1/jobs?printer_id={world['printer']}")
    assert {j["id"] for j in listed.json()} == _all(world)
    assert (await c.get(f"/api/v1/jobs/{world['foreign_failed']}")).status_code == 200
    csrf = {"X-CSRF-Token": c.cookies.get("lph_csrf") or ""}
    for job in ("foreign_queued", "orphan_queued"):
        resp = await c.post(f"/api/v1/jobs/{world[job]}/cancel", headers=csrf)
        assert resp.status_code == 200, resp.text


async def test_an_sso_user_keeps_full_access(api_client_with_seed, world, monkeypatch) -> None:
    monkeypatch.setenv("PRINTER_HUB_SSO_TRUST_TOKEN", FAKE_TRUST_TOKEN)
    get_settings.cache_clear()
    try:
        sso = {"Remote-User": "alice", "X-Pangolin-Token": FAKE_TRUST_TOKEN}
        c = api_client_with_seed
        listed = await c.get(f"/api/v1/jobs?printer_id={world['printer']}", headers=sso)
        assert listed.status_code == 200, listed.text
        assert {j["id"] for j in listed.json()} == _all(world)
        for job in ("foreign_failed", "orphan_failed"):
            assert (await c.get(f"/api/v1/jobs/{world[job]}", headers=sso)).status_code == 200
    finally:
        get_settings.cache_clear()
