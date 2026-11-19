# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""An admin key acts on every printer and refuses a printer list (#283).

All keys below are obviously fake test values. Legacy rows (scope ``admin`` together with a
printer list) are inserted directly, the way an older database holds them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import app.models  # noqa: F401
import bcrypt
import pytest
import pytest_asyncio
from app.config import get_settings
from app.models.api_key import ApiKey
from app.models.job import Job
from app.models.printer import Printer
from app.repositories import printers as printers_repo
from httpx import ASGITransport, AsyncClient

from tests.integration.api.test_sheet_types_api import _factory

pytestmark = pytest.mark.asyncio

_BODY = {
    "content_type": "qr_two_lines",
    "data": {"title": "T", "primary_id": "ID-1", "qr_payload": "https://e.invalid"},
}
_ERROR = {
    "error_code": "admin_key_not_restrictable",
    "error_message": "A key with the admin scope cannot be restricted to printers.",
}


async def _insert_key(scopes: list[str], allowed: list[str] | None = None) -> tuple[str, UUID]:
    plaintext = f"lh_pat_{uuid4().hex}"
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    async with _factory()() as s:
        key = ApiKey(
            name=f"t3-{uuid4().hex[:6]}",
            key_hash=hashed,
            key_prefix=plaintext[:16],
            scopes=scopes,
            allowed_printer_ids=allowed or [],
            enabled=True,
            rate_limit_per_minute=6000,
        )
        s.add(key)
        await s.commit()
        return plaintext, key.id


@pytest_asyncio.fixture
async def hub() -> AsyncIterator[dict[str, Any]]:
    from app.integrations import IntegrationRegistry, _discover_plugins  # type: ignore[attr-defined]
    from app.main import create_app

    if not IntegrationRegistry.names():
        _discover_plugins()
    get_settings.cache_clear()
    async with _factory()() as s:
        a = await printers_repo.create(
            s, Printer(name="Tape A", slug="tape-a", model="PT-P750W", backend="mock")
        )
        b = await printers_repo.create(
            s, Printer(name="Tape B", slug="tape-b", model="PT-P750W", backend="mock")
        )
        ids = (str(a.id), b.id)
    app = create_app()
    inner = app._app
    async with (
        inner.router.lifespan_context(inner),
        AsyncClient(transport=ASGITransport(app=inner), base_url="http://t") as c,
    ):
        yield {"client": c, "app": inner, "a": ids[0], "b": ids[1]}
    get_settings.cache_clear()


async def _admin() -> dict[str, str]:
    plaintext, _ = await _insert_key(["admin"])
    return {"X-Label-Hub-Key": plaintext}


async def _legacy(hub: dict[str, Any]) -> dict[str, str]:
    """An admin key restricted to printer A, as an old database holds it."""
    plaintext, _ = await _insert_key(["admin"], [hub["a"]])
    return {"X-Label-Hub-Key": plaintext}


def _create_body(scopes: list[str], printers: list[str]) -> dict[str, Any]:
    return {"name": f"k-{uuid4().hex[:6]}", "scopes": scopes, "allowed_printer_ids": printers}


# --- create ----------------------------------------------------------------


