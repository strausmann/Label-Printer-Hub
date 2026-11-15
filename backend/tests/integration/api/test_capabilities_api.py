# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""GET /api/v1/printers/{id}/capabilities: tape and page printers, cache only, no connection."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import app.models  # noqa: F401
import bcrypt
import pytest
from app.calibration import service as calibration_service
from app.calibration.model import CalibrationIn
from app.models.api_key import ApiKey
from app.models.printer import Printer
from app.models.printer_calibration import PrinterCalibration
from app.models.printer_status_cache import PrinterStatusCache
from app.models.printer_tray import PrinterTray
from app.printer_backends.ipp.attributes import (
    IppStatusRecord,
    Margins,
    ProbeSummary,
    TrayLoad,
)
from app.schemas.tape_geometry import TAPE_GEOMETRY
from app.services.producers.ipp_status_producer import _empty_summary

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _printers_are_polled(monkeypatch: pytest.MonkeyPatch) -> None:
    """The printers here are inserted directly, so the runtime does not poll them; the cache
    rows stand for what a producer wrote. Tests of the unpolled case switch this off again."""
    from app.services.printer_runtime import PrinterRuntime

    monkeypatch.setattr(PrinterRuntime, "is_polled", lambda self, _id: True)


SECRET_URI = "ipps://printer-secret.example.invalid:631/ipp/print"


def _factory():
    import app.db.engine as _engine_module

    return _engine_module.async_session


async def _key(scopes: list[str], allowed: list[str] | None = None) -> dict[str, str]:
    plaintext = f"lh_pat_{uuid4().hex}"
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    async with _factory()() as s:
        s.add(
            ApiKey(
                name=f"cap-{uuid4().hex[:6]}",
                key_hash=hashed,
                key_prefix=plaintext[:16],
                scopes=scopes,
                allowed_printer_ids=allowed or [],
                enabled=True,
                rate_limit_per_minute=6000,
            )
        )
        await s.commit()
    return {"X-Label-Hub-Key": plaintext}


async def _tape_printer(model: str, loaded_mm: int | None) -> UUID:
    async with _factory()() as s:
        p = Printer(
            name=f"t-{uuid4().hex[:6]}",
            slug=f"t-{uuid4().hex[:6]}",
            model=model,
            backend="mock",
            connection={"host": "192.0.2.10"},
        )
        s.add(p)
        if loaded_mm is not None:
            s.add(
                PrinterStatusCache(
                    printer_id=p.id,
                    parsed={"online": True, "loaded_tape_mm": loaded_mm},
                    captured_at=datetime.now(UTC),
                )
            )
        await s.commit()
        return p.id


def _record() -> IppStatusRecord:
    return IppStatusRecord(
        online=True,
        printer_state="idle",
        reasons=[],
        blocking_reason=None,
        warnings=[],
        markers=[],
        trays=[TrayLoad(key="main", media="iso_a4_210x297mm", ready=True)],
        jobs_ahead=0,
        summary=ProbeSummary(
            make_and_model="Acme 1000",
            ipp_versions=["2.0"],
            pdf_supported=True,
            pdf_versions=[],
            resolutions_dpi=[300, 600],
            media_sizes=["iso_a4_210x297mm", "na_letter_8.5x11in", "custom_min_10x10mm"],
            media_types=["stationery", "labels"],
            media_sources=["main", "auto"],
            color_modes=["monochrome"],
            margins_hmm=Margins(top=423, left=423, bottom=423, right=423),
            media_col_supported=True,
            media_col_members=["media-size", "media-type", "media-source"],
            accepting_jobs=True,
            scaling_none_supported=True,
            monochrome_supported=True,
            one_sided_supported=True,
            state="idle",
        ),
    )


