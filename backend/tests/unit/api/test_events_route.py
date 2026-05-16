# backend/tests/unit/api/test_events_route.py
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app as _app_wrapper
from app.services.event_bus import BusEvent, EventBus

_inner = _app_wrapper._app  # type: ignore[attr-defined]


@pytest.fixture()
def client_with_bus() -> TestClient:
    """TestClient with a real EventBus wired to app.state."""
    bus = EventBus(queue_size=8)
    _inner.state.event_bus = bus
    return TestClient(_inner, raise_server_exceptions=True)


def _mock_printer_get(return_value: object):  # type: ignore[no-untyped-def]
    return patch(
        "app.api.routes.events.printers_repo.get",
        new_callable=AsyncMock,
        return_value=return_value,
    )


def test_404_when_printer_not_found(client_with_bus: TestClient) -> None:
    with _mock_printer_get(None):
        resp = client_with_bus.get(f"/api/events?printer_id={uuid.uuid4()}")
    assert resp.status_code == 404


def test_429_when_subscriber_limit_exceeded(client_with_bus: TestClient) -> None:
    printer_id = uuid.uuid4()
    fake_printer = MagicMock()
    fake_printer.id = str(printer_id)

    bus: EventBus = _inner.state.event_bus
    # Saturate all three channels to exceed the per-printer cap
    from app.api.routes.events import _MAX_SUBSCRIBERS_PER_PRINTER

    for ch in (
        f"printer:{printer_id}:queue",
        f"printer:{printer_id}:state",
        f"printer:{printer_id}:tape",
    ):
        for i in range(_MAX_SUBSCRIBERS_PER_PRINTER):
            bus.subscribe(ch, f"fake-sub-{ch}-{i}")

    with _mock_printer_get(fake_printer):
        resp = client_with_bus.get(f"/api/events?printer_id={printer_id}")

    assert resp.status_code == 429
    body = resp.json()
    assert body["type"] == "sse-subscriber-limit"
