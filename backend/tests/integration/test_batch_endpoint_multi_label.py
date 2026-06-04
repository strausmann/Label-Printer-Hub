"""Phase 1k.2 End-to-End: POST /batch → BatchJob path → atomic completion.

Verifies the full flow:
  HTTP POST → batch_dispatch → submit_batch_job → enqueue_batch
           → worker → backend.print_images → atomic job state updates.

CRITICAL assertions:
- 4-item batch calls print_images() ONCE (not 4x print_image)
- All 4 job_ids reach state='done' on success
- On failure: all 4 job_ids reach state='failed' with shared 'batch print failed' msg
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_admin, require_print, require_read
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Fixtures — follow test_batch_endpoint_happy.py pattern
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def ml_batch_client():
    """AsyncClient mit gefakter Auth + propagierter temp-DB-Engine.

    Yields (client, inner_app) — identisches Muster wie batch_client in
    test_batch_endpoint_happy.py.  inner_app.state.backend_router ist nach
    dem ersten Request vollständig initialisiert.
    """
    import app.db.engine as _eng
    import app.db.session as _sess
    from app.integrations import (  # type: ignore[attr-defined]
        IntegrationRegistry,
        _discover_plugins,
    )
    from app.main import create_app

    # Propagate the monkeypatched engine into session.py's name binding
    _sess.async_session = _eng.async_session

    if not IntegrationRegistry.names():
        _discover_plugins()

    fake = AuthContext(source="api-key", scope="admin", api_key_id=uuid4(), ip="127.0.0.1")
    app = create_app()
    inner = app._app
    for dep in (require_read, require_print, require_admin):
        inner.dependency_overrides[dep] = lambda _c=fake: _c

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        # Touch the app once so lifespan runs and state is populated
        await c.get("/healthz")
        yield c, inner


def _four_item_body(template_id: str = "hangar-furniture-24mm") -> dict:
    """Build a 4-item batch request body using the given template."""
    return {
        "items": [
            {
                "template_id": template_id,
                "data": {
                    "primary_id": f"ML-{i:04d}",
                    "title": f"Multi-Label Test {i}",
                    "qr_payload": f"https://hangar.test/ml/{i}",
                },
            }
            for i in range(4)
        ]
    }


async def _poll_job_state(
    client: AsyncClient,
    job_id: str,
    *,
    target: str,
    timeout_s: float = 5.0,
    poll_interval: float = 0.05,
) -> dict:
    """Poll GET /api/jobs/{id} until state reaches target (or timeout)."""
    deadline = asyncio.get_event_loop().time() + timeout_s
    last: dict = {}
    while asyncio.get_event_loop().time() < deadline:
        r = await client.get(f"/api/jobs/{job_id}")
        assert r.status_code == 200, f"GET /api/jobs/{job_id} → {r.status_code}: {r.text}"
        last = r.json()
        if last["state"] == target:
            return last
        # Exit early if the job reached a terminal state that is NOT the target
        if last["state"] in ("done", "failed", "cancelled"):
            return last
        await asyncio.sleep(poll_interval)
    return last


# ---------------------------------------------------------------------------
# Test 1: 4-item batch → print_images called ONCE, all jobs → done
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_batch_4_items_calls_print_images_once(ml_batch_client):
    """4-item batch must call print_images() ONCE (not 4x print_image).

    The MockPrinterBackend's real print_images delegates to
    default_print_images_loop which calls print_image per image.  We patch
    print_images with an AsyncMock so we can assert the call count and that
    all images were passed in a single call.
    """
    client, inner_app = ml_batch_client
    printer_slug = inner_app.state.backend_router.slugs()[0]
    mock_backend = inner_app.state.backend_router.get(printer_slug)
    assert mock_backend is not None, f"No backend for slug {printer_slug!r}"

    print_images_mock = AsyncMock(return_value=None)
    with patch.object(mock_backend, "print_images", print_images_mock):
        resp = await client.post(
            f"/api/print/{printer_slug}/batch",
            json=_four_item_body(),
        )
        assert resp.status_code == 202, resp.text
        rb = resp.json()
        assert len(rb["job_ids"]) == 4
        assert rb["errors"] == []

        # Wait for the worker to dequeue + call print_images
        deadline = asyncio.get_event_loop().time() + 5.0
        while asyncio.get_event_loop().time() < deadline:
            if print_images_mock.await_count >= 1:
                break
            await asyncio.sleep(0.05)

    # CRITICAL: print_images called ONCE — not N times (one per image)
    assert print_images_mock.await_count == 1, (
        f"Expected print_images called 1x, got {print_images_mock.await_count}x"
    )

    # Verify all 4 images were passed in that single call
    call_args = print_images_mock.call_args
    assert call_args is not None, "print_images was never called"
    images_arg = call_args.args[0]
    assert len(images_arg) == 4, (
        f"Expected 4 images in print_images call, got {len(images_arg)}"
    )

    # All 4 job_ids must reach state='done'
    for job_id in rb["job_ids"]:
        result = await _poll_job_state(client, job_id, target="done")
        assert result["state"] == "done", (
            f"Job {job_id} expected state='done', got {result['state']!r}"
        )


# ---------------------------------------------------------------------------
# Test 2: print_images raises → all 4 jobs → failed with shared message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_batch_failure_marks_all_jobs_failed(ml_batch_client):
    """When print_images raises, all 4 job_ids reach state='failed'.

    Uses a RuntimeError (non-PrinterError) so the worker hits the generic
    except-Exception handler and sets error = 'batch print failed: ...' on
    all jobs atomically.
    """
    client, inner_app = ml_batch_client
    printer_slug = inner_app.state.backend_router.slugs()[0]
    mock_backend = inner_app.state.backend_router.get(printer_slug)
    assert mock_backend is not None, f"No backend for slug {printer_slug!r}"

    error_message = "simulated batch failure"
    failing_mock = AsyncMock(side_effect=RuntimeError(error_message))

    with patch.object(mock_backend, "print_images", failing_mock):
        resp = await client.post(
            f"/api/print/{printer_slug}/batch",
            json=_four_item_body(),
        )
        assert resp.status_code == 202, resp.text
        rb = resp.json()
        assert len(rb["job_ids"]) == 4
        assert rb["errors"] == []

        # Wait for the worker to attempt + fail
        deadline = asyncio.get_event_loop().time() + 5.0
        while asyncio.get_event_loop().time() < deadline:
            if failing_mock.await_count >= 1:
                break
            await asyncio.sleep(0.05)

    # print_images was called exactly once (then raised)
    assert failing_mock.await_count == 1, (
        f"Expected print_images attempted 1x, got {failing_mock.await_count}x"
    )

    # All 4 job_ids must reach state='failed' with shared error message
    for job_id in rb["job_ids"]:
        result = await _poll_job_state(client, job_id, target="failed", timeout_s=5.0)
        assert result["state"] == "failed", (
            f"Job {job_id} expected state='failed', got {result['state']!r}"
        )
        # error field contains the shared batch failure message
        job_error: str = result.get("error") or ""
        assert "batch print failed" in job_error, (
            f"Job {job_id} error {job_error!r} does not contain 'batch print failed'"
        )
