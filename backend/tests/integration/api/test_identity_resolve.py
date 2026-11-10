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
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from app.api.routes import admin_printers_api as admin_routes
from app.models.printer import Printer, PrinterAudit
from app.models.printer_calibration import PrinterCalibration
from app.models.printer_identity import PrinterIdentity
from app.printer_backends.snmp_helper import ObservedIdentity
from app.repositories import printer_identity as identity_repo
from app.services.printer_admin_service import PrinterAdminService
from sqlalchemy import select

from tests.helpers.fake_ipp_printer import FAKE_URI
from tests.integration.api.test_sheet_print_api import Rig, _body, _sheet, running
from tests.integration.api.test_sheet_types_api import _factory, _insert_key

pytestmark = pytest.mark.asyncio

SERIAL_A = "E1234567ABC"
SERIAL_B = "E7654321XYZ"
SERIAL_C = "E5555555QQQ"


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


def _identity_events(queue: Any) -> list[dict[str, Any]]:
    """The ``printer.identity_mismatch`` payloads queued so far, in order.

    The state channel is shared: the IPP status producer starts its first probe with the app and
    publishes ``printer.status`` whenever that probe lands, which can be after the subscription.
    Only the identity events belong to these tests."""
    seen = []
    while not queue.empty():
        event = queue.get_nowait()
        if event is not None and event.event_type == "printer.identity_mismatch":
            seen.append(event.data)
    return seen


def _url(printer_id: UUID) -> str:
    return f"/api/v1/admin/printers/{printer_id}/identity/resolve"


async def _resolve(
    rig: Rig,
    resolution: str,
    headers: dict[str, str] | None = None,
    pid: UUID | None = None,
    *,
    expected: str = SERIAL_B,
) -> httpx.Response:
    """Resolve the way the admin UI does: bound to the device the admin reviewed."""
    return await rig.client.post(
        _url(pid or rig.printer_id),
        json={
            "resolution": resolution,
            "expected_observed_id": expected,
            "expected_observed_kind": "serial",
        },
        headers=headers if headers is not None else await _admin(),
    )


def _on_service_session(
    monkeypatch: pytest.MonkeyPatch, setup: Callable[[Any, pytest.MonkeyPatch], None]
) -> None:
    """Run ``setup(session, monkeypatch)`` on the session the resolve call uses.

    Patches that one session instance, not ``AsyncSession`` for every session of the process."""
    original = PrinterAdminService.resolve_identity

    async def wrapped(self: PrinterAdminService, *args: Any, **kw: Any) -> Any:
        setup(self._session, monkeypatch)
        return await original(self, *args, **kw)

    monkeypatch.setattr(PrinterAdminService, "resolve_identity", wrapped)


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
        assert _identity_events(events) == [{"mismatch": False}]
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
        calls = 0

        def setup(session: Any, m: pytest.MonkeyPatch) -> None:
            original = session.delete

            async def failing_delete(instance: object) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise BoomError
                await original(instance)

            m.setattr(session, "delete", failing_delete)

        with monkeypatch.context() as m:
            _on_service_session(m, setup)
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

        async def adopting(*args: Any, **kw: Any) -> Any:
            nonlocal armed
            result = await adopt(*args, **kw)
            armed = True  # from here on the transaction is the only thing left to commit
            return result

        def setup(session: Any, m: pytest.MonkeyPatch) -> None:
            commit = session.commit

            async def failing_commit() -> None:
                if armed:
                    raise BoomError
                await commit()

            m.setattr(session, "commit", failing_commit)

        with monkeypatch.context() as m:
            m.setattr(identity_repo, "adopt_observed", adopting)
            _on_service_session(m, setup)
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


@pytest.mark.parametrize("resolution", ["same_device", "replaced"])
async def test_resolve_logs_no_identity(resolution: str, caplog: pytest.LogCaptureFixture) -> None:
    async with running() as rig:
        await _seed_calibrations(rig.printer_id, "auto")
        await _flag_swap(rig)
        headers = await _admin()
        # INFO: aiosqlite's DEBUG logger prints every bound parameter, including the value the
        # caller sent; the application's own logging is what is asserted here.
        with caplog.at_level(logging.INFO):
            resp = await _resolve(rig, resolution, headers)
            changed = await _resolve(rig, resolution, headers, expected=SERIAL_A)  # 409 path
        assert resp.status_code == 200 and changed.status_code == 409
        assert SERIAL_A not in caplog.text and SERIAL_B not in caplog.text


# ---------------------------------------------------------------------------- review round 1


async def test_resolve_binds_to_the_reviewed_device() -> None:
    """The device changes again between the admin's review and the click: nothing is resolved."""
    async with running() as rig:
        await _seed_calibrations(rig.printer_id, "auto", "gone")
        await _flag_swap(rig)  # the admin reviewed SERIAL_B
        sink = rig.app.state.printer_runtime._identity_sink
        assert await sink(rig.printer_id, ObservedIdentity(SERIAL_C, None, None)) == "different"

        resp = await _resolve(rig, "replaced")  # still expects SERIAL_B

        assert resp.status_code == 409, resp.text
        detail = resp.json()["detail"]
        assert detail["type"] == "identity-changed" and detail["status"] == 409
        assert str(rig.printer_id) in detail["detail"]
        for value in (SERIAL_A, SERIAL_B, SERIAL_C):
            assert value not in resp.text
        assert await _calibration_trays(rig.printer_id) == ["auto", "gone"]
        row = await _identity(rig.printer_id)
        assert row.hardware_id == SERIAL_A and row.observed_id == SERIAL_C
        assert row.mismatch_since is not None
        assert rig.app.state.print_queue.is_identity_held(rig.printer_id)
        again = await _resolve(rig, "replaced", expected=SERIAL_C)  # re-reviewed: accepted
        assert again.status_code == 200, again.text