async def test_create_admin_key_with_printers_is_422(hub: dict[str, Any]) -> None:
    resp = await hub["client"].post(
        "/api/v1/admin/api-keys",
        json=_create_body(["admin"], [hub["a"]]),
        headers=await _admin(),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == _ERROR


async def test_create_admin_key_without_printers_is_201(hub: dict[str, Any]) -> None:
    resp = await hub["client"].post(
        "/api/v1/admin/api-keys", json=_create_body(["admin"], []), headers=await _admin()
    )
    assert resp.status_code == 201, resp.text


async def test_create_print_key_with_printers_still_works(hub: dict[str, Any]) -> None:
    resp = await hub["client"].post(
        "/api/v1/admin/api-keys",
        json=_create_body(["print"], [hub["a"]]),
        headers=await _admin(),
    )
    assert resp.status_code == 201, resp.text


async def test_create_key_with_admin_and_print_scopes_and_printers_is_422(
    hub: dict[str, Any],
) -> None:
    """Any list holding ``admin`` is an admin key, whatever else it names."""
    resp = await hub["client"].post(
        "/api/v1/admin/api-keys",
        json=_create_body(["print", "admin"], [hub["a"]]),
        headers=await _admin(),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == _ERROR


# --- update ----------------------------------------------------------------


async def test_update_admin_key_with_printers_is_422(hub: dict[str, Any]) -> None:
    _, key_id = await _insert_key(["admin"])
    resp = await hub["client"].patch(
        f"/api/v1/admin/api-keys/{key_id}",
        json={"allowed_printer_ids": [hub["a"]]},
        headers=await _admin(),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == _ERROR
    async with _factory()() as s:
        row = await s.get(ApiKey, key_id)
        assert row is not None and row.allowed_printer_ids == []


async def test_update_admin_key_with_empty_list_is_200(hub: dict[str, Any]) -> None:
    """Clearing the list of a legacy admin key is the way out of the old state."""
    _, key_id = await _insert_key(["admin"], [hub["a"]])
    resp = await hub["client"].patch(
        f"/api/v1/admin/api-keys/{key_id}",
        json={"allowed_printer_ids": []},
        headers=await _admin(),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["allowed_printer_ids"] == []


async def test_update_admin_key_without_the_list_is_200(hub: dict[str, Any]) -> None:
    """A legacy admin key can still be renamed or disabled without touching the list."""
    _, key_id = await _insert_key(["admin"], [hub["a"]])
    resp = await hub["client"].patch(
        f"/api/v1/admin/api-keys/{key_id}", json={"notes": "x"}, headers=await _admin()
    )
    assert resp.status_code == 200, resp.text


async def test_update_print_key_with_printers_still_works(hub: dict[str, Any]) -> None:
    _, key_id = await _insert_key(["print"])
    resp = await hub["client"].patch(
        f"/api/v1/admin/api-keys/{key_id}",
        json={"allowed_printer_ids": [hub["a"]]},
        headers=await _admin(),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["allowed_printer_ids"] == [hub["a"]]


# --- the stored list of a legacy row is ignored ----------------------------


async def test_existing_restricted_admin_key_prints_on_any_printer(hub: dict[str, Any]) -> None:
    headers = await _legacy(hub)
    resp = await hub["client"].post(
        "/api/v1/print/tape-b/batch", json={"items": [_BODY]}, headers=headers
    )
    assert resp.status_code == 202, resp.text


async def test_legacy_admin_key_resolves_identity_on_printer_b(hub: dict[str, Any]) -> None:
    """The admin route that checks printer access today: 409 (no swap flagged), not 403."""
    resp = await hub["client"].post(
        f"/api/v1/admin/printers/{hub['b']}/identity/resolve",
        json={
            "resolution": "same_device",
            "expected_observed_id": "fake-device",
            "expected_observed_kind": "serial",
        },
        headers=await _legacy(hub),
    )
    assert resp.status_code == 409, resp.text  # no swap flagged: past the access check


# The remaining admin printer routes check no printer access today; these tests guard a
# later regression (a check added to one of them) and do not fail against the old code.


async def test_legacy_admin_key_lists_printers(hub: dict[str, Any]) -> None:
    """Regression guard, not a counter-test of #283: the route checks no access today."""
    resp = await hub["client"].get("/api/v1/admin/printers", headers=await _legacy(hub))
    assert resp.status_code == 200, resp.text
    assert {p["slug"] for p in resp.json()} >= {"tape-a", "tape-b"}


async def test_legacy_admin_key_gets_printer_b(hub: dict[str, Any]) -> None:
    """Regression guard, not a counter-test of #283: the route checks no access today."""
    resp = await hub["client"].get("/api/v1/admin/printers/tape-b", headers=await _legacy(hub))
    assert resp.status_code == 200, resp.text


async def test_legacy_admin_key_updates_printer_b(hub: dict[str, Any]) -> None:
    """Regression guard, not a counter-test of #283: the route checks no access today."""
    resp = await hub["client"].put(
        "/api/v1/admin/printers/tape-b", json={"name": "Tape B2"}, headers=await _legacy(hub)
    )
    assert resp.status_code != 403, resp.text


async def test_legacy_admin_key_disables_and_enables_printer_b(hub: dict[str, Any]) -> None:
    """Regression guard, not a counter-test of #283: the routes check no access today."""
    headers = await _legacy(hub)
    off = await hub["client"].post("/api/v1/admin/printers/tape-b/disable", headers=headers)
    assert off.status_code != 403, off.text
    on = await hub["client"].post("/api/v1/admin/printers/tape-b/enable", headers=headers)
    assert on.status_code != 403, on.text


async def test_restricted_admin_session_is_unrestricted(hub: dict[str, Any]) -> None:
    """A browser session signed in with the legacy key lists the jobs of printer B."""
    async with _factory()() as s:
        job = Job(printer_id=hub["b"], template_key=None, payload={}, state="done")
        s.add(job)
        await s.commit()
        job_id = str(job.id)
    headers = await _legacy(hub)
    async with AsyncClient(transport=ASGITransport(app=hub["app"]), base_url="http://t") as browser:
        signed = await browser.post(
            "/api/v1/auth/session", json={"key": headers["X-Label-Hub-Key"]}
        )
        assert signed.status_code == 204, signed.text
        resp = await browser.get(f"/api/v1/jobs?printer_id={hub['b']}")
    assert resp.status_code == 200, resp.text
    assert job_id in {j["id"] for j in resp.json()}


async def test_legacy_admin_key_lists_jobs_of_printer_b(hub: dict[str, Any]) -> None:
    async with _factory()() as s:
        job = Job(printer_id=hub["b"], template_key=None, payload={}, state="done")
        s.add(job)
        await s.commit()
        job_id = str(job.id)
    resp = await hub["client"].get(
        f"/api/v1/jobs?printer_id={hub['b']}", headers=await _legacy(hub)
    )
    assert resp.status_code == 200, resp.text
    assert job_id in {j["id"] for j in resp.json()}
