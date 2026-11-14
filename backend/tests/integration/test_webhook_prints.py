# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The Spoolman and Grocy webhooks hand their job to the print queue (#188).

The real app and lifespan run against a temp database with one tape printer. Its backend is a
recording ``MockPrinterBackend`` (one shared instance, so ``printed_images`` survives an app
restart); the integration lookup is patched. Every wait is bounded.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import app.models  # noqa: F401
import pytest
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_admin, require_print, require_read
from app.config import get_settings
from app.models.job import Job as DbJob
from app.models.printer import Printer
from app.printer_backends.mock_backend import MockPrinterBackend
from app.repositories import printer_state as printer_state_repo
from app.schemas.label_data import LabelData
from app.services.backend_router import BackendRouter
from app.services.lookup_service import LookupFailedError
from app.services.rate_limiter import _rate_limiter
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

pytestmark = pytest.mark.asyncio

KEY = "webhook-secret-key-at-least-32chars!"
WRONG_KEY = "wrong-key-xxxxxxxxxxxxxxxxxxxxxxxxxx"
SPOOLMAN = "/api/v1/webhook/spoolman"
GROCY = "/api/v1/webhook/grocy"
SPOOL_BODY = {"spool_id": "42", "type": "updated"}
GROCY_BODY = {"product_id": "17", "type": "stock_added"}
LABEL = LabelData(
    title="Prusament PLA",
    primary_id="#42",
    qr_payload="https://spoolman.example.invalid/spool/show/42",
    source_app="spoolman",
    secondary=(),
)
WAIT_S = 5.0


def _headers(key: str = KEY) -> dict[str, str]:
    return {"X-API-Key": key}


@dataclass
class Hub:
    backend: MockPrinterBackend
    printer_id: UUID
    monkeypatch: pytest.MonkeyPatch

    def set_limit(self, limit: int) -> None:
        self.monkeypatch.setenv("LABELYARD_WEBHOOK_LIMIT_PER_MINUTE", str(limit))
        get_settings.cache_clear()

    @asynccontextmanager
    async def running(self) -> AsyncIterator[tuple[AsyncClient, Any]]:
        from app.main import create_app

        app = create_app()
        inner = app._app
        auth = AuthContext(source="api-key", scope="admin", api_key_id=uuid4(), ip="127.0.0.1")
        for dep in (require_read, require_print, require_admin):
            inner.dependency_overrides[dep] = lambda _c=auth: _c
        with patch(
            "app.services.lookup_service.AppLookupService.lookup",
            AsyncMock(return_value=LABEL),
        ):
            async with (
                inner.router.lifespan_context(inner),
                AsyncClient(transport=ASGITransport(app=inner), base_url="http://t") as client,
            ):
                yield client, inner


@pytest.fixture
async def hub(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Hub]:
    import app.db.engine as eng
    from app.integrations import (  # type: ignore[attr-defined]
        IntegrationRegistry,
        _discover_plugins,
    )

    if not IntegrationRegistry.names():
        _discover_plugins()
    monkeypatch.setenv("LABELYARD_WEBHOOK_API_KEY", KEY)
    get_settings.cache_clear()
    _rate_limiter.clear()
    backend = MockPrinterBackend()
    monkeypatch.setattr(BackendRouter, "_build_one", staticmethod(lambda _cfg: backend))
    monkeypatch.setattr(
        "app.services.printer_runtime._resolve_model_id_from_config",
        AsyncMock(return_value="PT-P750W"),
    )
    async with eng.async_session() as s:
        printer = Printer(
            name="Tape",
            slug="tape-1",
            model="PT-P750W",
            backend="ptouch",
            connection={"host": "198.51.100.10", "port": 9100},
            enabled=True,
        )
        s.add(printer)
        await s.commit()
        printer_id = printer.id
    yield Hub(backend=backend, printer_id=printer_id, monkeypatch=monkeypatch)
    _rate_limiter.clear()
    get_settings.cache_clear()


async def _until(predicate: Callable[[], Awaitable[bool]], what: str) -> None:
    async with asyncio.timeout(WAIT_S):
        while not await predicate():
            await asyncio.sleep(0.02)
    # asyncio.timeout raises TimeoutError with no context; ``what`` documents the wait above.
    assert what


async def _row(job_id: str | UUID) -> DbJob:
    import app.db.engine as eng

    async with eng.async_session() as s:
        row = await s.get(DbJob, UUID(str(job_id)))
        assert row is not None
        return row


async def _row_count() -> int:
    import app.db.engine as eng

    async with eng.async_session() as s:
        return int((await s.execute(select(func.count()).select_from(DbJob))).scalar_one())


async def _done(job_id: str) -> None:
    async def _is_done() -> bool:
        return (await _row(job_id)).state == "done"

    await _until(_is_done, f"job {job_id} done")


async def test_spoolman_webhook_prints_without_restart(hub: Hub) -> None:
    async with hub.running() as (client, _app):
        r = await client.post(SPOOLMAN, json=SPOOL_BODY, headers=_headers())
        assert r.status_code == 202, r.text
        await _done(r.json()["job_id"])
    assert len(hub.backend.printed_images) == 1


