# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for app.api.routes.webhooks — 2 endpoints, 4 scenarios each (Phase 6a Task 5).

Test mapping (Spoolman):
    1. POST /api/v1/webhook/spoolman — missing X-API-Key header         → 422
    2. POST /api/v1/webhook/spoolman — wrong key                         → 401
    3. POST /api/v1/webhook/spoolman — valid key + valid payload          → 202 + job_id
    4. POST /api/v1/webhook/spoolman — valid key + malformed payload      → 422

Test mapping (Grocy):
    5. POST /api/v1/webhook/grocy — missing X-API-Key header             → 422
    6. POST /api/v1/webhook/grocy — wrong key                             → 401
    7. POST /api/v1/webhook/grocy — valid key + valid payload              → 202 + job_id
    8. POST /api/v1/webhook/grocy — valid key + malformed payload          → 422
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import app.models  # noqa: F401 — registers all SQLModel tables with metadata
import pytest
import pytest_asyncio
from app.api.routes.webhooks import router
from app.db.engine import _apply_pragmas
from app.db.session import get_session
from app.models.printer import Printer
from app.printer_backends.exceptions import NoTapeLoadedError, PrinterOfflineError
from app.schemas.content_type import ContentType
from app.schemas.print_request import PrintLookupRequest, PrintOptions, PrintRequest
from app.services.lookup_service import LookupFailedError, UnknownAppError
from fastapi import FastAPI
from fastapi.testclient import TestClient
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


_SENTINEL = object()


def _service() -> AsyncMock:
    """A stand-in ``PrintService`` whose ``submit_print_job`` accepts."""
    service = AsyncMock()
    service.submit_print_job.return_value = uuid4()
    return service


class _StubRuntime:
    def __init__(self, service: object) -> None:
        self._service = service

    def print_service_for(self, _printer_id: UUID) -> object:
        return self._service


_BODIES = {
    "spoolman": {"spool_id": "42", "type": "updated"},
    "grocy": {"product_id": "17", "type": "consumed"},
}


def _build_app(
    session_override: AsyncSession, key: str = _VALID_KEY, service: object = _SENTINEL
) -> FastAPI:
    """Return a FastAPI app with webhooks router, DB, and settings overridden."""
    test_app = FastAPI()
    test_app.include_router(router)

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session_override

    class _StubStore:
        def get(self, _key: str) -> str:
            return key

    test_app.state.settings_store = _StubStore()
    test_app.state.printer_runtime = _StubRuntime(_service() if service is _SENTINEL else service)
    test_app.dependency_overrides[get_session] = _override_session
    return test_app


# ===========================================================================
# Spoolman webhook tests
# ===========================================================================


