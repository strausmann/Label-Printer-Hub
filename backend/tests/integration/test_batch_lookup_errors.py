"""POST /api/v1/print/{printer}/batch with ``lookup`` items: real route, real PrintService and
AppLookupService, fake integration plugins.

Covers what the e2e cannot: the integration failing. Each outcome must answer with its own
status and code, and the body must never carry the plugin's own error text (it can wrap
upstream URLs and details).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from app.api.error_handlers import register_error_handlers
from app.api.routes.batch import router as batch_router
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_print
from app.db.session import get_session
from app.integrations.registry import IntegrationRegistry
from app.models.printer import Printer
from app.printer_backends.snmp_helper import PreflightStatus
from app.schemas.label_data import LabelData
from app.services.errors import AppLookupNotFoundError, IntegrationNotConfiguredError
from app.services.layout_engine import LayoutEngine
from app.services.lookup_service import AppLookupService
from app.services.print_service import PrintService
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

UPSTREAM_SECRET = "https://snipe.internal.example.invalid/api/v1/hardware/9?token=abc123"


class _Plugin:
    """Stands in for an integration; ``behaviour`` decides what lookup does."""

    display_name = "Fake"

    def __init__(self, name: str, behaviour: Any) -> None:
        self.name = name
        self._behaviour = behaviour

    async def lookup(self, identifier: str) -> LabelData:
        if isinstance(self._behaviour, Exception):
            raise self._behaviour
        return LabelData(
            source_app=self.name,
            title="Cordless drill",
            primary_id=identifier,
            qr_payload="https://example.invalid/x",
        )

    def bind(self, store: Any) -> None:  # protocol
        return None

    async def reconfigure(self) -> None:
        return None

    def is_configured(self) -> bool:
        return True


@pytest_asyncio.fixture
async def batch_env(db_session) -> AsyncIterator[tuple[AsyncClient, MagicMock, FastAPI]]:
    printer = Printer(name="P", slug="p", model="PT-P750W", backend="ptouch", connection={})
    db_session.add(printer)
    await db_session.commit()

    store = MagicMock()
    store.save_queued = AsyncMock()
    queue = MagicMock()
    queue.enqueue_batch = AsyncMock()
    backend = AsyncMock()
    backend.half_cut_supported = False
    backend.preflight_check = AsyncMock(
        return_value=PreflightStatus(hr_printer_status="idle", loaded_tape_mm=12, error_flags=[])
    )
    service = PrintService(
        printer_id=printer.id,
        backend=backend,
        queue=queue,
        store=store,
        engine=LayoutEngine(),
        lookup_service=AppLookupService(),
    )
    router_stub = MagicMock()
    router_stub.get = lambda _slug: backend
    router_stub.service_for = lambda _slug: service

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(batch_router)
    app.state.backend_router = router_stub
    ctx = AuthContext(source="api-key", scope="admin", api_key_id=uuid4(), ip="127.0.0.1")
    app.dependency_overrides[require_print] = lambda: ctx

    async def _session() -> AsyncIterator[Any]:
        yield db_session

    app.dependency_overrides[get_session] = _session

    saved = IntegrationRegistry.all()
    IntegrationRegistry.clear()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            yield client, queue, app
    finally:
        IntegrationRegistry.clear()
        for plugin in saved.values():
            IntegrationRegistry.register(plugin)


def _body(app_name: str = "snipeit", identifier: str = "42") -> dict[str, Any]:
    return {
        "items": [
            {"content_type": "qr_two_lines", "lookup": {"app": app_name, "identifier": identifier}}
        ]
    }


async def _post(client: AsyncClient, app_name: str = "snipeit") -> Any:
    return await client.post("/api/v1/print/p/batch", json=_body(app_name))


@pytest.mark.asyncio
async def test_lookup_item_is_resolved_and_queued(batch_env) -> None:
    client, queue, _ = batch_env
    IntegrationRegistry.register(_Plugin("snipeit", None))  # type: ignore[arg-type]
    response = await _post(client)
    assert response.status_code == 202, response.text
    assert len(response.json()["job_ids"]) == 1
    queue.enqueue_batch.assert_awaited_once()


@pytest.mark.asyncio
async def test_unknown_item_answers_404_and_queues_nothing(batch_env) -> None:
    client, queue, _ = batch_env
    missing = AppLookupNotFoundError("asset 42 not found")
    IntegrationRegistry.register(_Plugin("snipeit", missing))  # type: ignore[arg-type]
    response = await _post(client)
    assert response.status_code == 404
    queue.enqueue_batch.assert_not_awaited()


@pytest.mark.asyncio
async def test_unconfigured_integration_answers_503(batch_env) -> None:
    client, queue, _ = batch_env
    unconfigured = IntegrationNotConfiguredError("Snipe-IT is not configured")
    IntegrationRegistry.register(_Plugin("snipeit", unconfigured))  # type: ignore[arg-type]
    response = await _post(client)
    assert response.status_code == 503
    assert response.json()["type"] == "integration_not_configured"
    queue.enqueue_batch.assert_not_awaited()


@pytest.mark.asyncio
async def test_failing_integration_answers_502_with_a_fixed_message(batch_env) -> None:
    client, queue, _ = batch_env
    IntegrationRegistry.register(_Plugin("snipeit", RuntimeError(f"GET {UPSTREAM_SECRET} failed")))  # type: ignore[arg-type]
    response = await _post(client)
    assert response.status_code == 502, response.text
    detail = response.json()["detail"]
    assert detail["error_code"] == "integration_lookup_failed"
    # The plugin's text wraps upstream details; none of it may reach the client.
    assert "internal.example" not in response.text
    assert "abc123" not in response.text
    queue.enqueue_batch.assert_not_awaited()


@pytest.mark.asyncio
async def test_unregistered_app_is_its_own_code_not_a_500(batch_env) -> None:
    client, queue, _ = batch_env
    response = await _post(client, "grocy")
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["error_code"] == "integration_unknown_app"
    queue.enqueue_batch.assert_not_awaited()
