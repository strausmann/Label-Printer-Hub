"""Integration tests for auth dependency wiring on all routes — Phase 7c Step 4.

Tests that each category of endpoint:
1. Returns 401 without any auth
2. Returns 200/204 with a valid auth header of the correct scope

Phase 1k.1a (Task 25): Removed TemplateLoader and /api/templates tests.
Templates are deleted in Phase 1k.1a.

2026-08-14 security audit: added coverage for GET /api/v1/printers/{id} and
POST /api/v1/jobs/{id}/retry, which shipped with NO auth dependency at all
while their sibling endpoints in the same router file all required one
(see tests/unit/api/test_route_auth_coverage_guardrail.py for the
structural guardrail that now catches this class of gap for every route,
not just these two).
"""

from __future__ import annotations

import app.models  # noqa: F401
import bcrypt
import pytest
from app.models.api_key import ApiKey
from sqlalchemy import select


async def _make_print_key(factory):
    """Insert an api-key with print scope and return (plaintext, ApiKey)."""
    plaintext = "lh_pat_print_integ_wiring_test_step4_001"
    prefix = plaintext[:16]
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    async with factory() as s:
        key = ApiKey(
            name="wiring-test-print",
            key_hash=hashed,
            key_prefix=prefix,
            scopes=["print"],
            allowed_printer_ids=[],
            enabled=True,
        )
        s.add(key)
        await s.commit()
    return plaintext


async def _make_read_key(factory):
    plaintext = "lh_pat_read_integ_wiring_test_step4_002"
    prefix = plaintext[:16]
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    async with factory() as s:
        key = ApiKey(
            name="wiring-test-read",
            key_hash=hashed,
            key_prefix=prefix,
            scopes=["read"],
            allowed_printer_ids=[],
            enabled=True,
        )
        s.add(key)
        await s.commit()
    return plaintext


async def _make_admin_key(factory):
    plaintext = "lh_pat_admin_integ_wiring_test_step4_003"
    prefix = plaintext[:16]
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    async with factory() as s:
        key = ApiKey(
            name="wiring-test-admin",
            key_hash=hashed,
            key_prefix=prefix,
            scopes=["admin"],
            allowed_printer_ids=[],
            enabled=True,
        )
        s.add(key)
        await s.commit()
    return plaintext


@pytest.mark.asyncio
async def test_get_printers_without_auth_returns_401(api_client_with_seed):
    resp = await api_client_with_seed.get("/api/v1/printers")
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