async def test_grocy_webhook_prints_without_restart(hub: Hub) -> None:
    async with hub.running() as (client, _app):
        r = await client.post(GROCY, json=GROCY_BODY, headers=_headers())
        assert r.status_code == 202, r.text
        await _done(r.json()["job_id"])
    assert len(hub.backend.printed_images) == 1


async def test_webhook_job_payload_is_rerenderable(hub: Hub) -> None:
    async with hub.running() as (client, _app):
        r = await client.post(SPOOLMAN, json=SPOOL_BODY, headers=_headers())
        assert r.status_code == 202, r.text
        job_id = r.json()["job_id"]
        await _done(job_id)
        payload = (await _row(job_id)).payload
        assert payload["content_type"] == "qr_two_lines"
        assert payload["label_data"]["qr_payload"] == LABEL.qr_payload
        # The webhook key is not an API key, so the job has no owner; an admin retries it.
        assert (await _row(job_id)).api_key_id is None
        retry = await client.post(f"/api/v1/jobs/{job_id}/retry")
        assert 200 <= retry.status_code < 300, retry.text


async def test_webhook_job_records_the_peer_address_but_no_key(hub: Hub) -> None:
    """263-79: a webhook job has no API key, but the audit trail still names where it came from."""
    async with hub.running() as (client, _app):
        r = await client.post(SPOOLMAN, json=SPOOL_BODY, headers=_headers())
        assert r.status_code == 202, r.text
        row = await _row(r.json()["job_id"])
        assert (row.api_key_id, row.source_ip) == (None, "127.0.0.1")
        await _done(r.json()["job_id"])


async def test_webhook_without_tape_is_409_and_leaves_no_row(hub: Hub) -> None:
    hub.backend._loaded_tape_mm = None  # type: ignore[assignment]
    async with hub.running() as (client, _app):
        before = await _row_count()
        r = await client.post(SPOOLMAN, json=SPOOL_BODY, headers=_headers())
        assert r.status_code == 409, r.text
        assert r.json()["error_code"] == "no_tape_loaded"
        assert await _row_count() == before
    assert hub.backend.printed_images == []


async def test_webhook_quantity_is_not_copies(hub: Hub) -> None:
    async with hub.running() as (client, _app):
        r = await client.post(SPOOLMAN, json={**SPOOL_BODY, "quantity": 5}, headers=_headers())
        assert r.status_code == 202, r.text
        job_id = r.json()["job_id"]
        await _done(job_id)
        await asyncio.sleep(0.3)  # a wrongly queued second copy would have printed by now
        payload = (await _row(job_id)).payload
        assert "quantity" not in payload
    assert len(hub.backend.printed_images) == 1


async def _set_language(app: Any, language: str) -> None:
    import app.db.engine as eng

    async with eng.async_session() as s:
        await app.state.settings_store.set_many(s, {"general.language": language})


async def _quantity_job(client: AsyncClient, path: str, body: dict[str, Any]) -> DbJob:
    r = await client.post(path, json=body, headers=_headers())
    assert r.status_code == 202, r.text
    await _done(r.json()["job_id"])
    return await _row(r.json()["job_id"])


async def test_spoolman_quantity_prints_three_lines(hub: Hub) -> None:
    async with hub.running() as (client, _app):
        row = await _quantity_job(client, SPOOLMAN, {**SPOOL_BODY, "quantity": 850.5})
        assert row.payload["content_type"] == "qr_three_lines"
        assert row.payload["label_data"]["secondary"][0] == "851g remaining"
    assert len(hub.backend.printed_images) == 1


async def test_quantity_line_follows_hub_language(hub: Hub) -> None:
    async with hub.running() as (client, app):
        await _set_language(app, "de")
        row = await _quantity_job(client, SPOOLMAN, {**SPOOL_BODY, "quantity": 850.5})
        assert row.payload["label_data"]["secondary"][0] == "851 g übrig"


async def test_grocy_quantity_line_follows_hub_language(hub: Hub) -> None:
    async with hub.running() as (client, app):
        await _set_language(app, "de")
        row = await _quantity_job(client, GROCY, {**GROCY_BODY, "quantity": -1.5})
        assert row.payload["label_data"]["secondary"][0] == "Bestandsänderung: -1,5"


async def test_grocy_quantity_prints_three_lines(hub: Hub) -> None:
    async with hub.running() as (client, _app):
        row = await _quantity_job(client, GROCY, {**GROCY_BODY, "quantity": -2})
        assert row.payload["content_type"] == "qr_three_lines"
        assert row.payload["label_data"]["secondary"][0] == "Stock change: -2"
    assert len(hub.backend.printed_images) == 1


async def test_webhook_without_quantity_is_unchanged(hub: Hub) -> None:
    async with hub.running() as (client, _app):
        for path, body in ((SPOOLMAN, SPOOL_BODY), (GROCY, GROCY_BODY)):
            row = await _quantity_job(client, path, body)
            assert row.payload["content_type"] == "qr_two_lines"
            assert row.payload["label_data"]["secondary"] == []


