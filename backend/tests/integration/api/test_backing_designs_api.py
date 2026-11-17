# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""HTTP tests of the backing design API (#350, R-350-4)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.integration.api.test_sheet_types_api import _err, _insert_key

pytestmark = pytest.mark.asyncio

URL = "/api/v1/backing-designs"


def _design(key: str = "my-liner", **extra: Any) -> dict[str, Any]:
    return {
        "key": key,
        "name": "My liner",
        "page_size": "A4",
        "strips": [{"x_mm": 10, "y_mm": 20, "w_mm": 25, "h_mm": 100}],
        **extra,
    }


@pytest.fixture
async def admin() -> dict[str, str]:
    return {"X-Label-Hub-Key": await _insert_key(["admin"])}


@pytest.fixture
async def reader() -> dict[str, str]:
    return {"X-Label-Hub-Key": await _insert_key(["read"])}


@pytest.fixture
async def printer() -> dict[str, str]:
    return {"X-Label-Hub-Key": await _insert_key(["print"])}


async def test_list_is_readable_with_read_scope(api_client_with_seed, reader):
    resp = await api_client_with_seed.get(URL, headers=reader)
    assert resp.status_code == 200, resp.text
    (shipped,) = resp.json()
    assert shipped["key"] == "avery-zweckform-ultragrip"
    assert shipped["origin"] == "seed" and shipped["types_in_use"] == 2


async def test_create_validates_strips_inside_page(api_client_with_seed, admin):
    body = _design(strips=[{"x_mm": 200, "y_mm": 20, "w_mm": 25, "h_mm": 100}])
    resp = await api_client_with_seed.post(URL, json=body, headers=admin)
    assert resp.status_code == 422, resp.text
    assert _err(resp)["error_detail"]["field"] == "strips.0"
    tall = _design(strips=[{"x_mm": 10, "y_mm": 200, "w_mm": 25, "h_mm": 100}])
    assert (await api_client_with_seed.post(URL, json=tall, headers=admin)).status_code == 422
    ok = await api_client_with_seed.post(URL, json=_design(), headers=admin)
    assert ok.status_code == 201, ok.text
    assert ok.json()["origin"] == "custom"
    again = await api_client_with_seed.post(URL, json=_design(), headers=admin)
    assert again.status_code == 409 and _err(again)["error_code"] == "backing_design_exists"


async def test_patch_strips_admin_only(api_client_with_seed, admin, printer):
    await api_client_with_seed.post(URL, json=_design(), headers=admin)
    body = {"strips": [{"x_mm": 30, "y_mm": 20, "w_mm": 22, "h_mm": 62}]}
    refused = await api_client_with_seed.patch(f"{URL}/my-liner", json=body, headers=printer)
    assert refused.status_code == 403, refused.text
    resp = await api_client_with_seed.patch(f"{URL}/my-liner", json=body, headers=admin)
    assert resp.status_code == 200, resp.text
    assert resp.json()["strips"] == [{"x_mm": 30.0, "y_mm": 20.0, "w_mm": 22.0, "h_mm": 62.0}]
    off = {"strips": [{"x_mm": 190, "y_mm": 20, "w_mm": 22, "h_mm": 62}]}
    bad = await api_client_with_seed.patch(f"{URL}/my-liner", json=off, headers=admin)
    assert bad.status_code == 422 and _err(bad)["error_detail"]["field"] == "strips.0"
    missing = await api_client_with_seed.patch(f"{URL}/nope", json=body, headers=admin)
    assert missing.status_code == 404


async def test_delete_in_use_refused(api_client_with_seed, admin, reader):
    resp = await api_client_with_seed.delete(f"{URL}/avery-zweckform-ultragrip", headers=admin)
    assert resp.status_code == 409, resp.text
    assert _err(resp)["error_code"] == "backing_design_in_use"
    (shipped,) = (await api_client_with_seed.get(URL, headers=reader)).json()
    assert shipped["types_in_use"] > 0


async def test_delete_unused(api_client_with_seed, admin, reader):
    await api_client_with_seed.post(URL, json=_design(), headers=admin)
    resp = await api_client_with_seed.delete(f"{URL}/my-liner", headers=admin)
    assert resp.status_code == 204, resp.text
    keys = [d["key"] for d in (await api_client_with_seed.get(URL, headers=reader)).json()]
    assert keys == ["avery-zweckform-ultragrip"]
    assert (await api_client_with_seed.delete(f"{URL}/my-liner", headers=admin)).status_code == 404
