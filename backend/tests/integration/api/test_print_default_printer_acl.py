"""Per-printer access on the routes that act on the default printer.

POST /api/v1/print and POST /api/v1/printer/resume use the default printer (the first by
created_at). A print key restricted to another printer must get 403 there. Real lifespan and
real API keys, no dependency overrides.
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
from app.models.job import Job as DbJob
from app.models.printer import Printer
from app.repositories import printers as printers_repo
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from tests.integration.api.test_sheet_types_api import _factory, _insert_key

pytestmark = pytest.mark.asyncio

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
        a = await printers_repo.create(
            s, Printer(name="Tape A", slug="tape-a", model="PT-P750W", backend="mock")
        )
        await asyncio.sleep(0.01)
        b = await printers_repo.create(
            s, Printer(name="Tape B", slug="tape-b", model="PT-P750W", backend="mock")
        )
        a_id, b_id = a.id, b.id
    app = create_app()
    inner = app._app
    async with (
        inner.router.lifespan_context(inner),
        AsyncClient(transport=ASGITransport(app=inner), base_url="http://t") as c,
    ):
        yield {"client": c, "app": inner, "a": a_id, "b": b_id}
    get_settings.cache_clear()


def _k(plaintext: str) -> dict[str, str]:
    return {"X-Label-Hub-Key": plaintext}


async def _job_count() -> int:
    async with _factory()() as s:
        return len((await s.execute(select(DbJob))).scalars().all())


async def test_print_key_for_b_cannot_print_on_default_printer_a(hub: dict[str, Any]) -> None:
    c, a_id, b_id = hub["client"], hub["a"], hub["b"]
    assert hub["app"].state.printer_id == a_id, "A must be the default printer"
    key_b = _k(await _insert_key(["print"], [str(b_id)]))
    before = await _job_count()

    resp = await c.post("/api/v1/print", json=_BODY, headers=key_b)

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["error_code"] == "printer_not_allowed"
    assert await _job_count() == before, "no job may be created for a refused key"


async def test_print_keys_for_default_printer_or_unrestricted_can_print(
    hub: dict[str, Any],
) -> None:
    c, a_id = hub["client"], hub["a"]
    for allowed in ([str(a_id)], []):
        key = _k(await _insert_key(["print"], allowed))
        resp = await c.post("/api/v1/print", json=_BODY, headers=key)
        assert resp.status_code == 202, resp.text
        job_id = UUID(resp.json()["job_id"])
        async with _factory()() as s:
            row = (await s.execute(select(DbJob).where(DbJob.id == job_id))).scalar_one()
        assert row.printer_id == a_id


async def test_print_key_for_b_cannot_resume_default_printer_a(hub: dict[str, Any]) -> None:
    c, a_id, b_id = hub["client"], hub["a"], hub["b"]
    key_a = _k(await _insert_key(["print", "read"], [str(a_id)]))
    key_b = _k(await _insert_key(["print"], [str(b_id)]))
    paused = await c.post(f"/api/v1/printers/{a_id}/pause", headers=key_a)
    assert paused.status_code in (200, 204), paused.text

    denied = await c.post("/api/v1/printer/resume", headers=key_b)

    assert denied.status_code == 403, denied.text
    assert denied.json()["detail"]["error_code"] == "printer_not_allowed"
    state = await c.get(f"/api/v1/printers/{a_id}", headers=key_a)
    assert state.json()["paused"] is True, "a refused key must not un-pause the printer"

    allowed = await c.post("/api/v1/printer/resume", headers=key_a)
    assert allowed.status_code == 200, allowed.text
    state = await c.get(f"/api/v1/printers/{a_id}", headers=key_a)
    assert state.json()["paused"] is False
