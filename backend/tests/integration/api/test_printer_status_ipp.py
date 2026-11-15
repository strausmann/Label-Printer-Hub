# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""GET /api/v1/printers/{id}/status for IPP page printers (cache written by IppStatusProducer)
and the regression for tape printers (new fields stay null)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

import app.models  # noqa: F401
import httpx
import pytest
import pytest_asyncio
from app.models.printer import Printer
from app.models.printer_status_cache import PrinterStatusCache
from app.models.printer_tray import PrinterTray
from app.printer_backends.ipp.client import IppClient
from app.services.event_bus import EventBus
from app.services.producers.ipp_status_producer import IppPrinterState, IppStatusProducer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.helpers.fake_ipp_printer import FAKE_URI, FakeIppPrinter
from tests.helpers.fake_printer_runtime import FakeRuntime

# Printers made by ``_printer`` count as polled: the status route needs a runtime to say so.
_RUNTIME = FakeRuntime()


@pytest.fixture(autouse=True)
def _trust_legacy_pangolin_user(monkeypatch: pytest.MonkeyPatch):
    """The reads authenticate with the legacy X-Pangolin-User header (D10 opt-in)."""
    from app.config import get_settings

    monkeypatch.setenv("LABELYARD_TRUST_LEGACY_PANGOLIN_USER", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def api(async_session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator:
    from app.api.dependencies.printer_runtime import get_printer_runtime
    from app.api.routes.printers import router
    from app.db.session import get_session
    from fastapi import FastAPI

    async with async_session_factory() as session:
        app = FastAPI()
        app.include_router(router)

        async def _override() -> AsyncIterator[AsyncSession]:
            yield session

        app.dependency_overrides[get_session] = _override
        app.dependency_overrides[get_printer_runtime] = lambda: _RUNTIME
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://t",
            headers={"X-Pangolin-User": "tester"},
        ) as c:
            yield c, async_session_factory


async def _printer(factory: async_sessionmaker[AsyncSession], backend: str) -> UUID:
    async with factory() as s:
        p = Printer(
            name=f"{backend}-status",
            slug=f"{backend}-status",
            model="x",
            backend=backend,
            connection={"uri": FAKE_URI} if backend == "ipp" else {"host": "127.0.0.1"},
        )
        s.add(p)
        await s.commit()
        _RUNTIME.polled.add(p.id)
        return p.id


async def test_ipp_status_has_reasons_markers_and_trays(api) -> None:
    client, factory = api
    pid = await _printer(factory, "ipp")
    async with factory() as s:
        s.add_all(
            [
                PrinterTray(
                    printer_id=pid,
                    tray_key="main-tray",
                    label="Label tray",
                    load_hint="Labels, print side down",
                    enabled=True,
                    is_default=True,
                ),
                PrinterTray(
                    printer_id=pid,
                    tray_key="auto",
                    label="Automatic",
                    load_hint=None,
                    enabled=True,
                    is_default=False,
                ),
            ]
        )
        await s.commit()
    fake = FakeIppPrinter(
        reasons=["toner-low-warning"],
        markers=[{"name": "Black Toner", "color": "#000000", "level": 15, "type": "toner"}],
        media_sources=["main-tray"],
    )
    producer = IppStatusProducer(
        bus=EventBus(),
        printer_id=pid,
        client=IppClient(FAKE_URI, transport=httpx.ASGITransport(app=fake)),
        session_factory=factory,
        state=IppPrinterState(),
        pause_control=None,
        interval_s=30,
    )
    await producer.probe_once()
    await producer.stop()

    body = (await client.get(f"/api/v1/printers/{pid}/status")).json()
    assert body["kind"] == "page"
    assert body["online"] is True
    assert body["tape_loaded"] is None
    assert body["error_state"] is None  # warning only, nothing blocks
    assert body["printer_state"] == "idle"
    assert [r["keyword"] for r in body["state_reasons"]] == ["toner-low"]
    assert body["state_reasons"][0]["severity"] == "warning"
    assert body["markers"][0]["name"] == "Black Toner"
    assert body["markers"][0]["level_percent"] == 15
    trays = {t["key"]: t for t in body["trays"]}
    assert trays["main-tray"]["label"] == "Label tray"
    assert trays["main-tray"]["load_hint"] == "Labels, print side down"
    assert trays["main-tray"]["is_default"] is True
    assert trays["auto"]["label"] == "Automatic"
    assert body["jobs_ahead"] == 0
    assert body["last_probe_age_s"] is not None

    fake.reasons = ["media-empty-error"]
    await _reprobe(factory, pid, fake)
    body = (await client.get(f"/api/v1/printers/{pid}/status")).json()
    assert body["error_state"] == "media-empty"


async def _reprobe(factory, pid: UUID, fake: FakeIppPrinter) -> None:
    producer = IppStatusProducer(
        bus=EventBus(),
        printer_id=pid,
        client=IppClient(FAKE_URI, transport=httpx.ASGITransport(app=fake)),
        session_factory=factory,
        state=IppPrinterState(),
        pause_control=None,
        interval_s=30,
    )
    await producer.probe_once()
    await producer.stop()


async def test_ipp_offline_status(api) -> None:
    client, factory = api
    pid = await _printer(factory, "ipp")
    async with factory() as s:
        s.add(
            PrinterStatusCache(
                printer_id=pid,
                parsed={"online": False, "last_error": "IppUnreachableError", "kind": "page"},
                captured_at=datetime.now(UTC),
            )
        )
        await s.commit()
    body = (await client.get(f"/api/v1/printers/{pid}/status")).json()
    # An incomplete cache row degrades to the basic page answer, never a 500.
    assert body["kind"] == "page" and body["online"] is False
    assert body["last_error"] == "IppUnreachableError"
    assert body["markers"] is None and body["trays"] is None


async def test_tape_status_unchanged(api) -> None:
    client, factory = api
    pid = await _printer(factory, "ptouch")
    async with factory() as s:
        s.add(
            PrinterStatusCache(
                printer_id=pid,
                parsed={
                    "online": True,
                    "loaded_tape_mm": 12,
                    "hr_printer_status": "idle",
                    "error_flags": [],
                },
                captured_at=datetime.now(UTC),
            )
        )
        await s.commit()
    body = (await client.get(f"/api/v1/printers/{pid}/status")).json()
    assert body["online"] is True
    assert body["tape_loaded"] == "12mm"
    assert body["error_state"] is None
    for key in ("kind", "printer_state", "state_reasons", "markers", "trays", "jobs_ahead"):
        assert body[key] is None, key


@pytest.mark.parametrize("backend", ["ipp"])
async def test_no_probe_yet_note(api, backend: str) -> None:
    client, factory = api
    pid = await _printer(factory, backend)
    body = (await client.get(f"/api/v1/printers/{pid}/status")).json()
    assert body["online"] is None and "No probe yet" in body["note"]


async def test_loaded_media_is_merged_into_configured_trays(api) -> None:
    from app.printer_backends.ipp.attributes import IppStatusRecord, TrayLoad
    from app.services.producers.ipp_status_producer import _offline_record

    client, factory = api
    pid = await _printer(factory, "ipp")
    record: IppStatusRecord = _offline_record(None).model_copy(
        update={
            "online": True,
            "printer_state": "idle",
            "trays": [
                TrayLoad(key="main-tray", media="A4 labels", ready=True),
                TrayLoad(key="side-tray", media="Letter", ready=True),
            ],
        }
    )
    async with factory() as s:
        s.add_all(
            [
                PrinterStatusCache(
                    printer_id=pid,
                    parsed=record.model_dump(mode="json"),
                    captured_at=datetime.now(UTC),
                ),
                PrinterTray(
                    printer_id=pid,
                    tray_key="main-tray",
                    label="Label tray",
                    load_hint=None,
                    enabled=True,
                    is_default=True,
                ),
            ]
        )
        await s.commit()
    body = (await client.get(f"/api/v1/printers/{pid}/status")).json()
    # Only configured trays are listed; the reported media comes from the matching key.
    assert [(t["key"], t["media"]) for t in body["trays"]] == [("main-tray", "A4 labels")]


async def test_page_status_trays_in_printer_order(api) -> None:
    """Trays come in the order the printer lists its ``media-source-supported`` (265-05).

    A tray the printer does not list (``auto``) comes last, however its key sorts.
    """
    from app.printer_backends.ipp.attributes import TrayLoad
    from app.services.producers.ipp_status_producer import _offline_record

    client, factory = api
    pid = await _printer(factory, "ipp")
    record = _offline_record(None).model_copy(
        update={
            "online": True,
            "printer_state": "idle",
            "trays": [
                TrayLoad(key="tray-3", media=None, ready=False),
                TrayLoad(key="tray-1", media=None, ready=False),
                TrayLoad(key="tray-2", media=None, ready=False),
            ],
        }
    )
    async with factory() as s:
        s.add(
            PrinterStatusCache(
                printer_id=pid, parsed=record.model_dump(mode="json"), captured_at=datetime.now(UTC)
            )
        )
        s.add_all(
            PrinterTray(
                printer_id=pid,
                tray_key=key,
                label=key,
                load_hint=None,
                enabled=True,
                is_default=key == "tray-3",
            )
            for key in ("tray-1", "tray-2", "tray-3", "auto")
        )
        await s.commit()
    body = (await client.get(f"/api/v1/printers/{pid}/status")).json()
    assert [t["key"] for t in body["trays"]] == ["tray-3", "tray-1", "tray-2", "auto"]
