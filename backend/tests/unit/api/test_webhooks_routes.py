"""Unit tests for app.api.routes.webhooks — 2 endpoints, 4 scenarios each (Phase 6a Task 5).

Test mapping (Spoolman):
    1. POST /api/webhook/spoolman — missing X-API-Key header         → 422
    2. POST /api/webhook/spoolman — wrong key                         → 401
    3. POST /api/webhook/spoolman — valid key + valid payload          → 202 + job_id
    4. POST /api/webhook/spoolman — valid key + malformed payload      → 422

Test mapping (Grocy):
    5. POST /api/webhook/grocy — missing X-API-Key header             → 422
    6. POST /api/webhook/grocy — wrong key                             → 401
    7. POST /api/webhook/grocy — valid key + valid payload              → 202 + job_id
    8. POST /api/webhook/grocy — valid key + malformed payload          → 422
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import app.models  # noqa: F401 — registers all SQLModel tables with metadata
import pytest
import pytest_asyncio
from app.api.routes.webhooks import router
from app.config import Settings, get_settings
from app.db.engine import _apply_pragmas
from app.db.session import get_session
from app.models.printer import Printer
from app.schemas.label_data import LabelData
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_KEY = "webhook-secret-key-at-least-32chars!"
_WRONG_KEY = "wrong-key-xxxxxxxxxxxxxxxxxxxxxxxxxx"

# ---------------------------------------------------------------------------
# In-memory DB fixtures
# ---------------------------------------------------------------------------


def _make_engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(eng.sync_engine, "connect", _apply_pragmas)
    return eng


@pytest_asyncio.fixture
async def engine():
    eng = _make_engine()
    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s


# ---------------------------------------------------------------------------
# DB helpers — seed a default printer so webhook handlers can pick it
# ---------------------------------------------------------------------------


async def _seed_printer(session: AsyncSession) -> Printer:
    printer = Printer(
        name="Default Printer",
        model="PT-P750W",
        backend="ptouch",
        connection={"host": "198.51.100.100", "port": 9100},
        enabled=True,
    )
    session.add(printer)
    await session.commit()
    await session.refresh(printer)
    return printer


# ---------------------------------------------------------------------------
# App factory with DB + settings override
# ---------------------------------------------------------------------------


def _build_app(session_override: AsyncSession, key: str = _VALID_KEY) -> FastAPI:
    """Return a FastAPI app with webhooks router, DB, and settings overridden."""
    test_app = FastAPI()
    test_app.include_router(router)

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session_override

    settings_instance = Settings(
        _env_file=None,  # type: ignore[call-arg]
        webhook_api_key=SecretStr(key),
    )
    test_app.dependency_overrides[get_session] = _override_session
    test_app.dependency_overrides[get_settings] = lambda: settings_instance
    return test_app


# ---------------------------------------------------------------------------
# Shared LabelData fixture for mocking AppLookupService
# ---------------------------------------------------------------------------

_SPOOLMAN_LABEL = LabelData(
    title="Prusament PLA Galaxy Black",
    primary_id="#42",
    qr_payload="http://spoolman.local/spool/show/42",
    source_app="spoolman",
    secondary=("850g remaining",),
)

_GROCY_LABEL = LabelData(
    title="Olive Oil Extra Virgin",
    primary_id="17",
    qr_payload="http://grocy.local/product/17",
    source_app="grocy",
    secondary=(),
)


# ===========================================================================
# Spoolman webhook tests
# ===========================================================================


@pytest.mark.asyncio
async def test_spoolman_webhook_missing_api_key_header_returns_422(session) -> None:
    """POST /api/webhook/spoolman without X-API-Key returns 422 (missing required header)."""
    client = TestClient(_build_app(session), raise_server_exceptions=False)
    r = client.post(
        "/api/webhook/spoolman",
        json={"spool_id": "42", "type": "updated"},
        # No X-API-Key header
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_spoolman_webhook_wrong_key_returns_401(session) -> None:
    """POST /api/webhook/spoolman with wrong X-API-Key returns 401."""
    client = TestClient(_build_app(session), raise_server_exceptions=False)
    r = client.post(
        "/api/webhook/spoolman",
        json={"spool_id": "42", "type": "updated"},
        headers={"X-API-Key": _WRONG_KEY},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_spoolman_webhook_valid_payload_returns_202_with_job_id(session) -> None:
    """POST /api/webhook/spoolman with valid key + payload returns 202 WebhookAcceptedResponse."""
    await _seed_printer(session)

    with patch(
        "app.api.routes.webhooks._lookup_service.lookup",
        new=AsyncMock(return_value=_SPOOLMAN_LABEL),
    ):
        client = TestClient(_build_app(session), raise_server_exceptions=True)
        r = client.post(
            "/api/webhook/spoolman",
            json={"spool_id": "42", "type": "updated", "quantity": 850.0},
            headers={"X-API-Key": _VALID_KEY},
        )

    assert r.status_code == 202
    body = r.json()
    assert "job_id" in body
    # job_id must be a valid UUID string
    import uuid

    uuid.UUID(body["job_id"])  # raises ValueError if invalid


@pytest.mark.asyncio
async def test_spoolman_webhook_malformed_payload_returns_422(session) -> None:
    """POST /api/webhook/spoolman without required spool_id returns 422."""
    client = TestClient(_build_app(session), raise_server_exceptions=False)
    r = client.post(
        "/api/webhook/spoolman",
        json={"type": "updated"},  # missing spool_id
        headers={"X-API-Key": _VALID_KEY},
    )
    assert r.status_code == 422


# ===========================================================================
# Grocy webhook tests
# ===========================================================================


@pytest.mark.asyncio
async def test_grocy_webhook_missing_api_key_header_returns_422(session) -> None:
    """POST /api/webhook/grocy without X-API-Key returns 422 (missing required header)."""
    client = TestClient(_build_app(session), raise_server_exceptions=False)
    r = client.post(
        "/api/webhook/grocy",
        json={"product_id": "17", "type": "stock_added"},
        # No X-API-Key header
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_grocy_webhook_wrong_key_returns_401(session) -> None:
    """POST /api/webhook/grocy with wrong X-API-Key returns 401."""
    client = TestClient(_build_app(session), raise_server_exceptions=False)
    r = client.post(
        "/api/webhook/grocy",
        json={"product_id": "17", "type": "stock_added"},
        headers={"X-API-Key": _WRONG_KEY},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_grocy_webhook_valid_payload_returns_202_with_job_id(session) -> None:
    """POST /api/webhook/grocy with valid key + payload returns 202 WebhookAcceptedResponse."""
    await _seed_printer(session)

    with patch(
        "app.api.routes.webhooks._lookup_service.lookup",
        new=AsyncMock(return_value=_GROCY_LABEL),
    ):
        client = TestClient(_build_app(session), raise_server_exceptions=True)
        r = client.post(
            "/api/webhook/grocy",
            json={"product_id": "17", "type": "stock_added", "quantity": 3.0},
            headers={"X-API-Key": _VALID_KEY},
        )

    assert r.status_code == 202
    body = r.json()
    assert "job_id" in body
    import uuid

    uuid.UUID(body["job_id"])  # raises ValueError if invalid


@pytest.mark.asyncio
async def test_grocy_webhook_malformed_payload_returns_422(session) -> None:
    """POST /api/webhook/grocy without required product_id returns 422."""
    client = TestClient(_build_app(session), raise_server_exceptions=False)
    r = client.post(
        "/api/webhook/grocy",
        json={"type": "stock_added"},  # missing product_id
        headers={"X-API-Key": _VALID_KEY},
    )
    assert r.status_code == 422
