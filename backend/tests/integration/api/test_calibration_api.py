"""HTTP tests of the calibration API: scope matrix, printer restriction, errors, the fit."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import app.models  # noqa: F401
import bcrypt
import pytest
from app.calibration.fit import crossing_point
from app.models.api_key import ApiKey
from app.models.printer import Printer
from app.models.printer_tray import PrinterTray
from app.page_render.transform import Deviation, apply_deviation
from app.sheets import type_service as ts
from app.sheets.geometry import Geometry

pytestmark = pytest.mark.asyncio

G48 = Geometry("A4", 21000, 29700, 4570, 2120, 4, 12, 4820, 2120, 2130, 985, None, "rectangle")
BODY = {
    "offset_x_mm": 1.2,
    "offset_y_mm": -0.4,
    "scale_x": 1.001,
    "scale_y": 0.999,
    "rotation_deg": 0.3,
}


def _factory():
    import app.db.engine as _engine_module

    return _engine_module.async_session


async def _key(scopes: list[str], allowed: list[str] | None = None) -> dict[str, str]:
    plaintext = f"lh_pat_{uuid4().hex}"
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    async with _factory()() as s:
        s.add(
            ApiKey(
                name=f"cal-{uuid4().hex[:6]}",
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


async def _printer(backend: str = "ipp") -> UUID:
    async with _factory()() as s:
        p = Printer(
            name=f"p-{uuid4().hex[:6]}", slug=f"p-{uuid4().hex[:6]}", model="m", backend=backend
        )
        s.add(p)
        s.add(PrinterTray(printer_id=p.id, tray_key="auto", label="Auto", is_default=True))
        s.add(PrinterTray(printer_id=p.id, tray_key="off", label="Off", enabled=False))
        await s.commit()
        return p.id


async def _type(key: str = "cal-test", prefix: str = "CAL") -> None:
    async with _factory()() as s:
        await ts.create_type(s, ts.TypeFields(key, prefix, "Acme", [], None, None), G48, actor="t")


def _err(resp: Any) -> dict[str, Any]:
    detail = resp.json()["detail"]
    return detail


async def test_put_get_delete_happy_path(api_client_with_seed):
    c = api_client_with_seed
    admin, reader = await _key(["admin"]), await _key(["read"])
    pid = await _printer()
    put = await c.put(f"/api/printers/{pid}/calibration/auto", json=BODY, headers=admin)
    assert put.status_code == 200, put.text
    assert put.json()["offset_x_mm"] == 1.2 and put.json()["method"] == "manual"
    got = await c.get(f"/api/printers/{pid}/calibration", headers=reader)
    assert got.status_code == 200
    assert [r["tray"] for r in got.json()] == ["auto"]
    assert got.json()[0]["rotation_deg"] == 0.3
    gone = await c.delete(f"/api/printers/{pid}/calibration/auto", headers=admin)
    assert gone.status_code == 204
    again = await c.get(f"/api/printers/{pid}/calibration", headers=reader)
    assert again.json()[0]["method"] is None and again.json()[0]["offset_x_mm"] is None


async def test_put_measured_on(api_client_with_seed):
    c = api_client_with_seed
    admin = await _key(["admin"])
    pid = await _printer()
    await _type()
    ok = await c.put(
        f"/api/printers/{pid}/calibration/auto",
        json={**BODY, "measured_on": {"type_key": "cal-test", "version": 1}},
        headers=admin,
    )
    assert ok.status_code == 200 and ok.json()["measured_on"] == {
        "type_key": "cal-test",
        "version": 1,
    }
    bad = await c.put(
        f"/api/printers/{pid}/calibration/auto",
        json={**BODY, "measured_on": {"type_key": "cal-test", "version": 9}},
        headers=admin,
    )
    assert bad.status_code == 404 and _err(bad)["error_code"] == "sheet_type_version_not_found"


async def test_put_checks_the_path_before_the_body(api_client_with_seed):
    """Same order as fit and page: tray, then the measured_on type, then the ranges."""
    c = api_client_with_seed
    admin = await _key(["admin"])
    pid = await _printer()
    await _type()
    ghost = {"type_key": "no-such-type", "version": 1}
    wild = {**BODY, "offset_x_mm": 10.01}

    async def put(tray: str, body: dict) -> Any:
        return await c.put(f"/api/printers/{pid}/calibration/{tray}", json=body, headers=admin)

    unknown_tray_and_type = await put("nope", {**BODY, "measured_on": ghost})
    assert unknown_tray_and_type.status_code == 422
    assert _err(unknown_tray_and_type)["error_code"] == "tray_unknown"
    unknown_tray_and_range = await put("nope", wild)
    assert unknown_tray_and_range.status_code == 422
    assert _err(unknown_tray_and_range)["error_code"] == "tray_unknown"
    type_and_range = await put("auto", {**wild, "measured_on": ghost})
    assert type_and_range.status_code == 404
    assert _err(type_and_range)["error_code"] == "sheet_type_not_found"
    range_only = await put("auto", {**wild, "measured_on": {"type_key": "cal-test", "version": 1}})
    assert range_only.status_code == 422
    assert _err(range_only)["error_code"] == "calibration_out_of_range"


async def test_put_errors(api_client_with_seed):
    c = api_client_with_seed
    admin = await _key(["admin"])
    pid = await _printer()
    out = await c.put(
        f"/api/printers/{pid}/calibration/auto", json={**BODY, "offset_x_mm": 10.01}, headers=admin
    )
    assert out.status_code == 422
    assert _err(out)["error_code"] == "calibration_out_of_range"
    assert _err(out)["error_detail"]["field"] == "offset_x_mm"
    tray = await c.put(f"/api/printers/{pid}/calibration/nope", json=BODY, headers=admin)
    assert tray.status_code == 422 and _err(tray)["error_code"] == "tray_unknown"
    disabled = await c.put(f"/api/printers/{pid}/calibration/off", json=BODY, headers=admin)
    assert disabled.status_code == 422 and _err(disabled)["error_code"] == "tray_unknown"
    tape = await _printer("brother_ql")
    kind = await c.put(f"/api/printers/{tape}/calibration/auto", json=BODY, headers=admin)
    assert kind.status_code == 409 and _err(kind)["error_code"] == "media_kind_mismatch"
    missing = await c.put(f"/api/printers/{uuid4()}/calibration/auto", json=BODY, headers=admin)
    assert missing.status_code == 404 and _err(missing)["error_code"] == "printer_not_found"
    listing = await c.get(f"/api/printers/{pid}/calibration", headers=admin)
    assert listing.json()[0]["method"] is None  # nothing was stored


async def test_delete_errors(api_client_with_seed):
    c = api_client_with_seed
    admin = await _key(["admin"])
    pid = await _printer()
    tray = await c.delete(f"/api/printers/{pid}/calibration/nope", headers=admin)
    assert tray.status_code == 422 and _err(tray)["error_code"] == "tray_unknown"
    tape = await _printer("brother_ql")
    kind = await c.delete(f"/api/printers/{tape}/calibration/auto", headers=admin)
    assert kind.status_code == 409 and _err(kind)["error_code"] == "media_kind_mismatch"


async def test_scope_matrix(api_client_with_seed):
    c = api_client_with_seed
    reader, printer_key = await _key(["read"]), await _key(["print"])
    admin = await _key(["admin"])
    pid = await _printer()
    await _type()
    fit_body = _fit_body(Deviation(120, -40, 1_001_000, 999_000, 300_000))
    for headers in (reader, printer_key):
        put = await c.put(f"/api/printers/{pid}/calibration/auto", json=BODY, headers=headers)
        assert put.status_code == 403, headers
        delete = await c.delete(f"/api/printers/{pid}/calibration/auto", headers=headers)
        assert delete.status_code == 403
    assert (await c.put(f"/api/printers/{pid}/calibration/auto", json=BODY)).status_code == 401
    assert (
        await c.get(f"/api/printers/{pid}/calibration", headers=printer_key)
    ).status_code == 200  # print implies read
    assert (await c.get(f"/api/printers/{pid}/calibration", headers=reader)).status_code == 200
    assert (await c.get(f"/api/printers/{pid}/calibration", headers=admin)).status_code == 200
    ok = await c.post(f"/api/printers/{pid}/calibration/auto/fit", json=fit_body, headers=reader)
    assert ok.status_code == 200, ok.text
    assert (
        await c.post(f"/api/printers/{pid}/calibration/auto/fit", json=fit_body)
    ).status_code == 401


async def test_printer_restricted_key_gets_403_on_another_printer(api_client_with_seed):
    c = api_client_with_seed
    mine, other = await _printer(), await _printer()
    await _type()
    admin_r = await _key(["admin"], [str(mine)])
    read_r = await _key(["read"], [str(mine)])
    for method, path, kwargs in [
        ("GET", f"/api/printers/{other}/calibration", {}),
        ("PUT", f"/api/printers/{other}/calibration/auto", {"json": BODY}),
        ("DELETE", f"/api/printers/{other}/calibration/auto", {}),
        ("POST", f"/api/printers/{other}/calibration/auto/fit", {"json": _fit_body(Deviation())}),
    ]:
        resp = await c.request(
            method, path, headers=admin_r if method in ("PUT", "DELETE") else read_r, **kwargs
        )
        assert resp.status_code == 403, (method, resp.text)
        assert resp.json()["detail"]["error_code"] == "printer_not_allowed"
    own = await c.put(f"/api/printers/{mine}/calibration/auto", json=BODY, headers=admin_r)
    assert own.status_code == 200


def _fit_body(dev: Deviation, type_key: str = "cal-test") -> dict[str, Any]:
    readings = []
    for col, row in [(1, 1), (3, 1), (1, 11), (3, 11)]:
        qx, qy = crossing_point(G48, col, row)
        px, py = apply_deviation(dev, "A4", (qx, qy))
        readings.append({"col_gap": col, "row_gap": row, "across_mm": px - qx, "down_mm": py - qy})
    return {"type": type_key, "readings": readings}


async def test_fit_returns_values_and_saves_nothing(api_client_with_seed):
    c = api_client_with_seed
    reader = await _key(["read"])
    pid = await _printer()
    await _type()
    resp = await c.post(
        f"/api/printers/{pid}/calibration/auto/fit",
        json=_fit_body(Deviation(120, -40, 1_001_000, 999_000, 300_000)),
        headers=reader,
    )
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["values"]["offset_x_mm"] == pytest.approx(1.2, abs=0.01)
    assert out["values"]["scale_x"] == pytest.approx(1.001, abs=1e-5)
    assert out["values"]["rotation_deg"] == pytest.approx(0.3, abs=0.001)
    assert out["flagged"] == [] and out["out_of_range"] == [] and len(out["residuals_mm"]) == 4
    listing = await c.get(f"/api/printers/{pid}/calibration", headers=reader)
    assert listing.json()[0]["method"] is None


async def test_fit_out_of_range_is_returned_with_names(api_client_with_seed):
    c = api_client_with_seed
    reader = await _key(["read"])
    pid = await _printer()
    await _type()
    resp = await c.post(
        f"/api/printers/{pid}/calibration/auto/fit",
        json=_fit_body(Deviation(1500, 0, 1_000_000, 1_000_000, 0)),
        headers=reader,
    )
    assert resp.status_code == 200
    assert resp.json()["out_of_range"] == ["offset_x_mm"]
    assert resp.json()["values"]["offset_x_mm"] == pytest.approx(15.0, abs=0.01)


async def test_fit_errors(api_client_with_seed):
    c = api_client_with_seed
    reader = await _key(["read"])
    pid = await _printer()
    await _type()
    url = f"/api/printers/{pid}/calibration/auto/fit"
    good = _fit_body(Deviation())
    few = await c.post(url, json={**good, "readings": good["readings"][:2]}, headers=reader)
    assert few.status_code == 422  # request validation: min 3 readings
    line = {**good, "readings": [{**r, "row_gap": 5} for r in good["readings"]][:3]}
    line["readings"] = [{**line["readings"][i], "col_gap": i + 1} for i in range(3)]
    collinear = await c.post(url, json=line, headers=reader)
    assert collinear.status_code == 422 and _err(collinear)["error_code"] == "readings_insufficient"
    unknown_type = await c.post(url, json={**good, "type": "nope"}, headers=reader)
    assert (
        unknown_type.status_code == 404
        and _err(unknown_type)["error_code"] == "sheet_type_not_found"
    )
    bad_version = await c.post(url, json={**good, "version": 9}, headers=reader)
    assert bad_version.status_code == 404
    # the type exists, the version does not: the spec's code, same as the page routes
    assert _err(bad_version)["error_code"] == "sheet_type_version_not_found"
    gap = {**good, "readings": [*good["readings"][:3], {**good["readings"][3], "col_gap": 9}]}
    outside = await c.post(url, json=gap, headers=reader)
    assert outside.status_code == 422
    assert _err(outside)["error_code"] == "invalid_geometry"
    assert _err(outside)["error_detail"]["reading"] == 3
    tray = await c.post(f"/api/printers/{pid}/calibration/off/fit", json=good, headers=reader)
    assert tray.status_code == 422 and _err(tray)["error_code"] == "tray_unknown"
    tape = await _printer("brother_ql")
    kind = await c.post(f"/api/printers/{tape}/calibration/auto/fit", json=good, headers=reader)
    assert kind.status_code == 409 and _err(kind)["error_code"] == "media_kind_mismatch"


async def test_fit_with_explicit_version(api_client_with_seed):
    c = api_client_with_seed
    reader = await _key(["read"])
    pid = await _printer()
    await _type()
    body = {**_fit_body(Deviation(120, -40, 1_001_000, 999_000, 300_000)), "version": 1}
    resp = await c.post(f"/api/printers/{pid}/calibration/auto/fit", json=body, headers=reader)
    assert resp.status_code == 200, resp.text
    assert resp.json()["values"]["offset_y_mm"] == pytest.approx(-0.4, abs=0.01)


async def test_measured_on_is_validated(api_client_with_seed):
    c = api_client_with_seed
    admin = await _key(["admin"])
    pid = await _printer()
    for measured in ({"type_key": "k" * 201, "version": 1}, {"type_key": "k", "version": 0}):
        resp = await c.put(
            f"/api/printers/{pid}/calibration/auto",
            json={**BODY, "measured_on": measured},
            headers=admin,
        )
        assert resp.status_code == 422, measured
