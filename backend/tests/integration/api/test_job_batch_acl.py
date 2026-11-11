"""Per-printer ACL on job and batch endpoints (follow-up to #146).

Foreign jobs/batches answer 404 (not 403) so their existence is not leaked.
Covers restricted and unrestricted API keys and a browser session. The job tests use admin
keys: a plain key sees only the jobs it submitted (#294, test_job_ownership.py), and the
printer ACL applies to admin keys as well.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import app.models  # noqa: F401
import bcrypt
import pytest
from app.models.api_key import ApiKey
from app.models.job import Job, JobState
from app.models.print_batch import PrintBatch
from app.models.printer import Printer


def _factory():
    import app.db.engine as _engine_module

    return _engine_module.async_session


async def _insert_key(scopes: list[str], allowed: list[str]) -> str:
    plaintext = f"lh_pat_{uuid4().hex}"
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    async with _factory()() as s:
        s.add(
            ApiKey(
                name=f"job-acl-{uuid4().hex[:6]}",
                key_hash=hashed,
                key_prefix=plaintext[:16],
                scopes=scopes,
                allowed_printer_ids=allowed,
                enabled=True,
                rate_limit_per_minute=600,
            )
        )
        await s.commit()
    return plaintext


async def _printer_with_job(state: str = JobState.FAILED.value) -> tuple[UUID, UUID, UUID]:
    """Return (printer_id, job_id, batch_id) for a fresh printer."""
    async with _factory()() as s:
        slug = f"job-acl-{uuid4().hex[:8]}"
        printer = Printer(
            name=slug,
            slug=slug,
            model="PT-P750W",
            backend="ptouch",
            connection={"host": "192.0.2.50", "port": 9100},
        )
        s.add(printer)
        await s.commit()
        await s.refresh(printer)
        job = Job(printer_id=printer.id, template_key=None, payload={}, state=state)
        s.add(job)
        await s.commit()
        await s.refresh(job)
        batch = PrintBatch(printer_id=printer.id, job_ids=[str(job.id)], created_by="test")
        s.add(batch)
        await s.commit()
        await s.refresh(batch)
        return printer.id, job.id, batch.id


@pytest.fixture
async def world():
    a = await _printer_with_job()
    b = await _printer_with_job()
    return a, b


def _job_ids(resp) -> set[str]:
    return {j["id"] for j in resp.json()}


@pytest.mark.asyncio
async def test_job_list_filtered_to_allowed_printers(api_client_with_seed, world):
    (pa, ja, _), (pb, jb, _) = world
    key = await _insert_key(["admin"], [str(pa)])
    h = {"X-Label-Hub-Key": key}
    resp = await api_client_with_seed.get("/api/v1/jobs?limit=200", headers=h)
    assert resp.status_code == 200, resp.text
    ids = _job_ids(resp)
    assert str(ja) in ids and str(jb) not in ids
    foreign = await api_client_with_seed.get(f"/api/v1/jobs?printer_id={pb}", headers=h)
    assert foreign.status_code == 200 and foreign.json() == []


@pytest.mark.asyncio
async def test_job_list_unrestricted_sees_all(api_client_with_seed, world):
    (_, ja, _), (_, jb, _) = world
    key = await _insert_key(["admin"], [])
    resp = await api_client_with_seed.get(
        "/api/v1/jobs?limit=200", headers={"X-Label-Hub-Key": key}
    )
    assert {str(ja), str(jb)} <= _job_ids(resp)


@pytest.mark.asyncio
async def test_job_detail_and_mutations_of_foreign_job_404(api_client_with_seed, world):
    (pa, ja, _), (_, jb, _) = world
    key = await _insert_key(["admin"], [str(pa)])
    h = {"X-Label-Hub-Key": key}
    own = await api_client_with_seed.get(f"/api/v1/jobs/{ja}", headers=h)
    assert own.status_code == 200, own.text
    missing = await api_client_with_seed.get(f"/api/v1/jobs/{uuid4()}", headers=h)
    resp = await api_client_with_seed.get(f"/api/v1/jobs/{jb}", headers=h)
    assert resp.status_code == 404, resp.text
    for action in ("cancel", "pause", "resume", "retry"):
        r = await api_client_with_seed.post(f"/api/v1/jobs/{jb}/{action}", headers=h)
        assert r.status_code == 404, f"{action}: {r.status_code} {r.text}"
    # the foreign job must be untouched by retry (no clone created)
    async with _factory()() as s:
        from sqlalchemy import func, select

        count = await s.scalar(
            select(func.count()).select_from(Job).where(Job.printer_id == _pb(world))
        )
    assert count == 1
    assert missing.status_code == 404


def _pb(world) -> UUID:
    return world[1][0]


@pytest.mark.asyncio
async def test_batch_of_foreign_printer_404(api_client_with_seed, world):
    (pa, _, ba), (_, _, bb) = world
    key = await _insert_key(["read"], [str(pa)])
    h = {"X-Label-Hub-Key": key}
    assert (await api_client_with_seed.get(f"/api/v1/batches/{ba}", headers=h)).status_code == 200
    assert (await api_client_with_seed.get(f"/api/v1/batches/{bb}", headers=h)).status_code == 404
    unrestricted = await _insert_key(["read"], [])
    r = await api_client_with_seed.get(
        f"/api/v1/batches/{bb}", headers={"X-Label-Hub-Key": unrestricted}
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_session_job_and_batch_acl(api_client_with_seed, world):
    (pa, ja, ba), (_, jb, bb) = world
    key = await _insert_key(["print"], [str(pa)])
    signed = await api_client_with_seed.post("/api/v1/auth/session", json={"key": key})
    assert signed.status_code in (200, 201, 204), signed.text
    jobs = await api_client_with_seed.get("/api/v1/jobs?limit=200")
    assert str(ja) in _job_ids(jobs) and str(jb) not in _job_ids(jobs)
    assert (await api_client_with_seed.get(f"/api/v1/jobs/{jb}")).status_code == 404
    assert (await api_client_with_seed.get(f"/api/v1/jobs/{ja}")).status_code == 200
    assert (await api_client_with_seed.get(f"/api/v1/batches/{bb}")).status_code == 404
    assert (await api_client_with_seed.get(f"/api/v1/batches/{ba}")).status_code == 200
    csrf = {"X-CSRF-Token": api_client_with_seed.cookies.get("lph_csrf")}
    r = await api_client_with_seed.post(f"/api/v1/jobs/{jb}/retry", headers=csrf)
    assert r.status_code == 404
