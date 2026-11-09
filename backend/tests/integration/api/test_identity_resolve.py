"""An admin resolves a flagged device swap; the stored identity is visible to admins only (#231).

``POST /api/v1/admin/printers/{id}/identity/resolve``:
- ``same_device``: the observed identity becomes the stored one, calibration stays.
- ``replaced``: every stored calibration row of the printer goes, in the same transaction as the
  identity change; one failure rolls both back and the hold stays.

The full app (real queue, real runtime, the fake IPP printer) like ``test_identity_hold``.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from app.models.printer import Printer, PrinterAudit
from app.models.printer_calibration import PrinterCalibration
from app.models.printer_identity import PrinterIdentity
from app.printer_backends.snmp_helper import ObservedIdentity
from app.repositories import printer_identity as identity_repo
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers.fake_ipp_printer import FAKE_URI
from tests.integration.api.test_sheet_print_api import Rig, _body, _sheet, running
from tests.integration.api.test_sheet_types_api import _factory, _insert_key

pytestmark = pytest.mark.asyncio

SERIAL_A = "E1234567ABC"
SERIAL_B = "E7654321XYZ"


class BoomError(RuntimeError):
    pass


async def _flag_swap(rig: Rig) -> None:
    """Store SERIAL_A, then observe SERIAL_B: the printer is flagged and held."""
    sink = rig.app.state.printer_runtime._identity_sink
    await sink(rig.printer_id, ObservedIdentity(SERIAL_A, None, None))
    assert await sink(rig.printer_id, ObservedIdentity(SERIAL_B, None, None)) == "different"
    assert rig.app.state.print_queue.is_identity_held(rig.printer_id)


async def _admin() -> dict[str, str]:
    return {"X-Label-Hub-Key": await _insert_key(["admin"])}


async def _seed_calibrations(printer_id: UUID, *trays: str) -> None:
    async with _factory()() as s:
        for tray in trays:
            s.add(
                PrinterCalibration(
                    printer_id=printer_id,
                    tray_key=tray,
                    method="manual",
                    offset_x_hmm=10,
                    offset_y_hmm=-5,
                    scale_x_ppm=1_000_000,
                    scale_y_ppm=1_000_000,
                    rotation_udeg=0,
                )
            )
        await s.commit()


async def _calibration_trays(printer_id: UUID) -> list[str]:
    async with _factory()() as s:
        rows = await s.execute(
            select(PrinterCalibration.tray_key)
            .where(PrinterCalibration.printer_id == printer_id)  # type: ignore[arg-type]
            .order_by(PrinterCalibration.tray_key)  # type: ignore[arg-type]
        )
        return [r[0] for r in rows]


async def _identity(printer_id: UUID) -> PrinterIdentity:
    async with _factory()() as s:
        row = await s.get(PrinterIdentity, printer_id)
    assert row is not None
    return row


async def _other_printer() -> UUID:
    async with _factory()() as s:
        p = Printer(
            id=uuid4(),
            name="Other",
            slug="other-1",
            model="m",
            backend="ipp",
            connection={"uri": FAKE_URI, "tls_verify": True},
            enabled=False,
        )
        s.add(p)
        await s.commit()
        return p.id


def _url(printer_id: UUID) -> str:
    return f"/api/v1/admin/printers/{printer_id}/identity/resolve"


async def _resolve(
    rig: Rig, resolution: str, headers: dict[str, str] | None = None, pid: UUID | None = None
) -> httpx.Response:
    return await rig.client.post(
        _url(pid or rig.printer_id),
        json={"resolution": resolution},
        headers=headers if headers is not None else await _admin(),
    )


# ---------------------------------------------------------------------------- resolve


async def test_resolve_same_device_keeps_calibration() -> None:
    async with running() as rig:
        await _seed_calibrations(rig.printer_id, "auto", "gone")
        await _flag_swap(rig)
        events = rig.app.state.event_bus.subscribe(f"printer:{rig.printer_id}:state", "t-res")
        hub = rig.app.state.event_bus.subscribe("hub", "t-hub")

        resp = await _resolve(rig, "same_device")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["id"] == str(rig.printer_id)
        assert body["hardware_id"] == SERIAL_B and body["hardware_id_kind"] == "serial"
        assert body["hardware_id_seen_at"] is not None
        row = await _identity(rig.printer_id)
        assert (row.hardware_id, row.hardware_id_kind) == (SERIAL_B, "serial")
        assert row.observed_id is None and row.observed_kind is None
        assert row.mismatch_since is None
        assert await _calibration_trays(rig.printer_id) == ["auto", "gone"]
        assert not rig.app.state.print_queue.is_identity_held(rig.printer_id)
        event = events.get_nowait()
        assert event.event_type == "printer.identity_mismatch"
        assert event.data == {"mismatch": False}
        changed = hub.get_nowait()
        assert changed.event_type == "hub.printers_changed"
        assert changed.data["printer_id"] == str(rig.printer_id)


async def test_resolve_replaced_resets_calibration() -> None:
    async with running() as rig:
        other = await _other_printer()
        await _seed_calibrations(rig.printer_id, "auto", "gone")  # "gone" has no tray row
        await _seed_calibrations(other, "auto")
        await _flag_swap(rig)

        resp = await _resolve(rig, "replaced")

        assert resp.status_code == 200, resp.text
        assert resp.json()["hardware_id"] == SERIAL_B
        assert await _calibration_trays(rig.printer_id) == []
        assert await _calibration_trays(other) == ["auto"]  # untouched
        row = await _identity(rig.printer_id)
        assert row.hardware_id == SERIAL_B and row.mismatch_since is None
        assert not rig.app.state.print_queue.is_identity_held(rig.printer_id)


async def test_replaced_is_atomic(monkeypatch: pytest.MonkeyPatch) -> None:
    """The second calibration delete fails: no calibration row is lost, the mismatch stays."""
    async with running() as rig:
        await _seed_calibrations(rig.printer_id, "auto", "gone")
        await _flag_swap(rig)
        headers = await _admin()
        original = AsyncSession.delete
        calls = 0

        async def failing_delete(self: AsyncSession, instance: object) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise BoomError
            await original(self, instance)

        with monkeypatch.context() as m:
            m.setattr(AsyncSession, "delete", failing_delete)
            with pytest.raises(BoomError):
                await _resolve(rig, "replaced", headers)

        assert calls == 2
        assert await _calibration_trays(rig.printer_id) == ["auto", "gone"]
        row = await _identity(rig.printer_id)
        assert row.hardware_id == SERIAL_A and row.mismatch_since is not None
        assert rig.app.state.print_queue.is_identity_held(rig.printer_id)


async def test_a_failed_commit_keeps_the_hold(monkeypatch: pytest.MonkeyPatch) -> None:
    async with running() as rig:
        await _seed_calibrations(rig.printer_id, "auto")
        await _flag_swap(rig)
        headers = await _admin()
        armed = False
        adopt = identity_repo.adopt_observed
        commit = AsyncSession.commit

        async def adopting(*args: Any, **kw: Any) -> Any:
            nonlocal armed
            result = await adopt(*args, **kw)
            armed = True  # from here on the transaction is the only thing left to commit
            return result

        async def failing_commit(self: AsyncSession) -> None:
            if armed:
                raise BoomError
            await commit(self)

        with monkeypatch.context() as m:
            m.setattr(identity_repo, "adopt_observed", adopting)
            m.setattr(AsyncSession, "commit", failing_commit)
            with pytest.raises(BoomError):
                await _resolve(rig, "replaced", headers)

        assert rig.app.state.print_queue.is_identity_held(rig.printer_id)  # fail closed
        assert await _calibration_trays(rig.printer_id) == ["auto"]
        row = await _identity(rig.printer_id)
        assert row.hardware_id == SERIAL_A and row.mismatch_since is not None


async def test_resolve_without_mismatch_is_409() -> None:
    async with running() as rig:
        sink = rig.app.state.printer_runtime._identity_sink
        await sink(rig.printer_id, ObservedIdentity(SERIAL_A, None, None))
        await _seed_calibrations(rig.printer_id, "auto")

        for resolution in ("same_device", "replaced"):
            resp = await _resolve(rig, resolution)
            assert resp.status_code == 409, resp.text
            assert resp.json()["detail"]["error_code"] == "no-identity-mismatch"
        assert await _calibration_trays(rig.printer_id) == ["auto"]  # nothing reset
        assert (await _identity(rig.printer_id)).hardware_id == SERIAL_A


async def test_resolve_without_any_identity_row_is_409() -> None:
    async with running() as rig:
        resp = await _resolve(rig, "same_device")
        assert resp.status_code == 409, resp.text


async def test_resolve_unknown_printer_is_404() -> None:
    async with running() as rig:
        resp = await _resolve(rig, "same_device", pid=uuid4())
        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"]["error_code"] == "not_found"


async def test_resolve_rejects_other_bodies() -> None:
    async with running() as rig:
        await _flag_swap(rig)
        headers = await _admin()
        bad = await rig.client.post(
            _url(rig.printer_id), json={"resolution": "maybe"}, headers=headers
        )
        extra = await rig.client.post(
            _url(rig.printer_id),
            json={"resolution": "same_device", "hardware_id": "x"},
            headers=headers,
        )
        assert bad.status_code == 422 and extra.status_code == 422
        assert rig.app.state.print_queue.is_identity_held(rig.printer_id)


async def test_resolve_needs_admin() -> None:
    async with running() as rig:
        await _flag_swap(rig)

        for headers in (rig.key, rig.reader):  # print and read scope
            resp = await _resolve(rig, "same_device", headers)
            assert resp.status_code == 403, resp.text
        assert rig.app.state.print_queue.is_identity_held(rig.printer_id)
        assert (await _identity(rig.printer_id)).mismatch_since is not None


async def test_jobs_allowed_after_resolve() -> None:
    async with running() as rig:
        code = await _sheet()
        await _flag_swap(rig)
        assert (await rig.print(_body(code, 1))).status_code == 409

        assert (await _resolve(rig, "same_device")).status_code == 200

        assert (await rig.print(_body(code, 1))).status_code == 202


# ---------------------------------------------------------------------------- visibility


async def test_read_key_sees_no_hardware_id() -> None:
    async with running() as rig:
        await _flag_swap(rig)

        listing = await rig.client.get("/api/v1/printers", headers=rig.reader)
        detail = await rig.client.get(f"/api/v1/printers/{rig.printer_id}", headers=rig.reader)

        assert listing.status_code == 200 and detail.status_code == 200
        entry = next(p for p in listing.json() if p["id"] == str(rig.printer_id))
        for view in (entry, detail.json()):
            assert view["hardware_id"] is None
            assert view["hardware_id_kind"] is None
            assert view["hardware_id_seen_at"] is None
        for resp in (listing, detail):
            assert SERIAL_A not in resp.text and SERIAL_B not in resp.text


async def test_admin_sees_hardware_id() -> None:
    async with running() as rig:
        sink = rig.app.state.printer_runtime._identity_sink
        await sink(rig.printer_id, ObservedIdentity(SERIAL_A, None, None))
        headers = await _admin()

        detail = await rig.client.get(f"/api/v1/printers/{rig.printer_id}", headers=headers)
        listing = await rig.client.get("/api/v1/printers", headers=headers)
        admin_detail = await rig.client.get("/api/v1/admin/printers/page-1", headers=headers)
        admin_list = await rig.client.get("/api/v1/admin/printers", headers=headers)

        views = [
            detail.json(),
            next(p for p in listing.json() if p["id"] == str(rig.printer_id)),
            admin_detail.json(),
            next(p for p in admin_list.json() if p["id"] == str(rig.printer_id)),
        ]
        for view in views:
            assert view["hardware_id"] == SERIAL_A
            assert view["hardware_id_kind"] == "serial"
            assert view["hardware_id_seen_at"] is not None


async def test_admin_sees_null_without_identity() -> None:
    async with running() as rig:
        headers = await _admin()
        resp = await rig.client.get(f"/api/v1/printers/{rig.printer_id}", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["hardware_id"] is None and body["hardware_id_kind"] is None


# ---------------------------------------------------------------------------- audit and logs


async def test_audit_row_has_no_identity_value() -> None:
    async with running() as rig:
        await _seed_calibrations(rig.printer_id, "auto", "gone")
        await _flag_swap(rig)

        assert (await _resolve(rig, "replaced")).status_code == 200

        async with _factory()() as s:
            rows = list(
                (
                    await s.execute(
                        select(PrinterAudit).where(
                            PrinterAudit.action == "identity_resolved"  # type: ignore[arg-type]
                        )
                    )
                ).scalars()
            )
        (audit,) = rows
        assert audit.printer_id == rig.printer_id and audit.slug == "page-1"
        assert audit.after_json == {"resolution": "replaced", "calibrations_removed": 2}
        text = json.dumps([audit.before_json, audit.after_json])
        assert SERIAL_A not in text and SERIAL_B not in text


async def test_resolve_logs_no_identity(caplog: pytest.LogCaptureFixture) -> None:
    async with running() as rig:
        await _flag_swap(rig)
        headers = await _admin()
        with caplog.at_level(logging.DEBUG):
            resp = await _resolve(rig, "same_device", headers)
        assert resp.status_code == 200
        assert SERIAL_A not in caplog.text and SERIAL_B not in caplog.text
