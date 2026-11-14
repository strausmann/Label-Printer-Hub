# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""HTTP tests of the sheet API (spec 15): routes, scopes, error shape, shared cells (Task 8)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import app.models  # noqa: F401
import pytest
from app.models.sheet import Sheet, SheetCell, SheetIdCounter
from sqlalchemy import select

from tests.integration.api.test_sheet_types_api import _body, _factory, _insert_key

pytestmark = pytest.mark.asyncio

PURPOSE = "Grocy · flour 1 kg"


@pytest.fixture
async def admin() -> dict[str, str]:
    return {"X-Label-Hub-Key": await _insert_key(["admin"])}


@pytest.fixture
async def printer() -> dict[str, str]:
    return {"X-Label-Hub-Key": await _insert_key(["print"])}


@pytest.fixture
async def reader() -> dict[str, str]:
    return {"X-Label-Hub-Key": await _insert_key(["read"])}


def _err(resp) -> dict[str, Any]:
    detail = resp.json()["detail"]
    assert set(detail) == {"error_code", "error_message", "error_detail"}, detail
    return detail


async def _type(client, admin, key: str = "acme-t1", prefix: str = "AT1", **extra: Any) -> None:
    resp = await client.post("/api/v1/sheet-types", json=_body(key, prefix, **extra), headers=admin)
    assert resp.status_code == 201, resp.text