@pytest.mark.asyncio
async def test_get_printers_with_read_key_returns_200(api_client_with_seed):
    import app.db.engine as _engine_module

    factory = _engine_module.async_session
    read_key = await _make_read_key(factory)

    resp = await api_client_with_seed.get(
        "/api/v1/printers",
        headers={"X-Label-Hub-Key": read_key},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"


@pytest.mark.asyncio
async def test_get_jobs_without_auth_returns_401(api_client_with_seed):
    resp = await api_client_with_seed.get("/api/v1/jobs")
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


@pytest.mark.asyncio
async def test_readiness_without_auth_returns_401(api_client_with_seed):
    """Readiness endpoint requires read scope."""
    resp = await api_client_with_seed.get("/readiness")
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


@pytest.mark.asyncio
async def test_healthz_is_public_no_auth(api_client_with_seed):
    """healthz endpoint is always publicly accessible (no auth required)."""
    resp = await api_client_with_seed.get("/healthz")
    assert resp.status_code == 200, f"healthz should be public: {resp.status_code}"


@pytest.mark.asyncio
async def test_pangolin_sso_header_grants_read(api_client_with_seed, monkeypatch):
    """Legacy Pangolin-SSO header (X-Pangolin-User) grants read access — only with
    the D10 opt-in PRINTER_HUB_TRUST_LEGACY_PANGOLIN_USER (default off)."""
    from app.config import get_settings

    monkeypatch.setenv("PRINTER_HUB_TRUST_LEGACY_PANGOLIN_USER", "true")
    get_settings.cache_clear()
    resp = await api_client_with_seed.get(
        "/api/v1/printers",
        headers={"X-Pangolin-User": "testuser@example.com"},
    )
    assert resp.status_code == 200, f"SSO should grant read: {resp.status_code}"


# ---------------------------------------------------------------------------
# 2026-08-14 security audit regressions:
# GET /api/v1/printers/{id} and POST /api/v1/jobs/{id}/retry had NO auth
# dependency at all — any caller that could reach the backend got full
# printer connection metadata / could trigger a real reprint with zero
# credentials. See app/api/routes/printers.py::get_printer and
# app/api/routes/jobs.py::retry_job.
# ---------------------------------------------------------------------------


async def _seed_printer(factory):
    from app.models.printer import Printer

    async with factory() as s:
        printer = Printer(
            name="audit-seed-printer",
            slug="audit-seed-printer",
            model="PT-P750W",
            backend="ptouch",
            connection={"host": "192.0.2.10", "port": 9100},
        )
        s.add(printer)
        await s.commit()
        await s.refresh(printer)
        return printer


async def _seed_failed_job(factory, printer_id, api_key_id=None):
    from app.models.job import Job, JobState

    async with factory() as s:
        job = Job(
            printer_id=printer_id,
            api_key_id=api_key_id,
            template_key="audit-seed-template",
            state=JobState.FAILED.value,
            # Renderable like a job created by POST /api/v1/print: retry re-renders it.
            payload={
                "label_data": {
                    "title": "audit",
                    "primary_id": "A-001",
                    "qr_payload": "https://example.com",
                    "source_app": "manual",
                    "secondary": [],
                    "items": [],
                },
                "content_type": "qr_two_lines",
                "rendered_tape_mm": 24,
                "tape_mm": 24,
                "options": {},
            },
        )
        s.add(job)
        await s.commit()
        await s.refresh(job)
        return job


@pytest.mark.asyncio
async def test_get_printer_detail_without_auth_returns_401(api_client_with_seed):
    """GET /api/v1/printers/{id} must reject unauthenticated requests.

    Regression test: this endpoint previously had no auth dependency at
    all, unlike GET /api/v1/printers (list) and every other single-printer
    endpoint (status/tape/queue/pause/resume) in the same file.
    """
    import app.db.engine as _engine_module

    printer = await _seed_printer(_engine_module.async_session)

    resp = await api_client_with_seed.get(f"/api/v1/printers/{printer.id}")
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"


@pytest.mark.asyncio
async def test_get_printer_detail_with_read_key_returns_200(api_client_with_seed):
    """GET /api/v1/printers/{id} succeeds for a caller with a valid read-scope key."""
    import app.db.engine as _engine_module

    factory = _engine_module.async_session
    printer = await _seed_printer(factory)
    read_key = await _make_read_key(factory)

    resp = await api_client_with_seed.get(
        f"/api/v1/printers/{printer.id}",
        headers={"X-Label-Hub-Key": read_key},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    assert resp.json()["id"] == str(printer.id)


@pytest.mark.asyncio
async def test_retry_job_without_auth_returns_401(api_client_with_seed):
    """POST /api/v1/jobs/{id}/retry must reject unauthenticated requests.

    Regression test: this endpoint previously had no auth dependency at
    all, unlike list_jobs/get_job (read scope) and cancel_job (print scope)
    in the same file — despite retry_job creating a new QUEUED job that the
    worker actually dispatches to the physical printer.
    """
    import app.db.engine as _engine_module

    factory = _engine_module.async_session
    printer = await _seed_printer(factory)
    job = await _seed_failed_job(factory, printer.id)

    resp = await api_client_with_seed.post(f"/api/v1/jobs/{job.id}/retry")
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"


@pytest.mark.asyncio
async def test_retry_job_with_print_key_returns_201(api_client_with_seed):
    """POST /api/v1/jobs/{id}/retry succeeds for a caller with a valid print-scope key."""
    import app.db.engine as _engine_module

    factory = _engine_module.async_session
    printer = await _seed_printer(factory)
    print_key = await _make_print_key(factory)
    async with factory() as s:
        key_row = (
            await s.execute(select(ApiKey).where(ApiKey.key_prefix == print_key[:16]))
        ).scalar_one()
    # #294: a plain key retries only its own job.
    job = await _seed_failed_job(factory, printer.id, api_key_id=key_row.id)

    resp = await api_client_with_seed.post(
        f"/api/v1/jobs/{job.id}/retry",
        headers={"X-Label-Hub-Key": print_key},
    )
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["id"] != str(job.id)
    assert body["state"] == "queued"