async def _ipp_printer(
    *,
    cached: bool = True,
    calibrate: bool = True,
    record: IppStatusRecord | None = None,
    disabled_calibrated: bool = False,
) -> UUID:
    async with _factory()() as s:
        p = Printer(
            name=f"i-{uuid4().hex[:6]}",
            slug=f"i-{uuid4().hex[:6]}",
            model="Acme 1000",
            backend="ipp",
            connection={"uri": SECRET_URI},
        )
        s.add(p)
        s.add(PrinterTray(printer_id=p.id, tray_key="main", label="Main", is_default=True))
        s.add(PrinterTray(printer_id=p.id, tray_key="auto", label="Auto"))
        if cached:
            s.add(
                PrinterStatusCache(
                    printer_id=p.id,
                    parsed=(record or _record()).model_dump(mode="json"),
                    captured_at=datetime.now(UTC),
                )
            )
        if disabled_calibrated:
            s.add(PrinterTray(printer_id=p.id, tray_key="off", label="Off", enabled=False))
            s.add(
                PrinterCalibration(
                    printer_id=p.id,
                    tray_key="off",
                    method="manual",
                    offset_x_hmm=300,
                    offset_y_hmm=0,
                    scale_x_ppm=1_000_000,
                    scale_y_ppm=1_000_000,
                    rotation_udeg=0,
                )
            )
        await s.commit()
        pid = p.id
    if calibrate:
        async with _factory()() as s:
            await calibration_service.put(
                s,
                pid,
                "main",
                CalibrationIn(offset_x_mm=1.25, offset_y_mm=-0.5),
                measured_on=None,
                actor="t",
            )
    return pid


async def test_pt_printer_reports_tape_capabilities(api_client_with_seed):
    c, reader = api_client_with_seed, await _key(["read"])
    pid = await _tape_printer("PT-P750W", 12)
    body = (await c.get(f"/api/v1/printers/{pid}/capabilities", headers=reader)).json()
    assert body["kind"] == "tape"
    assert body["resolution_dpi"] == {"x": 180, "y": 180}
    px = TAPE_GEOMETRY[12].printable_px
    assert body["media"]["width_mm"] == 12
    assert body["media"]["printable_px"] == px
    assert body["media"]["printable_mm"] == round(px / 180 * 25.4, 2)
    assert body["trays"] is None and body["document_formats"] is None
    assert body["captured_at"] is not None


async def test_ql_printer_resolution(api_client_with_seed):
    c, reader = api_client_with_seed, await _key(["read"])
    await c.get("/healthz")  # start the app first: its startup builds a queue for stored printers
    pid = await _tape_printer("QL-820NWB", 62)
    body = (await c.get(f"/api/v1/printers/{pid}/capabilities", headers=reader)).json()
    assert body["resolution_dpi"] == {"x": 300, "y": 300}


async def test_tape_printer_without_tape_or_cache(api_client_with_seed):
    c, reader = api_client_with_seed, await _key(["read"])
    never = await _tape_printer("PT-P750W", None)
    body = (await c.get(f"/api/v1/printers/{never}/capabilities", headers=reader)).json()
    assert body["media"] is None and body["captured_at"] is None
    assert body["resolution_dpi"] == {"x": 180, "y": 180}


async def test_ipp_printer_reports_page_capabilities(api_client_with_seed):
    c, reader = api_client_with_seed, await _key(["read"])
    pid = await _ipp_printer()
    resp = await c.get(f"/api/v1/printers/{pid}/capabilities", headers=reader)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "page"
    assert body["resolution_dpi"] == {"max": 600, "supported": [300, 600]}
    sizes = {s["name"]: s for s in body["media"]["page_sizes"]}
    assert (sizes["A4"]["width_mm"], sizes["A4"]["height_mm"]) == (210.0, 297.0)
    assert (sizes["Letter"]["width_mm"], sizes["Letter"]["height_mm"]) == (215.9, 279.4)
    assert len(sizes) == 2  # the custom range is not a page size
    assert body["media"]["hardware_margins_mm"] == {
        "top": 4.23,
        "left": 4.23,
        "bottom": 4.23,
        "right": 4.23,
    }
    assert body["media"]["media_type_settable"] is True
    assert body["media"]["media_types"] == ["stationery", "labels"]
    assert body["document_formats"] == ["application/pdf"]
    trays = {t["key"]: t for t in body["trays"]}
    assert trays["main"]["media"] == "iso_a4_210x297mm" and trays["main"]["is_default"] is True
    assert trays["main"]["calibration"]["offset_x_mm"] == 1.25
    assert trays["main"]["calibration"]["offset_y_mm"] == -0.5
    assert trays["auto"]["calibration"] is None