async def _sheet(client, headers, type_key: str = "acme-t1", **extra: Any) -> dict[str, Any]:
    body = {"type": type_key, "id_placement": "manual", **extra}
    resp = await client.post("/api/v1/sheets", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _insert_cell(code: str, cell: int, state: str, **kw: Any) -> None:
    async with _factory()() as s:
        sheet = (await s.execute(select(Sheet).where(Sheet.code == code))).scalar_one()
        s.add(SheetCell(sheet_id=sheet.id, cell_no=cell, state=state, **{"source": "hub", **kw}))
        await s.commit()


@pytest.fixture
async def ready(api_client_with_seed, admin):
    """A custom 4 x 12 type (48 cells, prefix AT1)."""
    await _type(api_client_with_seed, admin)
    return api_client_with_seed


# ---------------------------------------------------------------------------
# Happy paths, one per route
# ---------------------------------------------------------------------------


async def test_create_and_get_sheet(ready, printer, reader):
    created = await _sheet(
        ready,
        printer,
        used_cells=[{"cell": 5, "purpose": PURPOSE}, {"cell": 2}],
        note="  second sheet from the box ",
    )
    assert created["code"] == "AT1-0001"
    assert created["type_key"] == "acme-t1"
    assert created["type_label"] == "Acme T-1"
    assert (created["version"], created["total"]) == (1, 48)
    assert (created["used"], created["reserved"], created["unconfirmed"], created["free"]) == (
        2,
        0,
        0,
        46,
    )
    assert created["state"] == "active"
    assert created["id_placement"] == "manual" and created["id_printed"] is False
    assert created["note"] == "second sheet from the box"
    assert (created["label_w"], created["label_h"]) == (45.7, 21.2)
    assert created["geometry"]["cols"] == 4 and created["geometry"]["page_w"] == 210.0
    assert created["discarded_at"] is None
    assert created["last_used_at"] is not None
    assert [c["cell"] for c in created["cells"]] == [2, 5]
    cell5 = created["cells"][1]
    assert cell5["state"] == "used" and cell5["source"] == "manual"
    assert cell5["purpose"] == PURPOSE and cell5["marked_by_hand"] is True
    assert created["cells"][0]["purpose"] == "marked by hand"
    assert cell5["job_id"] is None and cell5["ref"] is None

    got = await ready.get("/api/v1/sheets/AT1-0001", headers=reader)
    assert got.status_code == 200
    assert created["job_id"] is None  # only a `cell` sheet queues an ID-only job
    assert got.json() == {k: v for k, v in created.items() if k != "job_id"}


async def test_create_sheet_defaults_to_margin(ready, printer):
    resp = await ready.post("/api/v1/sheets", json={"type": "acme-t1"}, headers=printer)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id_placement"] == "margin"
    assert body["id_printed"] is False


async def test_create_pins_the_version_and_validates_cells(ready, printer, admin):
    new_geometry = _body()["geometry"] | {"cols": 3}
    resp = await ready.post(
        "/api/v1/sheet-types/acme-t1/versions",
        json={"geometry": new_geometry, "change_note": "three columns"},
        headers=admin,
    )
    assert resp.status_code == 201, resp.text
    pinned = await _sheet(ready, printer, version=1)
    assert (pinned["version"], pinned["total"]) == (1, 48)
    current = await _sheet(ready, printer)
    assert (current["version"], current["total"]) == (2, 36)
    out = await ready.post(
        "/api/v1/sheets",
        json={"type": "acme-t1", "id_placement": "manual", "used_cells": [{"cell": 37}]},
        headers=printer,
    )
    assert out.status_code == 422
    assert _err(out)["error_code"] == "cell_out_of_range"
    assert _err(out)["error_detail"] == {"cells": [37], "max": 36}
    missing = await ready.post(
        "/api/v1/sheets",
        json={"type": "acme-t1", "version": 9, "id_placement": "manual"},
        headers=printer,
    )
    assert missing.status_code == 404
    assert _err(missing)["error_code"] == "sheet_type_version_not_found"


async def test_list_sheets_filters_and_order(ready, printer, reader, admin):
    await _type(ready, admin, "zeta-z9", "ZZ9")
    first = await _sheet(ready, printer, used_cells=[{"cell": n} for n in range(1, 41)])
    second = await _sheet(ready, printer, used_cells=[{"cell": 1}])
    third = await _sheet(ready, printer, used_cells=[{"cell": n} for n in range(1, 49)])
    other = await _sheet(ready, printer, "zeta-z9")
    assert (
        await ready.post(f"/api/v1/sheets/{other['code']}/discard", headers=admin)
    ).status_code == 200

    listing = await ready.get("/api/v1/sheets", headers=reader)
    assert listing.status_code == 200
    rows = listing.json()
    assert [r["code"] for r in rows] == [second["code"], first["code"], third["code"]]
    assert set(rows[0]) == {
        "code", "type_key", "type_label", "version", "label_w", "label_h", "total", "used",
        "reserved", "unconfirmed", "free", "state", "last_used_at",
    }  # fmt: skip
    assert "cells" not in rows[0]

    def codes(resp) -> list[str]:
        assert resp.status_code == 200, resp.text
        return [r["code"] for r in resp.json()]

    assert codes(await ready.get("/api/v1/sheets", params={"state": "full"}, headers=reader)) == [
        third["code"]
    ]
    assert codes(
        await ready.get("/api/v1/sheets", params={"state": "discarded"}, headers=reader)
    ) == [other["code"]]
    assert (
        len(codes(await ready.get("/api/v1/sheets", params={"state": "all"}, headers=reader))) == 4
    )
    # 'fits first' (OC-34): sheets with enough room come before the others, most free first
    fit = codes(await ready.get("/api/v1/sheets", params={"free_at_least": 10}, headers=reader))
    assert fit == [second["code"], first["code"], third["code"]]
    fit = codes(await ready.get("/api/v1/sheets", params={"free_at_least": 9}, headers=reader))
    assert fit[0] == second["code"]
    assert codes(
        await ready.get("/api/v1/sheets", params={"type": "acme-t1", "q": "0002"}, headers=reader)
    ) == [second["code"]]
    unknown = await ready.get("/api/v1/sheets", params={"type": "nope-nope"}, headers=reader)
    assert unknown.status_code == 404
    assert _err(unknown)["error_code"] == "sheet_type_not_found"
    bad = await ready.get("/api/v1/sheets", params={"state": "bogus"}, headers=reader)
    assert bad.status_code == 422 and _err(bad)["error_code"] == "invalid_request"


async def test_next_code_is_a_hint_and_not_a_code_lookup(ready, printer, reader):
    resp = await ready.get("/api/v1/sheets/next-code", params={"type": "acme-t1"}, headers=reader)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"code": "AT1-0001", "hint": "probable"}
    await _sheet(ready, printer)
    again = await ready.get("/api/v1/sheets/next-code", params={"type": "acme-t1"}, headers=reader)
    assert again.json()["code"] == "AT1-0002"
    unknown = await ready.get(
        "/api/v1/sheets/next-code", params={"type": "nope-nope"}, headers=reader
    )
    assert unknown.status_code == 404
    assert _err(unknown)["error_code"] == "sheet_type_not_found"
    assert (await ready.get("/api/v1/sheets/next-code", headers=reader)).status_code == 422