@pytest.mark.asyncio
async def test_spoolman_webhook_missing_api_key_header_returns_422(session) -> None:
    """POST /api/v1/webhook/spoolman without X-API-Key returns 422 (missing required header)."""
    client = TestClient(_build_app(session), raise_server_exceptions=False)
    r = client.post(
        "/api/v1/webhook/spoolman",
        json={"spool_id": "42", "type": "updated"},
        # No X-API-Key header
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_spoolman_webhook_wrong_key_returns_401(session) -> None:
    """POST /api/v1/webhook/spoolman with wrong X-API-Key returns 401."""
    client = TestClient(_build_app(session), raise_server_exceptions=False)
    r = client.post(
        "/api/v1/webhook/spoolman",
        json={"spool_id": "42", "type": "updated"},
        headers={"X-API-Key": _WRONG_KEY},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_spoolman_webhook_valid_payload_returns_202_with_job_id(session) -> None:
    """POST /api/v1/webhook/spoolman with a valid key and payload returns 202 with the job id."""
    await _seed_printer(session)

    client = TestClient(_build_app(session), raise_server_exceptions=True)
    r = client.post(
        "/api/v1/webhook/spoolman",
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
    """POST /api/v1/webhook/spoolman without required spool_id returns 422."""
    client = TestClient(_build_app(session), raise_server_exceptions=False)
    r = client.post(
        "/api/v1/webhook/spoolman",
        json={"type": "updated"},  # missing spool_id
        headers={"X-API-Key": _VALID_KEY},
    )
    assert r.status_code == 422


# ===========================================================================
# Grocy webhook tests
# ===========================================================================


@pytest.mark.asyncio
async def test_grocy_webhook_missing_api_key_header_returns_422(session) -> None:
    """POST /api/v1/webhook/grocy without X-API-Key returns 422 (missing required header)."""
    client = TestClient(_build_app(session), raise_server_exceptions=False)
    r = client.post(
        "/api/v1/webhook/grocy",
        json={"product_id": "17", "type": "stock_added"},
        # No X-API-Key header
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_grocy_webhook_wrong_key_returns_401(session) -> None:
    """POST /api/v1/webhook/grocy with wrong X-API-Key returns 401."""
    client = TestClient(_build_app(session), raise_server_exceptions=False)
    r = client.post(
        "/api/v1/webhook/grocy",
        json={"product_id": "17", "type": "stock_added"},
        headers={"X-API-Key": _WRONG_KEY},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_grocy_webhook_valid_payload_returns_202_with_job_id(session) -> None:
    """POST /api/v1/webhook/grocy with valid key + payload returns 202 WebhookAcceptedResponse."""
    await _seed_printer(session)

    client = TestClient(_build_app(session), raise_server_exceptions=True)
    r = client.post(
        "/api/v1/webhook/grocy",
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
    """POST /api/v1/webhook/grocy without required product_id returns 422."""
    client = TestClient(_build_app(session), raise_server_exceptions=False)
    r = client.post(
        "/api/v1/webhook/grocy",
        json={"type": "stock_added"},  # missing product_id
        headers={"X-API-Key": _VALID_KEY},
    )
    assert r.status_code == 422


# ===========================================================================
# 503 path — no enabled printers registered
# ===========================================================================


@pytest.mark.asyncio
async def test_spoolman_webhook_no_enabled_printers_returns_503(session) -> None:
    """POST /api/v1/webhook/spoolman with no enabled printers returns 503.

    _resolve_default_printer_id raises 503 when the printers table has no
    enabled rows (lines 77-83 of webhooks.py).
    """
    # Do NOT seed any printer — table is empty.
    client = TestClient(_build_app(session), raise_server_exceptions=False)
    r = client.post(
        "/api/v1/webhook/spoolman",
        json={"spool_id": "42", "type": "updated"},
        headers={"X-API-Key": _VALID_KEY},
    )
    assert r.status_code == 503
    assert "No enabled printers" in r.json()["detail"]


@pytest.mark.asyncio
async def test_grocy_webhook_no_enabled_printers_returns_503(session) -> None:
    """POST /api/v1/webhook/grocy with no enabled printers returns 503.

    Exercises _resolve_default_printer_id (lines 77-83) via the grocy handler.
    """
    # Do NOT seed any printer — table is empty.
    client = TestClient(_build_app(session), raise_server_exceptions=False)
    r = client.post(
        "/api/v1/webhook/grocy",
        json={"product_id": "7", "type": "consumed"},
        headers={"X-API-Key": _VALID_KEY},
    )
    assert r.status_code == 503
    assert "No enabled printers" in r.json()["detail"]


@pytest.mark.asyncio
async def test_spoolman_webhook_disabled_printer_returns_503(session) -> None:
    """POST /api/v1/webhook/spoolman when only printer is disabled returns 503.

    _resolve_default_printer_id filters out disabled printers; with only a
    disabled printer present the enabled list is empty → 503.
    """
    printer = Printer(
        name="Disabled Printer",
        model="PT-P750W",
        backend="ptouch",
        connection={"host": "198.51.100.100", "port": 9100},
        enabled=False,  # explicitly disabled
    )
    session.add(printer)
    await session.commit()

    client = TestClient(_build_app(session), raise_server_exceptions=False)
    r = client.post(
        "/api/v1/webhook/spoolman",
        json={"spool_id": "99", "type": "updated"},
        headers={"X-API-Key": _VALID_KEY},
    )
    assert r.status_code == 503


# ===========================================================================
# Optional quantity
# ===========================================================================


@pytest.mark.asyncio
async def test_spoolman_webhook_without_quantity_returns_202(session) -> None:
    """POST /api/v1/webhook/spoolman without optional 'quantity' returns 202.

    Exercises the ``if payload.quantity is not None`` False branch in the
    spoolman handler (lines 107-116 without the quantity write).
    """
    await _seed_printer(session)

    client = TestClient(_build_app(session), raise_server_exceptions=True)
    r = client.post(
        "/api/v1/webhook/spoolman",
        json={"spool_id": "42", "type": "updated"},  # no quantity field
        headers={"X-API-Key": _VALID_KEY},
    )

    assert r.status_code == 202
    body = r.json()
    assert "job_id" in body


@pytest.mark.asyncio
async def test_grocy_webhook_without_quantity_returns_202(session) -> None:
    """POST /api/v1/webhook/grocy without optional 'quantity' returns 202.

    Exercises the ``if payload.quantity is not None`` False branch in the
    grocy handler (lines 147-156 without the quantity write).
    """
    await _seed_printer(session)

    client = TestClient(_build_app(session), raise_server_exceptions=True)
    r = client.post(
        "/api/v1/webhook/grocy",
        json={"product_id": "17", "type": "stock_added"},  # no quantity field
        headers={"X-API-Key": _VALID_KEY},
    )

    assert r.status_code == 202
    body = r.json()
    assert "job_id" in body


# ===========================================================================
# Direct async tests — bypass TestClient thread to capture coverage correctly
# These call the route functions and helper directly in the pytest event loop.
# ===========================================================================


@pytest.mark.asyncio
async def test_resolve_default_printer_id_raises_503_when_no_printers(session) -> None:
    """_resolve_default_printer_id raises HTTP 503 when printers table is empty.

    Directly exercises lines 76-83 in the pytest async loop where coverage tracks.
    """
    from app.api.routes.webhooks import _resolve_default_printer_id
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await _resolve_default_printer_id(session)

    assert exc_info.value.status_code == 503
    assert "No enabled printers" in exc_info.value.detail


@pytest.mark.asyncio
async def test_resolve_default_printer_id_raises_503_when_only_disabled(session) -> None:
    """_resolve_default_printer_id raises 503 when all printers are disabled.

    Exercises the ``enabled`` filter (line 77) and the 503 branch (lines 79-82).
    """
    from app.api.routes.webhooks import _resolve_default_printer_id
    from fastapi import HTTPException

    printer = Printer(
        name="Offline Printer",
        model="PT-P750W",
        backend="ptouch",
        connection={"host": "198.51.100.200", "port": 9100},
        enabled=False,
    )
    session.add(printer)
    await session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await _resolve_default_printer_id(session)

    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_resolve_default_printer_id_returns_first_enabled_printer(session) -> None:
    """_resolve_default_printer_id returns the first enabled printer's ID string.

    Exercises line 83 (the successful return path).
    """
    from app.api.routes.webhooks import _resolve_default_printer_id

    printer = await _seed_printer(session)

    result = await _resolve_default_printer_id(session)

    assert result == str(printer.id)


def _submitted(service: AsyncMock) -> PrintRequest:
    service.submit_print_job.assert_awaited_once()
    return service.submit_print_job.await_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route", "body", "app_name", "identifier"),
    [
        ("spoolman", {"spool_id": "42", "type": "updated", "quantity": 850.0}, "spoolman", "42"),
        ("grocy", {"product_id": "17", "type": "consumed", "quantity": 3.0}, "grocy", "17"),
    ],
)
async def test_webhook_submits_a_two_line_qr_label_for_one_copy(
    session, route: str, body: dict, app_name: str, identifier: str
) -> None:
    """The handler hands a lookup request to the print service; ``quantity`` changes nothing."""
    await _seed_printer(session)
    service = _service()

    r = TestClient(_build_app(session, service=service)).post(
        f"/api/v1/webhook/{route}", json=body, headers={"X-API-Key": _VALID_KEY}
    )

    assert r.status_code == 202, r.text
    request = _submitted(service)
    assert request.content_type == ContentType.QR_TWO_LINES
    assert request.lookup == PrintLookupRequest(app=app_name, identifier=identifier)
    assert request.options == PrintOptions()
    assert request.options.copies == 1
    assert r.json()["job_id"] == str(service.submit_print_job.return_value)
    # no owner key is invented; the audit trail records the peer address only (263-79)
    assert service.submit_print_job.await_args.kwargs == {"source_ip": "testclient"}


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["spoolman", "grocy"])
async def test_webhook_without_a_wired_service_is_503(session, route: str) -> None:
    await _seed_printer(session)
    r = TestClient(_build_app(session, service=None), raise_server_exceptions=False).post(
        f"/api/v1/webhook/{route}", json=_BODIES[route], headers={"X-API-Key": _VALID_KEY}
    )
    assert r.status_code == 503
    assert "not attached" in r.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["spoolman", "grocy"])
@pytest.mark.parametrize(
    ("exc", "http_status", "code"),
    [
        (NoTapeLoadedError(), 409, "no_tape_loaded"),
        (PrinterOfflineError("x"), 503, "printer_offline"),
        (UnknownAppError("secret-upstream-detail"), 422, "integration_unknown_app"),
        (LookupFailedError("https://example.invalid/leak"), 502, "integration_lookup_failed"),
    ],
)
async def test_webhook_answers_print_errors_like_the_print_route(
    session, route: str, exc: Exception, http_status: int, code: str
) -> None:
    await _seed_printer(session)
    service = _service()
    service.submit_print_job.side_effect = exc

    r = TestClient(_build_app(session, service=service)).post(
        f"/api/v1/webhook/{route}", json=_BODIES[route], headers={"X-API-Key": _VALID_KEY}
    )

    assert r.status_code == http_status, r.text
    assert r.json()["error_code"] == code
    assert "example.invalid" not in r.text and "secret-upstream" not in r.text


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["spoolman", "grocy"])
async def test_webhook_rate_limit_is_per_key_and_shared(session, route: str, monkeypatch) -> None:
    from app.config import get_settings
    from app.services.rate_limiter import _rate_limiter

    monkeypatch.setenv("LABELYARD_WEBHOOK_LIMIT_PER_MINUTE", "1")
    get_settings.cache_clear()
    _rate_limiter.clear()
    try:
        await _seed_printer(session)
        client = TestClient(_build_app(session, service=_service()))
        ok = client.post(
            f"/api/v1/webhook/{route}", json=_BODIES[route], headers={"X-API-Key": _VALID_KEY}
        )
        other = "grocy" if route == "spoolman" else "spoolman"
        over = client.post(
            f"/api/v1/webhook/{other}", json=_BODIES[other], headers={"X-API-Key": _VALID_KEY}
        )
        assert (ok.status_code, over.status_code) == (202, 429)
        assert "Retry-After" in over.headers
        # the bucket is named by a hash: neither the key nor its hash is on the wire
        assert _VALID_KEY not in over.text
        digest = hashlib.sha256(_VALID_KEY.encode()).hexdigest()[:16]
        assert digest not in over.text
        assert all(_VALID_KEY not in str(k) for k in _rate_limiter._buckets)
        assert any(digest in str(k) for k in _rate_limiter._buckets)  # the digest is the name
    finally:
        _rate_limiter.clear()
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_resolve_default_printer_id_skips_an_ipp_page_printer(session) -> None:
    """Spec 11.4: a webhook is a tape job; the first enabled printer may be a page printer."""
    from app.api.routes.webhooks import _resolve_default_printer_id

    page = Printer(
        name="Office laser",
        slug="office-laser",
        model="x",
        backend="ipp",
        connection={"uri": "ipp://printer.example.invalid/ipp/print"},
    )
    session.add(page)
    await session.commit()
    tape = Printer(
        name="Workshop",
        model="PT-P750W",
        backend="ptouch",
        connection={"host": "198.51.100.30", "port": 9100},
    )
    session.add(tape)
    await session.commit()

    assert await _resolve_default_printer_id(session) == str(tape.id)


@pytest.mark.asyncio
async def test_resolve_default_printer_id_503_when_only_a_page_printer_exists(session) -> None:
    from app.api.routes.webhooks import _resolve_default_printer_id
    from fastapi import HTTPException

    session.add(
        Printer(
            name="Office laser",
            slug="office-laser",
            model="x",
            backend="ipp",
            connection={"uri": "ipp://printer.example.invalid/ipp/print"},
        )
    )
    await session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await _resolve_default_printer_id(session)

    assert exc_info.value.status_code == 503
    assert "No enabled printers" in exc_info.value.detail


# ===========================================================================
# R12-1: non-finite numbers are refused at the boundary
# ===========================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("route,id_field", [("spoolman", "spool_id"), ("grocy", "product_id")])
@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
async def test_a_non_finite_quantity_is_a_422_that_does_not_echo_it(
    session, route: str, id_field: str, bad: str
) -> None:
    """A stored literal NaN is not JSON: SQLite before 3.45 (the production image) rejects the
    document in every JSON function, which stopped the hub from starting."""
    from app.api.error_handlers import register_error_handlers

    test_app = _build_app(session)
    register_error_handlers(test_app)
    client = TestClient(test_app, raise_server_exceptions=False)

    r = client.post(
        f"/api/v1/webhook/{route}",
        content=f'{{"{id_field}": "ZQX-1", "type": "updated", "quantity": {bad}}}',
        headers={"X-API-Key": _VALID_KEY, "Content-Type": "application/json"},
    )

    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["error_code"] == "invalid_request"
    assert detail["error_detail"] == {"errors": ["quantity"]}
    assert "NaN" not in r.text and "nfinity" not in r.text and "ZQX-1" not in r.text


def test_calibration_values_refuse_non_finite_numbers() -> None:
    import pytest as _pytest
    from app.api.routes.calibration import ReadingIn
    from app.calibration.model import CalibrationIn
    from pydantic import ValidationError

    for bad in (float("nan"), float("inf")):
        with _pytest.raises(ValidationError):
            ReadingIn(col_gap=1, row_gap=1, across_mm=bad, down_mm=0)
        with _pytest.raises(ValidationError):
            CalibrationIn(offset_x_mm=bad)
        with _pytest.raises(ValidationError):
            CalibrationIn(scale_y=bad)


def test_a_job_payload_with_a_non_finite_number_is_not_stored() -> None:
    from app.models.job import FiniteJSON

    column = FiniteJSON()
    assert column.process_bind_param({"quantity": 1.5}, None) == {"quantity": 1.5}
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            column.process_bind_param({"quantity": bad}, None)
