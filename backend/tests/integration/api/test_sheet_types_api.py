"""HTTP tests of the sheet type API (spec 15): routes, scopes, error shape, import limits."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from copy import deepcopy
from typing import Any
from uuid import uuid4

import app.models  # noqa: F401
import bcrypt
import pytest
from app.models.api_key import ApiKey
from app.sheets import sheet_service as ss

pytestmark = pytest.mark.asyncio

GEOMETRY: dict[str, Any] = {
    "page_size": "A4",
    "label_w": 45.7,
    "label_h": 21.2,
    "cols": 4,
    "rows": 12,
    "pitch_x": 48.2,
    "pitch_y": 21.2,
    "margin_top": 21.3,
    "margin_left": 9.85,
    "corner_radius": None,
    "shape": "rectangle",
}


def _factory():
    import app.db.engine as _engine_module

    return _engine_module.async_session


async def _insert_key(scopes: list[str], allowed_printer_ids: list[str] | None = None) -> str:
    plaintext = f"lh_pat_{uuid4().hex}"
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    async with _factory()() as s:
        s.add(
            ApiKey(
                name=f"sheet-types-{uuid4().hex[:6]}",
                key_hash=hashed,
                key_prefix=plaintext[:16],
                scopes=scopes,
                allowed_printer_ids=allowed_printer_ids or [],
                enabled=True,
                rate_limit_per_minute=6000,
            )
        )
        await s.commit()
    return plaintext


@pytest.fixture
async def admin() -> dict[str, str]:
    return {"X-Label-Hub-Key": await _insert_key(["admin"])}


@pytest.fixture
async def reader() -> dict[str, str]:
    return {"X-Label-Hub-Key": await _insert_key(["read"])}


def _body(key: str = "acme-t1", prefix: str = "AT1", **extra: Any) -> dict[str, Any]:
    return {
        "key": key,
        "prefix": prefix,
        "vendor": "Acme",
        "product_codes": ["T-1"],
        "description": "test type",
        "geometry": deepcopy(GEOMETRY),
        **extra,
    }


async def _create(client, admin, key: str = "acme-t1", prefix: str = "AT1", **extra: Any):
    resp = await client.post("/api/sheet-types", json=_body(key, prefix, **extra), headers=admin)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _err(resp) -> dict[str, Any]:
    detail = resp.json()["detail"]
    assert set(detail) == {"error_code", "error_message", "error_detail"}, detail
    return detail


# ---------------------------------------------------------------------------
# Happy paths, one per route
# ---------------------------------------------------------------------------


async def test_create_returns_type_with_current_version(api_client_with_seed, admin):
    created = await _create(api_client_with_seed, admin)
    assert created["key"] == "acme-t1"
    assert created["current_version"] == 1
    assert created["origin"] == "custom"
    assert created["geometry"]["label_w"] == 45.7
    assert created["geometry"]["page_w"] == 210.0
    assert created["sheets_in_use"] == 0
    assert created["allow_qr"] is True  # OC-28: shorter side 21.2 mm
    assert created["hints"] == []
    assert created["archived_at"] is None


async def test_list_and_get_and_filters(api_client_with_seed, admin, reader):
    await _create(api_client_with_seed, admin, "acme-t1", "AT1")
    other = _body("zeta-z9", "ZZ9", vendor="Zeta", description="small dots")
    other["geometry"].update(label_w=10, label_h=10, cols=10, rows=20, pitch_x=15, pitch_y=12)
    other["geometry"].update(shape="round", margin_left=10, margin_top=10)
    resp = await api_client_with_seed.post("/api/sheet-types", json=other, headers=admin)
    assert resp.status_code == 201, resp.text
    listing = await api_client_with_seed.get("/api/sheet-types", headers=reader)
    assert listing.status_code == 200
    keys = [t["key"] for t in listing.json()]
    assert {"acme-t1", "zeta-z9"} <= set(keys)
    assert len(keys) > 2  # the seed types are listed too
    assert keys == sorted(keys)
    by_vendor = await api_client_with_seed.get(
        "/api/sheet-types", params={"vendor": "Zeta"}, headers=reader
    )
    assert [t["key"] for t in by_vendor.json()] == ["zeta-z9"]
    by_q = await api_client_with_seed.get("/api/sheet-types", params={"q": "acme"}, headers=reader)
    assert [t["key"] for t in by_q.json()] == ["acme-t1"]
    by_size = await api_client_with_seed.get(
        "/api/sheet-types", params={"w": 10.2, "h": 9.8}, headers=reader
    )
    assert "zeta-z9" in [t["key"] for t in by_size.json()]
    assert "acme-t1" not in [t["key"] for t in by_size.json()]
    detail = await api_client_with_seed.get("/api/sheet-types/acme-t1", headers=reader)
    assert detail.status_code == 200
    body = detail.json()
    assert body["key"] == "acme-t1"
    assert [v["version"] for v in body["versions"]] == [1]
    version = body["versions"][0]
    assert version["sheets"] == 0
    assert len(version["geometry_hash"]) > 10
    assert version["change_note"] is None or isinstance(version["change_note"], str)


async def test_get_version(api_client_with_seed, admin, reader):
    await _create(api_client_with_seed, admin)
    resp = await api_client_with_seed.get("/api/sheet-types/acme-t1/versions/1", headers=reader)
    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == 1
    assert resp.json()["geometry"]["cols"] == 4
    missing = await api_client_with_seed.get("/api/sheet-types/acme-t1/versions/9", headers=reader)
    assert missing.status_code == 404
    assert _err(missing)["error_code"] == "sheet_type_not_found"


async def test_patch_changes_only_sent_fields(api_client_with_seed, admin):
    await _create(api_client_with_seed, admin)
    resp = await api_client_with_seed.patch(
        "/api/sheet-types/acme-t1", json={"vendor": "Acme Corp"}, headers=admin
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["vendor"] == "Acme Corp"
    assert body["description"] == "test type"  # omitted: untouched
    assert body["product_codes"] == ["T-1"]
    assert body["allow_qr"] is True
    assert body["current_version"] == 1


async def test_patch_null_clears_nullable_field(api_client_with_seed, admin):
    await _create(api_client_with_seed, admin)
    resp = await api_client_with_seed.patch(
        "/api/sheet-types/acme-t1", json={"description": None}, headers=admin
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["description"] is None
    assert resp.json()["vendor"] == "Acme"


@pytest.mark.parametrize("field", ["prefix", "allow_qr", "verified", "product_codes"])
async def test_patch_null_for_non_nullable_is_422(api_client_with_seed, admin, field):
    await _create(api_client_with_seed, admin)
    resp = await api_client_with_seed.patch(
        "/api/sheet-types/acme-t1", json={field: None}, headers=admin
    )
    assert resp.status_code == 422, resp.text
    again = await api_client_with_seed.get("/api/sheet-types/acme-t1", headers=admin)
    assert again.json()["prefix"] == "AT1"
    assert again.json()["product_codes"] == ["T-1"]


async def test_patch_rejects_geometry_and_unknown_fields(api_client_with_seed, admin):
    await _create(api_client_with_seed, admin)
    for payload in ({"geometry": GEOMETRY}, {"key": "other-key"}, {"origin": "seed"}):
        resp = await api_client_with_seed.patch(
            "/api/sheet-types/acme-t1", json=payload, headers=admin
        )
        assert resp.status_code == 422, resp.text


async def test_patch_prefix_while_unused(api_client_with_seed, admin):
    await _create(api_client_with_seed, admin)
    resp = await api_client_with_seed.patch(
        "/api/sheet-types/acme-t1", json={"prefix": "NEWP"}, headers=admin
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["prefix"] == "NEWP"


async def test_patch_prefix_locked_when_sheets_exist(api_client_with_seed, admin):
    await _create(api_client_with_seed, admin)
    async with _factory()() as s:
        await ss.create_sheet(
            s,
            type_key="acme-t1",
            version=None,
            id_placement="manual",
            used_cells=[],
            note=None,
            actor="test",
        )
    resp = await api_client_with_seed.patch(
        "/api/sheet-types/acme-t1", json={"prefix": "NEWP"}, headers=admin
    )
    assert resp.status_code == 409
    err = _err(resp)
    assert err["error_code"] == "prefix_taken"
    assert err["error_detail"] == {"reason": "sheets_exist"}
    detail = await api_client_with_seed.get("/api/sheet-types/acme-t1", headers=admin)
    assert detail.json()["sheets_in_use"] == 1
    assert detail.json()["versions"][0]["sheets"] == 1


async def test_patch_source_url_must_be_http(api_client_with_seed, admin):
    await _create(api_client_with_seed, admin)
    resp = await api_client_with_seed.patch(
        "/api/sheet-types/acme-t1", json={"source_url": "javascript:alert(1)"}, headers=admin
    )
    assert resp.status_code == 422
    ok = await api_client_with_seed.patch(
        "/api/sheet-types/acme-t1", json={"source_url": "https://example.com/x"}, headers=admin
    )
    assert ok.status_code == 200


async def test_new_version(api_client_with_seed, admin):
    await _create(api_client_with_seed, admin)
    geometry = deepcopy(GEOMETRY)
    geometry["cols"] = 3
    resp = await api_client_with_seed.post(
        "/api/sheet-types/acme-t1/versions",
        json={"geometry": geometry, "change_note": "fewer columns"},
        headers=admin,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["version"] == 2
    assert resp.json()["change_note"] == "fewer columns"
    detail = await api_client_with_seed.get("/api/sheet-types/acme-t1", headers=admin)
    assert detail.json()["current_version"] == 2
    assert [v["version"] for v in detail.json()["versions"]] == [1, 2]


async def test_new_version_requires_change_note_and_a_change(api_client_with_seed, admin):
    await _create(api_client_with_seed, admin)
    empty = await api_client_with_seed.post(
        "/api/sheet-types/acme-t1/versions",
        json={"geometry": GEOMETRY, "change_note": ""},
        headers=admin,
    )
    assert empty.status_code == 422
    unchanged = await api_client_with_seed.post(
        "/api/sheet-types/acme-t1/versions",
        json={"geometry": GEOMETRY, "change_note": "nothing"},
        headers=admin,
    )
    assert unchanged.status_code == 422
    assert _err(unchanged)["error_code"] == "invalid_geometry"


async def test_archive_and_unarchive(api_client_with_seed, admin, reader):
    await _create(api_client_with_seed, admin)
    archived = await api_client_with_seed.post("/api/sheet-types/acme-t1/archive", headers=admin)
    assert archived.status_code == 200, archived.text
    assert archived.json()["archived_at"] is not None
    hidden = await api_client_with_seed.get("/api/sheet-types", headers=reader)
    assert "acme-t1" not in [t["key"] for t in hidden.json()]
    shown = await api_client_with_seed.get(
        "/api/sheet-types", params={"include_archived": "true"}, headers=reader
    )
    assert "acme-t1" in [t["key"] for t in shown.json()]
    restored = await api_client_with_seed.post("/api/sheet-types/acme-t1/unarchive", headers=admin)
    assert restored.status_code == 200
    assert restored.json()["archived_at"] is None


async def test_delete_custom_type_without_sheets(api_client_with_seed, admin):
    await _create(api_client_with_seed, admin)
    resp = await api_client_with_seed.delete("/api/sheet-types/acme-t1", headers=admin)
    assert resp.status_code == 204, resp.text
    gone = await api_client_with_seed.get("/api/sheet-types/acme-t1", headers=admin)
    assert gone.status_code == 404


async def test_delete_type_with_sheets_is_type_in_use(api_client_with_seed, admin):
    await _create(api_client_with_seed, admin)
    async with _factory()() as s:
        await ss.create_sheet(
            s,
            type_key="acme-t1",
            version=None,
            id_placement="manual",
            used_cells=[],
            note=None,
            actor="test",
        )
    resp = await api_client_with_seed.delete("/api/sheet-types/acme-t1", headers=admin)
    assert resp.status_code == 409
    err = _err(resp)
    assert err["error_code"] == "type_in_use"
    assert err["error_detail"] == {"reason": "has_sheets"}


async def test_delete_imported_type_is_type_in_use(api_client_with_seed, admin):
    await _create(api_client_with_seed, admin)
    doc = (await api_client_with_seed.get("/api/sheet-types/acme-t1/export", headers=admin)).json()
    await api_client_with_seed.delete("/api/sheet-types/acme-t1", headers=admin)
    imported = await api_client_with_seed.post("/api/sheet-types/import", json=doc, headers=admin)
    assert imported.status_code == 201, imported.text
    resp = await api_client_with_seed.delete("/api/sheet-types/acme-t1", headers=admin)
    assert resp.status_code == 409
    assert _err(resp)["error_detail"] == {"reason": "imported_type"}


# ---------------------------------------------------------------------------
# Export and import
# ---------------------------------------------------------------------------


async def test_export_document_and_headers(api_client_with_seed, admin, reader):
    await _create(api_client_with_seed, admin)
    resp = await api_client_with_seed.get("/api/sheet-types/acme-t1/export", headers=reader)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.headers["content-disposition"] == 'attachment; filename="acme-t1-v1.json"'
    doc = resp.json()
    assert doc["format"] == "label-printer-hub.sheet-type"
    assert doc["format_version"] == 1
    assert doc["type"]["key"] == "acme-t1"
    assert doc["version"]["version"] == 1
    missing = await api_client_with_seed.get(
        "/api/sheet-types/acme-t1/export", params={"version": 7}, headers=reader
    )
    assert missing.status_code == 404


async def test_export_import_roundtrip_over_http(api_client_with_seed, admin):
    await _create(api_client_with_seed, admin)
    original = (await api_client_with_seed.get("/api/sheet-types/acme-t1", headers=admin)).json()
    exported = await api_client_with_seed.get("/api/sheet-types/acme-t1/export", headers=admin)
    doc = exported.json()
    # Same key and geometry on the same hub: nothing changes.
    same = await api_client_with_seed.post("/api/sheet-types/import", json=doc, headers=admin)
    assert same.status_code == 200, same.text
    assert same.json() == {"outcome": "unchanged", "key": "acme-t1", "version": 1}
    # Remove it, import into the empty hub: created as imported, never verified.
    assert (
        await api_client_with_seed.delete("/api/sheet-types/acme-t1", headers=admin)
    ).status_code == 204
    created = await api_client_with_seed.post("/api/sheet-types/import", json=doc, headers=admin)
    assert created.status_code == 201, created.text
    assert created.json() == {"outcome": "created", "key": "acme-t1", "version": 1}
    again = (await api_client_with_seed.get("/api/sheet-types/acme-t1", headers=admin)).json()
    assert again["origin"] == "imported"
    assert again["verified"] is False
    assert again["geometry"] == original["geometry"]
    assert again["prefix"] == original["prefix"]


async def test_import_modes(api_client_with_seed, admin):
    await _create(api_client_with_seed, admin)
    doc = (await api_client_with_seed.get("/api/sheet-types/acme-t1/export", headers=admin)).json()
    doc["version"]["geometry"]["cols"] = 3
    strict = await api_client_with_seed.post("/api/sheet-types/import", json=doc, headers=admin)
    assert strict.status_code == 409
    assert _err(strict)["error_code"] == "type_exists"
    newver = await api_client_with_seed.post(
        "/api/sheet-types/import", params={"mode": "new_version"}, json=doc, headers=admin
    )
    assert newver.status_code == 201, newver.text
    assert newver.json() == {"outcome": "version_added", "key": "acme-t1", "version": 2}
    doc["version"]["geometry"]["cols"] = 2
    taken = await api_client_with_seed.post(
        "/api/sheet-types/import",
        params={"mode": "as_new_key", "new_key": "acme-copy"},
        json=doc,
        headers=admin,
    )
    assert taken.status_code == 409
    assert _err(taken)["error_code"] == "prefix_taken"
    copy = await api_client_with_seed.post(
        "/api/sheet-types/import",
        params={"mode": "as_new_key", "new_key": "acme-copy", "new_prefix": "ACP"},
        json=doc,
        headers=admin,
    )
    assert copy.status_code == 201, copy.text
    assert copy.json() == {"outcome": "created_as_new_key", "key": "acme-copy", "version": 1}


async def test_import_new_key_outside_as_new_key_mode_is_invalid(api_client_with_seed, admin):
    await _create(api_client_with_seed, admin)
    doc = (await api_client_with_seed.get("/api/sheet-types/acme-t1/export", headers=admin)).json()
    resp = await api_client_with_seed.post(
        "/api/sheet-types/import", params={"new_key": "acme-copy"}, json=doc, headers=admin
    )
    assert resp.status_code == 422
    assert _err(resp)["error_code"] == "invalid_import"


async def test_import_unknown_mode_is_422(api_client_with_seed, admin):
    resp = await api_client_with_seed.post(
        "/api/sheet-types/import", params={"mode": "overwrite"}, content=b"{}", headers=admin
    )
    assert resp.status_code == 422


async def test_import_invalid_documents(api_client_with_seed, admin):
    for raw in (b"not json", b"[]", b'{"format": "x"}', b"{}", b'{"a": NaN}'):
        resp = await api_client_with_seed.post(
            "/api/sheet-types/import", content=raw, headers=admin
        )
        assert resp.status_code == 422, (raw, resp.text)
        err = _err(resp)
        assert err["error_code"] == "invalid_import"
        assert "errors" in err["error_detail"]


async def test_import_error_does_not_echo_input(api_client_with_seed, admin):
    await _create(api_client_with_seed, admin)
    doc = (await api_client_with_seed.get("/api/sheet-types/acme-t1/export", headers=admin)).json()
    doc["type"]["SECRETFIELDNAME"] = "SECRETVALUE"
    resp = await api_client_with_seed.post("/api/sheet-types/import", json=doc, headers=admin)
    assert resp.status_code == 422
    assert "SECRET" not in resp.text


async def test_import_too_large_with_content_length(api_client_with_seed, admin):
    resp = await api_client_with_seed.post(
        "/api/sheet-types/import", content=b"x" * 70_000, headers=admin
    )
    assert resp.status_code == 413
    assert _err(resp)["error_code"] == "import_too_large"


async def test_import_exactly_at_limit_is_parsed_not_refused(api_client_with_seed, admin):
    resp = await api_client_with_seed.post(
        "/api/sheet-types/import", content=b" " * 65_536, headers=admin
    )
    assert resp.status_code == 422  # too large would be 413
    assert _err(resp)["error_code"] == "invalid_import"


async def test_import_streaming_limit(api_client_with_seed, admin):
    """No Content-Length (chunked): the route stops reading just past 64 KB."""
    chunk = b"x" * 1000
    pulled = 0

    async def body() -> AsyncIterator[bytes]:
        nonlocal pulled
        for _ in range(70):
            pulled += 1
            yield chunk

    resp = await api_client_with_seed.post("/api/sheet-types/import", content=body(), headers=admin)
    assert resp.status_code == 413, resp.text
    assert _err(resp)["error_code"] == "import_too_large"
    assert pulled <= 66, pulled  # 65 537 bytes are 66 chunks of 1000; nothing beyond is read


async def test_import_content_length_refused_without_reading(api_client_with_seed, admin):
    pulled = 0

    async def body() -> AsyncIterator[bytes]:
        nonlocal pulled
        for _ in range(70):
            pulled += 1
            yield b"x" * 1000

    resp = await api_client_with_seed.post(
        "/api/sheet-types/import",
        content=body(),
        headers={**admin, "Content-Length": "70000"},
    )
    assert resp.status_code == 413, resp.text
    assert pulled <= 1, pulled


async def test_import_route_documents_request_body(api_client_with_seed):
    schema = (await api_client_with_seed.get("/openapi.json")).json()
    op = schema["paths"]["/api/sheet-types/import"]["post"]
    content = op["requestBody"]["content"]["application/json"]
    assert content["schema"] == {"$ref": "#/components/schemas/ExportDoc"}
    assert op["requestBody"]["required"] is True
    assert "ExportDoc" in schema["components"]["schemas"]


async def test_openapi_lists_sheet_type_routes(api_client_with_seed):
    schema = (await api_client_with_seed.get("/openapi.json")).json()
    expected = {
        ("get", "/api/sheet-types"),
        ("post", "/api/sheet-types"),
        ("post", "/api/sheet-types/import"),
        ("get", "/api/sheet-types/{key}"),
        ("patch", "/api/sheet-types/{key}"),
        ("delete", "/api/sheet-types/{key}"),
        ("get", "/api/sheet-types/{key}/versions/{n}"),
        ("post", "/api/sheet-types/{key}/versions"),
        ("post", "/api/sheet-types/{key}/archive"),
        ("post", "/api/sheet-types/{key}/unarchive"),
        ("get", "/api/sheet-types/{key}/export"),
    }
    present = {
        (method, path)
        for path, ops in schema["paths"].items()
        if path.startswith("/api/sheet-types")
        for method in ops
    }
    assert present == expected


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


async def test_unknown_type_is_404_on_every_keyed_route(api_client_with_seed, admin):
    calls = [
        ("get", "/api/sheet-types/nope-x", None),
        ("patch", "/api/sheet-types/nope-x", {"vendor": "v"}),
        ("post", "/api/sheet-types/nope-x/versions", {"geometry": GEOMETRY, "change_note": "n"}),
        ("post", "/api/sheet-types/nope-x/archive", None),
        ("post", "/api/sheet-types/nope-x/unarchive", None),
        ("delete", "/api/sheet-types/nope-x", None),
        ("get", "/api/sheet-types/nope-x/export", None),
        ("get", "/api/sheet-types/nope-x/versions/1", None),
    ]
    for method, path, payload in calls:
        resp = await api_client_with_seed.request(method, path, json=payload, headers=admin)
        assert resp.status_code == 404, (method, path, resp.text)
        assert _err(resp)["error_code"] == "sheet_type_not_found"


async def test_create_conflicts(api_client_with_seed, admin):
    await _create(api_client_with_seed, admin)
    same_key = await api_client_with_seed.post(
        "/api/sheet-types", json=_body("acme-t1", "OTHER"), headers=admin
    )
    assert same_key.status_code == 409
    assert _err(same_key)["error_code"] == "type_exists"
    same_prefix = await api_client_with_seed.post(
        "/api/sheet-types", json=_body("acme-t2", "AT1"), headers=admin
    )
    assert same_prefix.status_code == 409
    assert _err(same_prefix)["error_code"] == "prefix_taken"


async def test_create_invalid_geometry_names_the_field(api_client_with_seed, admin):
    body = _body()
    body["geometry"]["label_w"] = 45.123
    resp = await api_client_with_seed.post("/api/sheet-types", json=body, headers=admin)
    assert resp.status_code == 422, resp.text
    err = _err(resp)
    assert err["error_code"] == "invalid_geometry"
    assert err["error_detail"]["field"] == "label_w"
    assert "45.123" not in resp.text


async def test_create_invalid_key_and_prefix(api_client_with_seed, admin):
    for key, prefix in (("Bad Key", "AT1"), ("acme-t1", "lower")):
        resp = await api_client_with_seed.post(
            "/api/sheet-types", json=_body(key, prefix), headers=admin
        )
        assert resp.status_code == 422, resp.text
        assert "Bad Key" not in resp.text and "lower" not in resp.text


async def test_create_with_geometry_that_does_not_fit(api_client_with_seed, admin):
    body = _body()
    body["geometry"]["cols"] = 20  # runs off the page
    resp = await api_client_with_seed.post("/api/sheet-types", json=body, headers=admin)
    assert resp.status_code == 422
    assert _err(resp)["error_code"] == "invalid_geometry"


async def test_validation_error_does_not_echo_input(api_client_with_seed, admin):
    body = _body()
    body["SECRETFIELDNAME"] = "SECRETVALUE"
    resp = await api_client_with_seed.post("/api/sheet-types", json=body, headers=admin)
    assert resp.status_code == 422
    assert "SECRET" not in resp.text
    assert _err(resp)["error_code"] == "invalid_request"


async def test_validation_error_elsewhere_keeps_default_shape(api_client_with_seed, admin):
    resp = await api_client_with_seed.get("/api/printers/not-a-uuid", headers=admin)
    assert resp.status_code == 422
    assert isinstance(resp.json()["detail"], list)  # FastAPI default, untouched


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

_READ_ROUTES = [
    ("get", "/api/sheet-types"),
    ("get", "/api/sheet-types/acme-t1"),
    ("get", "/api/sheet-types/acme-t1/versions/1"),
    ("get", "/api/sheet-types/acme-t1/export"),
]


def _write_calls(doc: dict[str, Any]) -> list[tuple[str, str, Any]]:
    new_geometry = deepcopy(GEOMETRY)
    new_geometry["cols"] = 3
    return [
        ("post", "/api/sheet-types", _body("acme-t9", "AT9")),
        ("patch", "/api/sheet-types/acme-t1", {"vendor": "x"}),
        (
            "post",
            "/api/sheet-types/acme-t1/versions",
            {"geometry": new_geometry, "change_note": "n"},
        ),
        ("post", "/api/sheet-types/acme-t1/archive", None),
        ("post", "/api/sheet-types/acme-t1/unarchive", None),
        ("post", "/api/sheet-types/import", doc),
        ("delete", "/api/sheet-types/acme-t1", None),
    ]


async def test_missing_key_is_401_everywhere(api_client_with_seed):
    for method, path in _READ_ROUTES:
        assert (await api_client_with_seed.request(method, path)).status_code == 401, path
    for method, path, payload in _write_calls({}):
        resp = await api_client_with_seed.request(method, path, json=payload)
        assert resp.status_code == 401, (method, path)


@pytest.mark.parametrize("scope", ["read", "print"])
async def test_non_admin_keys_cannot_write(api_client_with_seed, admin, scope):
    await _create(api_client_with_seed, admin)
    doc = (await api_client_with_seed.get("/api/sheet-types/acme-t1/export", headers=admin)).json()
    headers = {"X-Label-Hub-Key": await _insert_key([scope])}
    for method, path, payload in _write_calls(doc):
        resp = await api_client_with_seed.request(method, path, json=payload, headers=headers)
        assert resp.status_code == 403, (method, path, resp.text)
    assert (
        await api_client_with_seed.get("/api/sheet-types/acme-t1", headers=admin)
    ).status_code == 200


async def test_admin_key_may_write(api_client_with_seed, admin):
    await _create(api_client_with_seed, admin)
    doc = (await api_client_with_seed.get("/api/sheet-types/acme-t1/export", headers=admin)).json()
    for method, path, payload in _write_calls(doc):
        resp = await api_client_with_seed.request(method, path, json=payload, headers=admin)
        assert 200 <= resp.status_code < 300, (method, path, resp.text)


async def test_reads_ignore_printer_restriction(api_client_with_seed, admin):
    """OC-37: a read key that is limited to one printer still reads sheet types."""
    await _create(api_client_with_seed, admin)
    headers = {"X-Label-Hub-Key": await _insert_key(["read"], [str(uuid4())])}
    for method, path in _READ_ROUTES:
        resp = await api_client_with_seed.request(method, path, headers=headers)
        assert resp.status_code == 200, (path, resp.text)


async def test_export_survives_json_loads(api_client_with_seed, admin):
    await _create(api_client_with_seed, admin)
    resp = await api_client_with_seed.get("/api/sheet-types/acme-t1/export", headers=admin)
    assert json.loads(resp.content)["type"]["prefix"] == "AT1"


# ---------------------------------------------------------------------------
# Parked minors of Task 7
# ---------------------------------------------------------------------------


async def test_import_with_non_numeric_content_length_is_read_by_streaming(
    api_client_with_seed, admin
):
    """A declared length that is no number is ignored; the streaming limit still applies."""
    await _create(api_client_with_seed, admin)
    doc = (await api_client_with_seed.get("/api/sheet-types/acme-t1/export", headers=admin)).json()
    doc["type"]["key"], doc["type"]["prefix"] = "acme-t2", "AT2"
    doc["type"]["product_codes"] = ["T-2"]
    doc["version"]["geometry"]["cols"] = 3
    resp = await api_client_with_seed.post(
        "/api/sheet-types/import",
        content=json.dumps(doc).encode(),
        headers={**admin, "Content-Length": "abc", "Content-Type": "application/json"},
    )
    assert resp.status_code == 201, resp.text
    too_big = await api_client_with_seed.post(
        "/api/sheet-types/import",
        content=b"x" * 70_000,
        headers={**admin, "Content-Length": "abc"},
    )
    assert too_big.status_code == 413, too_big.text
    assert _err(too_big)["error_code"] == "import_too_large"


async def test_discarded_sheet_counts_in_sheets_in_use(api_client_with_seed, admin):
    await _create(api_client_with_seed, admin)
    async with _factory()() as s:
        sheet = await ss.create_sheet(
            s,
            type_key="acme-t1",
            version=None,
            id_placement="manual",
            used_cells=[],
            note=None,
            actor="test",
        )
        await ss.discard_sheet(s, sheet.code, actor="test")
    detail = await api_client_with_seed.get("/api/sheet-types/acme-t1", headers=admin)
    assert detail.json()["sheets_in_use"] == 1
    assert detail.json()["versions"][0]["sheets"] == 1


async def test_create_rejects_non_http_source_url(api_client_with_seed, admin):
    resp = await api_client_with_seed.post(
        "/api/sheet-types", json=_body(source_url="javascript:alert(1)"), headers=admin
    )
    assert resp.status_code == 422
    assert _err(resp)["error_code"] == "invalid_request"