async def test_mark_unmark_resolve_discard_flow(ready, printer, admin):
    sheet = await _sheet(ready, printer)
    code = sheet["code"]
    marked = await ready.post(
        f"/api/v1/sheets/{code}/cells/mark",
        json={"cells": [{"cell": 3, "purpose": PURPOSE}, {"cell": 4}]},
        headers=printer,
    )
    assert marked.status_code == 200, marked.text
    assert (marked.json()["used"], marked.json()["free"]) == (2, 46)
    assert [c["cell"] for c in marked.json()["cells"]] == [3, 4]

    unmarked = await ready.post(
        f"/api/v1/sheets/{code}/cells/unmark", json={"cells": [4]}, headers=printer
    )
    assert unmarked.status_code == 200, unmarked.text
    assert [c["cell"] for c in unmarked.json()["cells"]] == [3]

    await _insert_cell(code, 7, "unconfirmed", job_id=uuid4(), purpose="x", ref="1")
    await _insert_cell(code, 8, "unconfirmed", job_id=uuid4())
    resolved = await ready.post(
        f"/api/v1/sheets/{code}/cells/resolve",
        json={"cells": [7], "outcome": "printed"},
        headers=printer,
    )
    assert resolved.status_code == 200, resolved.text
    by_cell = {c["cell"]: c for c in resolved.json()["cells"]}
    assert by_cell[7]["state"] == "used" and by_cell[8]["state"] == "unconfirmed"
    assert resolved.json()["unconfirmed"] == 1
    freed = await ready.post(
        f"/api/v1/sheets/{code}/cells/resolve",
        json={"cells": [8], "outcome": "not_printed"},
        headers=printer,
    )
    assert 8 not in {c["cell"] for c in freed.json()["cells"]}

    discarded = await ready.post(f"/api/v1/sheets/{code}/discard", headers=admin)
    assert discarded.status_code == 200, discarded.text
    assert discarded.json()["state"] == "discarded"
    assert discarded.json()["discarded_at"] is not None
    again = await ready.post(f"/api/v1/sheets/{code}/discard", headers=admin)
    assert again.status_code == 200
    assert again.json()["discarded_at"] == discarded.json()["discarded_at"]  # idempotent


async def test_sheet_cells_reprint_lookup(ready, printer, reader):
    first = await _sheet(ready, printer)
    second = await _sheet(ready, printer)
    await _insert_cell(first["code"], 5, "used", source="grocy", ref="42", purpose=PURPOSE)
    await _insert_cell(second["code"], 9, "used", source="grocy", ref="42")
    await _insert_cell(second["code"], 10, "used", source="grocy", ref="43")
    resp = await ready.get(
        "/api/v1/sheet-cells", params={"source": "grocy", "ref": "42"}, headers=reader
    )
    assert resp.status_code == 200, resp.text
    hits = resp.json()
    assert {(h["code"], h["cell"]) for h in hits} == {(first["code"], 5), (second["code"], 9)}
    assert set(hits[0]) == {"code", "cell", "state", "purpose", "updated_at"}
    none = await ready.get(
        "/api/v1/sheet-cells", params={"source": "grocy", "ref": "0"}, headers=reader
    )
    assert none.json() == []
    for params in (
        {"source": "Grocy", "ref": "42"},
        {"source": "grocy"},
        {"ref": "42"},
        {"source": "grocy", "ref": ""},
    ):
        resp = await ready.get("/api/v1/sheet-cells", params=params, headers=reader)
        assert resp.status_code == 422 and _err(resp)["error_code"] == "invalid_request", params