async def test_resolve_needs_the_reviewed_device_in_the_body() -> None:
    async with running() as rig:
        await _flag_swap(rig)
        headers = await _admin()
        for body in (
            {"resolution": "same_device"},
            {"resolution": "same_device", "expected_observed_id": SERIAL_B},
            {"resolution": "same_device", "expected_observed_kind": "serial"},
        ):
            resp = await rig.client.post(_url(rig.printer_id), json=body, headers=headers)
            assert resp.status_code == 422, resp.text
        assert rig.app.state.print_queue.is_identity_held(rig.printer_id)


async def test_admin_sees_the_observed_device_read_key_does_not() -> None:
    async with running() as rig:
        await _flag_swap(rig)
        headers = await _admin()

        admin = await rig.client.get(f"/api/v1/printers/{rig.printer_id}", headers=headers)
        admin_api = await rig.client.get("/api/v1/admin/printers/page-1", headers=headers)
        reader = await rig.client.get(f"/api/v1/printers/{rig.printer_id}", headers=rig.reader)

        for view in (admin.json(), admin_api.json()):
            assert view["observed_id"] == SERIAL_B and view["observed_kind"] == "serial"
        assert reader.json()["observed_id"] is None and reader.json()["observed_kind"] is None
        assert SERIAL_B not in reader.text


async def test_a_probe_between_commit_and_release_keeps_the_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A different device is seen right after the commit: the hold follows the database."""
    async with running() as rig:
        await _flag_swap(rig)
        headers = await _admin()
        sink = rig.app.state.printer_runtime._identity_sink
        events = rig.app.state.event_bus.subscribe(f"printer:{rig.printer_id}:state", "t-race")
        original = PrinterAdminService.resolve_identity

        async def resolve_then_probe(self: PrinterAdminService, *a: Any, **kw: Any) -> Any:
            result = await original(self, *a, **kw)
            assert await sink(rig.printer_id, ObservedIdentity(SERIAL_C, None, None)) == "different"
            return result

        with monkeypatch.context() as m:
            m.setattr(PrinterAdminService, "resolve_identity", resolve_then_probe)
            resp = await _resolve(rig, "same_device", headers)

        assert resp.status_code == 200, resp.text
        row = await _identity(rig.printer_id)
        assert row.mismatch_since is not None and row.observed_id == SERIAL_C
        assert rig.app.state.print_queue.is_identity_held(rig.printer_id)
        seen = [data["mismatch"] for data in _identity_events(events)]
        assert False not in seen  # the stream never announces "resolved"


async def test_a_failure_after_the_commit_does_not_leave_a_stuck_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with running() as rig:
        await _flag_swap(rig)
        headers = await _admin()

        async def broken_read(*_a: Any, **_kw: Any) -> Any:
            raise BoomError

        with monkeypatch.context() as m:
            m.setattr(admin_routes, "_read", broken_read)
            with pytest.raises(BoomError):
                await _resolve(rig, "same_device", headers)

        assert (await _identity(rig.printer_id)).mismatch_since is None
        assert not rig.app.state.print_queue.is_identity_held(rig.printer_id)


async def test_a_restricted_admin_key_cannot_resolve_another_printer() -> None:
    async with running() as rig:
        await _seed_calibrations(rig.printer_id, "auto")
        await _flag_swap(rig)
        other = {"X-Label-Hub-Key": await _insert_key(["admin"], [str(uuid4())])}
        own = {"X-Label-Hub-Key": await _insert_key(["admin"], [str(rig.printer_id)])}

        denied = await _resolve(rig, "replaced", other)

        assert denied.status_code == 403, denied.text
        assert denied.json()["detail"]["error_code"] == "printer_not_allowed"
        assert await _calibration_trays(rig.printer_id) == ["auto"]
        assert rig.app.state.print_queue.is_identity_held(rig.printer_id)
        assert (await _resolve(rig, "replaced", own)).status_code == 200


async def test_409_does_not_delete_before_the_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """No mismatch pending: the calibration rows are not even touched."""
    async with running() as rig:
        sink = rig.app.state.printer_runtime._identity_sink
        await sink(rig.printer_id, ObservedIdentity(SERIAL_A, None, None))
        await _seed_calibrations(rig.printer_id, "auto")
        deletes = 0

        def setup(session: Any, m: pytest.MonkeyPatch) -> None:
            original = session.delete

            async def counting(instance: object) -> None:
                nonlocal deletes
                deletes += 1
                await original(instance)

            m.setattr(session, "delete", counting)

        with monkeypatch.context() as m:
            _on_service_session(m, setup)
            resp = await _resolve(rig, "replaced", expected=SERIAL_A)

        assert resp.status_code == 409 and deletes == 0