async def test_restart_with_the_printer_down_keeps_the_last_real_capabilities(
    api_client_with_seed,
):
    """The printer is stored with a real cached answer and is unreachable when the app starts.

    The app's status producer fails its first probe and writes the offline row; that write
    must keep the cached summary (CI saw the placeholder win, which reads as "unknown").
    Waits on the row itself, bounded, not on a sleep.
    """
    import asyncio

    c, reader = api_client_with_seed, await _key(["read"])
    pid = await _ipp_printer()  # seeded before the first request, so the app starts a producer
    assert (await c.get("/healthz")).status_code == 200  # starts the app and its producers
    async with asyncio.timeout(20):
        while True:
            async with _factory()() as s:
                row = await s.get(PrinterStatusCache, pid)
                if row is not None and (row.parsed or {}).get("last_error"):
                    break
            await asyncio.sleep(0.05)
    body = (await c.get(f"/api/v1/printers/{pid}/capabilities", headers=reader)).json()
    assert body["resolution_dpi"] == {"max": 600, "supported": [300, 600]}
    assert body["document_formats"] == ["application/pdf"]
    assert body["media"] is not None


async def test_ipp_response_leaks_no_connection_detail(api_client_with_seed):
    c, reader = api_client_with_seed, await _key(["read"])
    pid = await _ipp_printer()
    raw = (await c.get(f"/api/v1/printers/{pid}/capabilities", headers=reader)).text
    assert "printer-secret" not in raw and SECRET_URI not in raw
    assert "ipps://" not in raw and "connection" not in raw


async def test_ipp_printer_without_cache_answers_200(api_client_with_seed):
    c, reader = api_client_with_seed, await _key(["read"])
    pid = await _ipp_printer(cached=False, calibrate=False)
    resp = await c.get(f"/api/v1/printers/{pid}/capabilities", headers=reader)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["media"] is None and body["captured_at"] is None
    assert body["document_formats"] is None
    assert body["resolution_dpi"] == {"max": None, "supported": []}
    assert {t["key"] for t in body["trays"]} == {"main", "auto"}


async def test_access_control(api_client_with_seed):
    c = api_client_with_seed
    mine, other = await _ipp_printer(), await _ipp_printer()
    restricted = await _key(["read"], [str(mine)])
    resp = await c.get(f"/api/v1/printers/{other}/capabilities", headers=restricted)
    assert resp.status_code == 403
    assert resp.json()["detail"]["error_code"] == "printer_not_allowed"
    assert (
        await c.get(f"/api/v1/printers/{mine}/capabilities", headers=restricted)
    ).status_code == 200
    assert (await c.get(f"/api/v1/printers/{mine}/capabilities")).status_code == 401
    # The restriction is checked before any lookup: an unknown id is 403 for a restricted key.
    unknown = await c.get(f"/api/v1/printers/{uuid4()}/capabilities", headers=restricted)
    assert unknown.status_code == 403
    free = await _key(["read"])
    missing = await c.get(f"/api/v1/printers/{uuid4()}/capabilities", headers=free)
    assert missing.status_code == 404
    assert missing.json()["detail"]["error_code"] == "printer_not_found"


async def test_printer_that_never_answered_has_unknown_capabilities(api_client_with_seed):
    """The producer's placeholder (offline, empty summary) means unknown, not "accepts nothing"."""
    c, reader = api_client_with_seed, await _key(["read"])
    placeholder = IppStatusRecord(
        online=False,
        printer_state="stopped",
        reasons=[],
        blocking_reason=None,
        warnings=[],
        markers=[],
        trays=[],
        jobs_ahead=None,
        summary=_empty_summary(),
    )
    pid = await _ipp_printer(record=placeholder)
    body = (await c.get(f"/api/v1/printers/{pid}/capabilities", headers=reader)).json()
    assert body["media"] is None
    assert body["document_formats"] is None
    assert body["captured_at"] is None
    assert {t["key"] for t in body["trays"]} == {"main", "auto"}
    main = next(t for t in body["trays"] if t["key"] == "main")
    assert main["calibration"]["offset_x_mm"] == 1.25