# ---------------------------------------------------------------------------
# Shared data, discarded sheets, input checks
# ---------------------------------------------------------------------------


async def test_other_client_sees_same_cells(ready, admin):
    """Acceptance 11 at the data level: a cell marked with key A shows up for key B."""
    key_a = {"X-Label-Hub-Key": await _insert_key(["print"])}
    key_b = {"X-Label-Hub-Key": await _insert_key(["read"])}
    sheet = await _sheet(ready, key_a)
    marked = await ready.post(
        f"/api/v1/sheets/{sheet['code']}/cells/mark",
        json={"cells": [{"cell": 5, "purpose": PURPOSE}]},
        headers=key_a,
    )
    assert marked.status_code == 200
    seen = (await ready.get(f"/api/v1/sheets/{sheet['code']}", headers=key_b)).json()
    assert [(c["cell"], c["purpose"], c["state"]) for c in seen["cells"]] == [(5, PURPOSE, "used")]
    assert seen["free"] == 47


async def test_discarded_lookup_200_unknown_404(ready, printer, reader, admin):
    sheet = await _sheet(ready, printer, used_cells=[{"cell": 1}])
    await ready.post(f"/api/v1/sheets/{sheet['code']}/discard", headers=admin)
    found = await ready.get(f"/api/v1/sheets/{sheet['code']}", headers=reader)
    assert found.status_code == 200
    assert found.json()["state"] == "discarded" and len(found.json()["cells"]) == 1
    unknown = await ready.get("/api/v1/sheets/AT1-0099", headers=reader)
    assert unknown.status_code == 404
    assert _err(unknown)["error_code"] == "sheet_not_found"
    # a discarded sheet takes no more marks
    resp = await ready.post(
        f"/api/v1/sheets/{sheet['code']}/cells/mark", json={"cells": [{"cell": 2}]}, headers=printer
    )
    assert resp.status_code == 409 and _err(resp)["error_code"] == "sheet_discarded"


@pytest.mark.parametrize(
    "code", ["at1-0001", "AT1-01", "AT1-1", "AT1-001", "A-0001", "1AT-0001", "AT1_0001"]
)
async def test_code_pattern_rejects_malformed_codes(ready, reader, code):
    resp = await ready.get(f"/api/v1/sheets/{code}", headers=reader)
    assert resp.status_code == 422, code
    assert _err(resp)["error_code"] == "invalid_request"
    assert _err(resp)["error_detail"] == {"errors": ["path.code"]}


async def test_five_digit_codes_match_the_pattern(ready, reader):
    resp = await ready.get("/api/v1/sheets/AT1-10000", headers=reader)
    assert resp.status_code == 404  # well-formed, just unknown


async def test_purpose_limit_and_plain_text(ready, printer):
    sheet = await _sheet(ready, printer)
    url = f"/api/v1/sheets/{sheet['code']}/cells/mark"
    over = await ready.post(
        url, json={"cells": [{"cell": 1, "purpose": "x" * 121}]}, headers=printer
    )
    assert over.status_code == 422 and _err(over)["error_code"] == "invalid_request"
    assert _err(over)["error_detail"] == {"errors": ["cells.0.purpose"]}
    ok = await ready.post(url, json={"cells": [{"cell": 1, "purpose": "x" * 120}]}, headers=printer)
    assert ok.status_code == 200
    assert len(ok.json()["cells"][0]["purpose"]) == 120
    cleaned = await ready.post(
        url,
        json={"cells": [{"cell": 2, "purpose": "ba\x07d‮text"}, {"cell": 3, "purpose": "\x07"}]},
        headers=printer,
    )
    purposes = {c["cell"]: c["purpose"] for c in cleaned.json()["cells"]}
    assert purposes[2] == "badtext" and purposes[3] == "marked by hand"


