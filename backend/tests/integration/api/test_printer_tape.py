"""The tape endpoint and the structured width in the status read the SNMP cache (#229)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import app.models  # noqa: F401
import httpx
import pytest
import pytest_asyncio
from app.api.dependencies.printer_runtime import get_printer_runtime
from app.models.printer import Printer
from app.models.printer_status_cache import PrinterStatusCache
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.helpers.fake_printer_runtime import FakeRuntime


@pytest.fixture(autouse=True)
def _trust_legacy_pangolin_user(monkeypatch: pytest.MonkeyPatch):
    from app.config import get_settings

    monkeypatch.setenv("LABELYARD_TRUST_LEGACY_PANGOLIN_USER", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def api(async_session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator:
    from app.api.routes.printers import router
    from app.db.session import get_session
    from fastapi import FastAPI

    async with async_session_factory() as session:
        app = FastAPI()
        app.include_router(router)

        async def _override() -> AsyncIterator[AsyncSession]:
            yield session

        app.dependency_overrides[get_session] = _override
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://t",
            headers={"X-Pangolin-User": "tester"},
        ) as c:
            yield c, app, async_session_factory


async def _printer(factory) -> UUID:
    async with factory() as s:
        p = Printer(name="p", slug="p", model="x", backend="mock", connection={"host": "127.0.0.1"})
        s.add(p)
        await s.commit()
        return p.id


async def _cache_row(factory, pid: UUID, parsed: dict, *, age_s: float = 5) -> None:
    stamp = datetime.now(UTC) - timedelta(seconds=age_s)
    async with factory() as s:
        s.add(
            PrinterStatusCache(printer_id=pid, parsed=parsed, captured_at=stamp, updated_at=stamp)
        )
        await s.commit()


async def test_tape_endpoint_reads_snmp_cache(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _cache_row(factory, pid, {"online": True, "loaded_tape_mm": 62, "media_raw": "62mm"})
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    r = await client.get(f"/api/v1/printers/{pid}/tape")
    assert r.status_code == 200
    body = r.json()
    assert body["width_mm"] == 62
    assert body["media_raw"] == "62mm"
    assert body["colour"] is None


async def test_tape_endpoint_404_without_tape(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _cache_row(factory, pid, {"online": True, "loaded_tape_mm": None})
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    r = await client.get(f"/api/v1/printers/{pid}/tape")
    assert r.status_code == 404
    assert "no tape loaded" in r.json()["detail"]


async def test_tape_endpoint_404_without_row(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    assert (await client.get(f"/api/v1/printers/{pid}/tape")).status_code == 404


async def test_tape_label_comes_from_model_driver(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _cache_row(factory, pid, {"online": True, "loaded_tape_mm": 62})
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime(
        {pid}, labels={62: "62mm DK"}
    )
    body = (await client.get(f"/api/v1/printers/{pid}/tape")).json()
    assert body["label"] == "62mm DK"


async def test_tape_label_falls_back_to_generic(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _cache_row(factory, pid, {"online": True, "loaded_tape_mm": 99})
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    body = (await client.get(f"/api/v1/printers/{pid}/tape")).json()
    assert body["label"] == "99mm"


async def test_status_has_structured_width(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _cache_row(factory, pid, {"online": True, "loaded_tape_mm": 12})
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    body = (await client.get(f"/api/v1/printers/{pid}/status")).json()
    assert body["tape_width_mm"] == 12
    assert body["tape_colour"] is None
    assert body["tape_loaded"] == "12mm"


async def test_status_without_tape_has_no_width(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _cache_row(factory, pid, {"online": True, "loaded_tape_mm": None})
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    body = (await client.get(f"/api/v1/printers/{pid}/status")).json()
    assert body["tape_width_mm"] is None


async def test_stale_status_has_no_width(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _cache_row(factory, pid, {"online": True, "loaded_tape_mm": 12}, age_s=10_000)
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    body = (await client.get(f"/api/v1/printers/{pid}/status")).json()
    assert body["stale"] is True
    assert body["tape_width_mm"] is None


async def test_tape_404_cases_are_declared_in_openapi(api) -> None:
    _client, app, _ = api
    op = app.openapi()["paths"]["/api/v1/printers/{printer_id}/tape"]["get"]
    assert "404" in op["responses"]
    desc = op["responses"]["404"]["description"]
    for phrase in ("Not polled", "older than", "no tape", "no cached status"):
        assert phrase in desc


async def test_offline_printer_reports_no_tape(api) -> None:
    """An offline printer shows no tape and ``/tape`` answers 404 ``printer offline`` (263-31).

    The row is what ``StatusProbeProducer`` writes after a failed probe.
    """
    client, app, factory = api
    pid = await _printer(factory)
    await _cache_row(
        factory,
        pid,
        {"online": False, "loaded_tape_mm": None, "media_raw": None, "last_error": "timed out"},
    )
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    r = await client.get(f"/api/v1/printers/{pid}/tape")
    assert r.status_code == 404
    assert r.json() == {"detail": "printer offline"}
    status = (await client.get(f"/api/v1/printers/{pid}/status")).json()
    assert status["online"] is False
    assert status["tape_loaded"] is None
    assert status["tape_width_mm"] is None
    assert status["tape_colour"] is None
    assert status["roll_prompt"] is False


async def test_offline_row_with_a_leftover_tape_still_reports_none(api) -> None:
    """A row written before the producer cleared the tape must not resurrect it."""
    client, app, factory = api
    pid = await _printer(factory)
    await _cache_row(factory, pid, {"online": False, "loaded_tape_mm": 62, "media_raw": "62mm"})
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    r = await client.get(f"/api/v1/printers/{pid}/tape")
    assert (r.status_code, r.json()["detail"]) == (404, "printer offline")
    status = (await client.get(f"/api/v1/printers/{pid}/status")).json()
    assert status["tape_loaded"] is None and status["tape_width_mm"] is None


async def test_tape_404_body_matches_model(api) -> None:
    """The 404 body is the ``{"detail": ...}`` FastAPI sends, and OpenAPI describes exactly that."""
    from app.schemas.problem import DetailError

    client, app, factory = api
    pid = await _printer(factory)
    await _cache_row(factory, pid, {"online": False, "loaded_tape_mm": None})
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    r = await client.get(f"/api/v1/printers/{pid}/tape")
    assert r.status_code == 404
    assert set(r.json()) == {"detail"}
    assert DetailError.model_validate(r.json()).detail == "printer offline"
    spec = app.openapi()
    for path in ("/api/v1/printers/{printer_id}/tape", "/api/v1/printers/{printer_id}/status"):
        schema = spec["paths"][path]["get"]["responses"]["404"]["content"]["application/json"][
            "schema"
        ]
        assert schema == {"$ref": "#/components/schemas/DetailError"}


async def test_tape_endpoint_returns_every_tape_read_field(api) -> None:
    from app.models.printer_roll import PrinterRoll

    client, app, factory = api
    pid = await _printer(factory)
    await _cache_row(factory, pid, {"online": True, "loaded_tape_mm": 12, "media_raw": "12mm"})
    async with factory() as s:
        s.add(PrinterRoll(printer_id=pid, width_mm=12, media_raw="12mm", colour="red"))
        await s.commit()
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid}, labels={12: "12mm"})
    body = (await client.get(f"/api/v1/printers/{pid}/tape")).json()
    assert body == {"width_mm": 12, "label": "12mm", "media_raw": "12mm", "colour": "red"}