async def test_answered_printer_without_pdf_lists_no_formats(api_client_with_seed):
    c, reader = api_client_with_seed, await _key(["read"])
    record = _record()
    record.summary.pdf_supported = False
    pid = await _ipp_printer(record=record)
    body = (await c.get(f"/api/v1/printers/{pid}/capabilities", headers=reader)).json()
    assert body["document_formats"] == []
    assert body["media"] is not None and body["captured_at"] is not None


async def test_unknown_printer_model_is_409_without_echo(api_client_with_seed):
    c, reader = api_client_with_seed, await _key(["read"])
    await c.get("/healthz")  # start the app first: startup refuses stored printers of unknown model
    pid = await _tape_printer("ZZ-NOSUCH-9000", 12)
    resp = await c.get(f"/api/v1/printers/{pid}/capabilities", headers=reader)
    assert resp.status_code == 409
    assert resp.json()["detail"]["error_code"] == "printer_model_unknown"
    assert "NOSUCH" not in resp.text


async def test_tape_width_without_geometry_has_no_media(api_client_with_seed):
    c, reader = api_client_with_seed, await _key(["read"])
    assert 3 not in TAPE_GEOMETRY
    pid = await _tape_printer("PT-P750W", 3)
    body = (await c.get(f"/api/v1/printers/{pid}/capabilities", headers=reader)).json()
    assert body["media"] is None and body["captured_at"] is not None


async def test_disabled_tray_lists_without_calibration(api_client_with_seed):
    c, reader = api_client_with_seed, await _key(["read"])
    pid = await _ipp_printer(calibrate=False, disabled_calibrated=True)
    body = (await c.get(f"/api/v1/printers/{pid}/capabilities", headers=reader)).json()
    off = next(t for t in body["trays"] if t["key"] == "off")
    assert off["enabled"] is False and off["calibration"] is None


async def _age_cache(pid: UUID, seconds: float) -> None:
    from datetime import timedelta

    stamp = datetime.now(UTC) - timedelta(seconds=seconds)
    async with _factory()() as s:
        row = await s.get(PrinterStatusCache, pid)
        assert row is not None
        row.updated_at = stamp
        row.captured_at = stamp
        await s.commit()


async def test_stale_tape_is_reported_as_unknown(api_client_with_seed):
    c, reader = api_client_with_seed, await _key(["read"])
    pid = await _tape_printer("PT-P750W", 12)
    await _age_cache(pid, 12_349_795)
    body = (await c.get(f"/api/v1/printers/{pid}/capabilities", headers=reader)).json()
    assert body["stale"] is True
    assert body["media"] is None
    assert body["captured_at"] is not None  # kept: the client shows the age


async def test_fresh_tape_is_not_stale(api_client_with_seed):
    c, reader = api_client_with_seed, await _key(["read"])
    pid = await _tape_printer("PT-P750W", 12)
    body = (await c.get(f"/api/v1/printers/{pid}/capabilities", headers=reader)).json()
    assert body["stale"] is False
    assert body["media"]["width_mm"] == 12


async def test_unpolled_tape_printer_is_reported_as_unknown(
    api_client_with_seed, monkeypatch: pytest.MonkeyPatch
):
    from app.services.printer_runtime import PrinterRuntime

    monkeypatch.setattr(PrinterRuntime, "is_polled", lambda self, _id: False)
    c, reader = api_client_with_seed, await _key(["read"])
    pid = await _tape_printer("PT-P750W", 12)
    body = (await c.get(f"/api/v1/printers/{pid}/capabilities", headers=reader)).json()
    assert body["stale"] is True
    assert body["media"] is None


async def test_stale_page_printer_is_reported_as_unknown(api_client_with_seed):
    c, reader = api_client_with_seed, await _key(["read"])
    await c.get("/healthz")  # start the app first: its startup would probe a stored printer
    pid = await _ipp_printer()
    await _age_cache(pid, 12_349_795)
    body = (await c.get(f"/api/v1/printers/{pid}/capabilities", headers=reader)).json()
    assert body["stale"] is True
    assert body["media"] is None and body["document_formats"] is None