async def test_note_that_cleans_to_nothing_is_null(ready, printer):
    sheet = await _sheet(ready, printer, note="\x07 ")
    assert sheet["note"] is None


async def test_request_bodies_are_checked(ready, printer):
    sheet = await _sheet(ready, printer)
    base = f"/api/v1/sheets/{sheet['code']}/cells"
    secret = "SECRETFIELDNAME"
    cases = [
        (f"{base}/mark", {"cells": []}),
        (f"{base}/mark", {"cells": [{"cell": 0}]}),
        (f"{base}/mark", {"cells": [{"cell": 1}] * 401}),
        (f"{base}/mark", {"cells": [{"cell": 1, secret: "x"}]}),
        (f"{base}/unmark", {"cells": []}),
        (f"{base}/unmark", {"cells": ["a"]}),
        (f"{base}/resolve", {"cells": [1], "outcome": "maybe"}),
        (f"{base}/resolve", {"cells": []}),
        ("/api/v1/sheets", {"type": "acme-t1", "id_placement": "cell"}),
        ("/api/v1/sheets", {"type": "ACME", "id_placement": "manual"}),
        ("/api/v1/sheets", {"type": "acme-t1", "id_placement": "manual", "note": "n" * 501}),
        (
            "/api/v1/sheets",
            {"type": "acme-t1", "id_placement": "manual", "used_cells": [{"cell": 1}] * 401},
        ),
        ("/api/v1/sheets", {"type": "acme-t1", "id_placement": "manual", secret: 1}),
    ]
    for url, body in cases:
        resp = await ready.post(url, json=body, headers=printer)
        assert resp.status_code == 422, (url, body)
        assert _err(resp)["error_code"] == "invalid_request", (url, body)
        assert secret not in resp.text


async def test_conflicts_name_the_cells(ready, printer, admin):
    sheet = await _sheet(ready, printer, used_cells=[{"cell": 5}])
    code = sheet["code"]
    taken = await ready.post(
        f"/api/v1/sheets/{code}/cells/mark",
        json={"cells": [{"cell": 5}, {"cell": 6}]},
        headers=printer,
    )
    assert taken.status_code == 409
    assert _err(taken)["error_code"] == "cells_taken"
    assert _err(taken)["error_detail"] == {"cells": [5]}
    after = (await ready.get(f"/api/v1/sheets/{code}", headers=printer)).json()
    assert [c["cell"] for c in after["cells"]] == [5]  # nothing half-written
    out = await ready.post(
        f"/api/v1/sheets/{code}/cells/mark", json={"cells": [{"cell": 49}]}, headers=printer
    )
    assert out.status_code == 422 and _err(out)["error_code"] == "cell_out_of_range"
    assert _err(out)["error_detail"] == {"cells": [49], "max": 48}
    await _insert_cell(code, 9, "used", source="grocy", ref="1")
    hand = await ready.post(
        f"/api/v1/sheets/{code}/cells/unmark", json={"cells": [9]}, headers=printer
    )
    assert hand.status_code == 409 and _err(hand)["error_code"] == "cells_not_marked_by_hand"
    assert _err(hand)["error_detail"] == {"cells": [9]}
    unconf = await ready.post(
        f"/api/v1/sheets/{code}/cells/resolve",
        json={"cells": [5], "outcome": "printed"},
        headers=printer,
    )
    assert unconf.status_code == 409 and _err(unconf)["error_code"] == "cells_not_unconfirmed"
    await _insert_cell(code, 11, "reserved", job_id=uuid4())
    busy = await ready.post(f"/api/v1/sheets/{code}/discard", headers=admin)
    assert busy.status_code == 409 and _err(busy)["error_code"] == "sheet_busy"
    unknown = await ready.post("/api/v1/sheets/AT1-0099/discard", headers=admin)
    assert unknown.status_code == 404 and _err(unknown)["error_code"] == "sheet_not_found"