async def test_webhook_out_of_range_quantity_is_absent(hub: Hub) -> None:
    async with hub.running() as (client, _app):
        for path, body in (
            (SPOOLMAN, {**SPOOL_BODY, "quantity": -1}),
            (SPOOLMAN, {**SPOOL_BODY, "quantity": 1_000_001}),
            (GROCY, {**GROCY_BODY, "quantity": 1_000_001}),
        ):
            row = await _quantity_job(client, path, body)
            assert row.payload["content_type"] == "qr_two_lines"
            assert row.payload["label_data"]["secondary"] == []


async def test_quantity_job_survives_restart(hub: Hub) -> None:
    import app.db.engine as eng

    async with eng.async_session() as s:
        await printer_state_repo.set_paused(s, hub.printer_id, True)
    async with hub.running() as (client, _app):
        r = await client.post(SPOOLMAN, json={**SPOOL_BODY, "quantity": 850.5}, headers=_headers())
        assert r.status_code == 202, r.text
        job_id = r.json()["job_id"]
        await asyncio.sleep(0.2)
        assert (await _row(job_id)).state == "queued"
    async with eng.async_session() as s:
        await printer_state_repo.set_paused(s, hub.printer_id, False)
    async with hub.running():
        await _done(job_id)
        row = await _row(job_id)
        assert row.error is None
        assert row.payload["label_data"]["secondary"] == ["851g remaining"]
    assert len(hub.backend.printed_images) == 1


async def test_webhook_job_survives_restart(hub: Hub) -> None:
    import app.db.engine as eng

    async with eng.async_session() as s:
        await printer_state_repo.set_paused(s, hub.printer_id, True)
    async with hub.running() as (client, _app):
        r = await client.post(SPOOLMAN, json=SPOOL_BODY, headers=_headers())
        assert r.status_code == 202, r.text
        job_id = r.json()["job_id"]
        await asyncio.sleep(0.2)
        row = await _row(job_id)
        assert row.state == "queued"
        assert hub.backend.printed_images == []
    async with eng.async_session() as s:
        await printer_state_repo.set_paused(s, hub.printer_id, False)
    async with hub.running():
        await _done(job_id)
        assert (await _row(job_id)).error is None
    assert len(hub.backend.printed_images) == 1


async def test_webhook_lookup_failure_has_fixed_message(hub: Hub) -> None:
    async with hub.running() as (client, _app):
        with patch(
            "app.services.lookup_service.AppLookupService.lookup",
            AsyncMock(side_effect=LookupFailedError("upstream https://example.invalid/x")),
        ):
            r = await client.post(SPOOLMAN, json=SPOOL_BODY, headers=_headers())
        assert r.status_code == 502, r.text
        body = r.json()
        assert body["error_code"] == "integration_lookup_failed"
        assert body["error_message"] == "The integration failed or could not be reached."
        assert "example.invalid" not in r.text
        assert await _row_count() == 0


async def test_webhook_rate_limit(hub: Hub) -> None:
    hub.set_limit(2)
    async with hub.running() as (client, _app):
        first = await client.post(SPOOLMAN, json=SPOOL_BODY, headers=_headers())
        second = await client.post(GROCY, json=GROCY_BODY, headers=_headers())
        third = await client.post(SPOOLMAN, json=SPOOL_BODY, headers=_headers())
        assert (first.status_code, second.status_code) == (202, 202)
        assert third.status_code == 429, third.text
        assert int(third.headers["Retry-After"]) >= 1
        assert third.json()["detail"]["error_code"] == "rate_limit_exceeded"
        assert KEY not in third.text


async def test_webhook_wrong_key_uses_no_token(hub: Hub) -> None:
    hub.set_limit(1)
    async with hub.running() as (client, _app):
        bad = await client.post(SPOOLMAN, json=SPOOL_BODY, headers=_headers(WRONG_KEY))
        again = await client.post(SPOOLMAN, json=SPOOL_BODY, headers=_headers(WRONG_KEY))
        # 401 both times (a spent token would turn the second into a 429), and no bucket
        # exists for a key that never authenticated.
        assert (bad.status_code, again.status_code) == (401, 401)
        assert len(_rate_limiter._buckets) == 0
        good = await client.post(SPOOLMAN, json=SPOOL_BODY, headers=_headers())
        assert good.status_code == 202, good.text


async def test_webhook_disabled_printer_body_matches_print_route(hub: Hub) -> None:
    async with hub.running() as (client, app):
        service = app.state.printer_runtime.print_service_for(hub.printer_id)
        assert service is not None
        service._printer_enabled = False
        web = await client.post(SPOOLMAN, json=SPOOL_BODY, headers=_headers())
        direct = await client.post(
            "/api/v1/print",
            json={"content_type": "qr_two_lines", "data": {"title": "T", "primary_id": "1"}},
        )
        assert web.status_code == direct.status_code == 409, (web.text, direct.text)
        assert set(web.json()) == {"error", "slug"}
        assert web.json()["error"] == "printer_disabled"
        assert web.content == direct.content