async def test_create_refuses_unknown_and_archived_types(ready, printer, admin):
    unknown = await ready.post(
        "/api/v1/sheets", json={"type": "nope-nope", "id_placement": "manual"}, headers=printer
    )
    assert unknown.status_code == 404 and _err(unknown)["error_code"] == "sheet_type_not_found"
    await ready.post("/api/v1/sheet-types/acme-t1/archive", headers=admin)
    archived = await ready.post(
        "/api/v1/sheets", json={"type": "acme-t1", "id_placement": "manual"}, headers=printer
    )
    assert archived.status_code == 409 and _err(archived)["error_code"] == "sheet_type_archived"


async def test_validation_errors_of_other_routes_keep_the_default_shape(ready, reader):
    resp = await ready.get("/api/v1/printers/not-a-uuid", headers=reader)
    assert resp.status_code == 422 and isinstance(resp.json()["detail"], list)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

_READS = [
    ("get", "/api/v1/sheets"),
    ("get", "/api/v1/sheets/next-code?type=acme-t1"),
    ("get", "/api/v1/sheets/AT1-0001"),
    ("get", "/api/v1/sheet-cells?source=grocy&ref=1"),
]
_WRITES: list[tuple[str, str, Any]] = [
    ("post", "/api/v1/sheets", {"type": "acme-t1", "id_placement": "manual"}),
    ("post", "/api/v1/sheets/AT1-0001/discard", None),
    ("post", "/api/v1/sheets/AT1-0001/cells/mark", {"cells": [{"cell": 1}]}),
    ("post", "/api/v1/sheets/AT1-0001/cells/unmark", {"cells": [1]}),
    ("post", "/api/v1/sheets/AT1-0001/cells/resolve", {"cells": [1], "outcome": "printed"}),
]


async def test_missing_key_is_401_everywhere(ready):
    for method, path in _READS:
        assert (await ready.request(method, path)).status_code == 401, path
    for method, path, payload in _WRITES:
        assert (await ready.request(method, path, json=payload)).status_code == 401, path


async def test_scope_matrix(ready, printer, reader, admin):
    """Writes need print (OC-11), discard needs admin (#264): one exact status per route."""
    await _sheet(ready, printer)  # AT1-0001, no cell used
    for method, path in _READS:
        resp = await ready.request(method, path, headers=reader)
        assert resp.status_code == 200, (path, resp.text)  # the read scope is enough
    for method, path, payload in _WRITES:
        resp = await ready.request(method, path, json=payload, headers=reader)
        assert resp.status_code == 403, (path, resp.text)
        assert resp.json()["detail"]["error_code"] == "insufficient_scope", path
    expected = {
        "/api/v1/sheets": 201,
        "/api/v1/sheets/AT1-0001/discard": 403,  # admin only
        "/api/v1/sheets/AT1-0001/cells/mark": 200,
        "/api/v1/sheets/AT1-0001/cells/unmark": 200,  # the cell marked just before
        "/api/v1/sheets/AT1-0001/cells/resolve": 409,  # cell 1 is not waiting: the state check
    }
    for method, path, payload in _WRITES:
        resp = await ready.request(method, path, json=payload, headers=printer)
        assert resp.status_code == expected[path], (path, resp.text)
    resolve = await ready.post(_WRITES[4][1], json=_WRITES[4][2], headers=printer)
    assert _err(resolve)["error_code"] == "cells_not_unconfirmed"
    assert (
        await ready.request("post", "/api/v1/sheets", json=_WRITES[0][2], headers=admin)
    ).status_code == 201
    assert (await ready.post("/api/v1/sheets/AT1-0001/discard", headers=admin)).status_code == 200


async def test_discard_requires_admin(ready, printer, admin, monkeypatch):
    """264-04: a print key may not retire a sheet; nothing changes and no event goes out."""
    from app.sheets import sheet_service

    sheet = await _sheet(ready, printer, used_cells=[{"cell": 1}])
    code = sheet["code"]
    seen: list[Any] = []
    real_publish = sheet_service.publish_sheet_updated

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(args)
        return real_publish(*args, **kwargs)

    monkeypatch.setattr(sheet_service, "publish_sheet_updated", spy)
    refused = await ready.post(f"/api/v1/sheets/{code}/discard", headers=printer)
    monkeypatch.setattr(sheet_service, "publish_sheet_updated", real_publish)
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"]["error_code"] == "insufficient_scope"
    assert seen == []
    after = (await ready.get(f"/api/v1/sheets/{code}", headers=printer)).json()
    assert after["state"] == "active" and after["discarded_at"] is None
    async with _factory()() as s:
        row = (await s.execute(select(Sheet).where(Sheet.code == code))).scalar_one()
    assert row.state == "active" and row.discarded_by is None
    done = await ready.post(f"/api/v1/sheets/{code}/discard", headers=admin)
    assert done.status_code == 200 and done.json()["state"] == "discarded"


async def test_restricted_print_key_may_mark_and_resolve(ready, printer):
    """Sheets are shared (OC-37): a printer-restricted print key marks and resolves cells."""
    sheet = await _sheet(ready, printer)
    code = sheet["code"]
    restricted = {
        "X-Label-Hub-Key": await _insert_key(["print"], allowed_printer_ids=[str(uuid4())])
    }
    marked = await ready.post(
        f"/api/v1/sheets/{code}/cells/mark", json={"cells": [{"cell": 1}]}, headers=restricted
    )
    assert marked.status_code == 200, marked.text
    await _insert_cell(code, 7, "unconfirmed", job_id=uuid4(), source="grocy", ref="7")
    resolved = await ready.post(
        f"/api/v1/sheets/{code}/cells/resolve",
        json={"cells": [7], "outcome": "printed"},
        headers=restricted,
    )
    assert resolved.status_code == 200, resolved.text
    assert {c["cell"]: c["state"] for c in resolved.json()["cells"]} == {1: "used", 7: "used"}
    refused = await ready.post(f"/api/v1/sheets/{code}/discard", headers=restricted)
    assert refused.status_code == 403  # discard is admin, restriction or not


async def test_sheet_list_tie_break_numeric(ready, printer, reader):
    """264-05: equal free cells sort by code as a number, so 9999 comes before 10000."""
    async with _factory()() as s:
        s.add(SheetIdCounter(prefix="AT1", next_value=9999))
        await s.commit()
    first = await _sheet(ready, printer)
    second = await _sheet(ready, printer)
    assert (first["code"], second["code"]) == ("AT1-9999", "AT1-10000")
    rows = (await ready.get("/api/v1/sheets", headers=reader)).json()
    assert [r["code"] for r in rows] == ["AT1-9999", "AT1-10000"]


async def test_id_cell_flag(ready, printer, reader):
    """267-06: the hub says which cell is the ID label; another hub-sourced cell is not."""
    sheet = await _sheet(ready, printer, used_cells=[{"cell": 3}])
    code = sheet["code"]
    await _insert_cell(code, 1, "used", source="hub", purpose="Sheet ID")
    await _insert_cell(code, 2, "used", source="hub", purpose="Calibration")
    await _insert_cell(code, 4, "used", source="grocy", purpose="Sheet ID", ref="9")
    cells = (await ready.get(f"/api/v1/sheets/{code}", headers=reader)).json()["cells"]
    assert {c["cell"]: c["is_id_cell"] for c in cells} == {1: True, 2: False, 3: False, 4: False}


async def test_reads_ignore_printer_restriction(ready, printer):
    sheet = await _sheet(ready, printer)
    restricted = {
        "X-Label-Hub-Key": await _insert_key(["print"], allowed_printer_ids=[str(uuid4())])
    }
    assert (
        await ready.get(f"/api/v1/sheets/{sheet['code']}", headers=restricted)
    ).status_code == 200
    marked = await ready.post(
        f"/api/v1/sheets/{sheet['code']}/cells/mark",
        json={"cells": [{"cell": 1}]},
        headers=restricted,
    )
    assert marked.status_code == 200


async def test_openapi_lists_the_sheet_routes(ready):
    schema = (await ready.get("/openapi.json")).json()
    paths = schema["paths"]
    for path, methods in {
        "/api/v1/sheets": {"get", "post"},
        "/api/v1/sheets/next-code": {"get"},
        "/api/v1/sheets/{code}": {"get"},
        "/api/v1/sheets/{code}/discard": {"post"},
        "/api/v1/sheets/{code}/cells/mark": {"post"},
        "/api/v1/sheets/{code}/cells/unmark": {"post"},
        "/api/v1/sheets/{code}/cells/resolve": {"post"},
        "/api/v1/sheet-cells": {"get"},
    }.items():
        assert methods <= set(paths[path]), path
    code_param = next(
        p for p in paths["/api/v1/sheets/{code}"]["get"]["parameters"] if p["name"] == "code"
    )
    assert code_param["schema"]["pattern"] == r"^[A-Z][A-Z0-9]{1,9}-[0-9]{4,}$"


# ---------------------------------------------------------------------------
# Resolve all unconfirmed cells (#282)
# ---------------------------------------------------------------------------


async def _with_unconfirmed(ready, printer, cells=(2, 5)) -> str:
    code = (await _sheet(ready, printer))["code"]
    for n in cells:
        await _insert_cell(code, n, "unconfirmed", source="grocy", job_id=uuid4())
    return code


async def test_resolve_all_route_print_key(ready, printer):
    code = await _with_unconfirmed(ready, printer)
    resp = await ready.post(
        f"/api/v1/sheets/{code}/cells/resolve-all",
        json={"outcome": "printed", "expected_count": 2},
        headers=printer,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["unconfirmed"] == 0
    assert {c["cell"]: c["state"] for c in body["cells"]} == {2: "used", 5: "used"}


async def test_resolve_all_route_restricted_print_key_allowed(ready, printer):
    """Sheets are shared (#264): a printer-restricted print key may settle cells too."""
    code = await _with_unconfirmed(ready, printer)
    restricted = {
        "X-Label-Hub-Key": await _insert_key(["print"], allowed_printer_ids=[str(uuid4())])
    }
    resp = await ready.post(
        f"/api/v1/sheets/{code}/cells/resolve-all",
        json={"outcome": "not_printed"},
        headers=restricted,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["cells"] == []


async def test_resolve_all_route_read_key_403(ready, printer, reader):
    code = await _with_unconfirmed(ready, printer)
    resp = await ready.post(
        f"/api/v1/sheets/{code}/cells/resolve-all", json={"outcome": "printed"}, headers=reader
    )
    assert resp.status_code == 403
    after = await ready.get(f"/api/v1/sheets/{code}", headers=reader)
    assert after.json()["unconfirmed"] == 2


async def test_resolve_all_route_nothing_unconfirmed_409(ready, printer):
    code = (await _sheet(ready, printer))["code"]
    resp = await ready.post(
        f"/api/v1/sheets/{code}/cells/resolve-all", json={"outcome": "printed"}, headers=printer
    )
    assert resp.status_code == 409 and _err(resp)["error_code"] == "no_unconfirmed_cells"


async def test_resolve_all_route_changed_count_409(ready, printer):
    code = await _with_unconfirmed(ready, printer)
    resp = await ready.post(
        f"/api/v1/sheets/{code}/cells/resolve-all",
        json={"outcome": "printed", "expected_count": 5},
        headers=printer,
    )
    assert resp.status_code == 409
    assert _err(resp)["error_code"] == "unconfirmed_count_changed"
    assert _err(resp)["error_detail"] == {"unconfirmed": 2}


@pytest.mark.parametrize(
    "body",
    [{"outcome": "maybe"}, {}, {"outcome": "printed", "expected_count": 0}],
)
async def test_resolve_all_route_bad_body_422(ready, printer, body):
    code = await _with_unconfirmed(ready, printer)
    resp = await ready.post(f"/api/v1/sheets/{code}/cells/resolve-all", json=body, headers=printer)
    assert resp.status_code == 422
    after = await ready.get(f"/api/v1/sheets/{code}", headers=printer)
    assert after.json()["unconfirmed"] == 2
