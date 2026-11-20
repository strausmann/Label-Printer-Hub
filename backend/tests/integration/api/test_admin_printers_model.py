# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The model of a tape printer is validated when the printer is created (#207, #166).

An unknown model used to be stored and then stopped the hub at the next start. The registry
is asked, after ``ensure_discovered()``: the QL driver has to be found on a process that never
imported its module.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import app.models  # noqa: F401
import bcrypt
import pytest
from app.models.api_key import ApiKey
from app.models.printer import Printer
from app.printer_models.registry import ModelRegistry
from sqlalchemy import select

pytestmark = pytest.mark.asyncio

ADMIN = "/api/v1/admin/printers"


def _factory():
    import app.db.engine as _engine_module

    return _engine_module.async_session


async def _admin() -> dict[str, str]:
    plaintext = f"lh_pat_{uuid4().hex}"
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    async with _factory()() as s:
        s.add(
            ApiKey(
                name=f"model-{uuid4().hex[:6]}",
                key_hash=hashed,
                key_prefix=plaintext[:16],
                scopes=["admin"],
                allowed_printer_ids=[],
                enabled=True,
                rate_limit_per_minute=600,
            )
        )
        await s.commit()
    return {"X-Label-Hub-Key": plaintext}


def _body(model: str | None, backend: str = "brother_ql", **over: Any) -> dict[str, Any]:
    slug = f"m-{uuid4().hex[:8]}"
    body: dict[str, Any] = {
        "name": slug,
        "slug": slug,
        "backend": backend,
        "connection": {"host": "192.0.2.50", "port": 9100, "snmp": {"discover": False}},
    }
    if model is not None:
        body["model"] = model
    body.update(over)
    return body


async def _count(slug: str) -> int:
    async with _factory()() as s:
        return len((await s.execute(select(Printer).where(Printer.slug == slug))).all())


async def test_create_unknown_model_is_422(api_client_with_seed) -> None:
    body = _body("NOPE-1", "ptouch")
    resp = await api_client_with_seed.post(ADMIN, json=body, headers=await _admin())
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["error_code"] == "printer_model_unknown"
    assert detail["error_message"] == "No driver is registered for this model."
    assert {"PT-P750W", "QL-820NWB"} <= set(detail["error_detail"]["known"])
    assert await _count(body["slug"]) == 0  # nothing stored


async def test_create_ql_printer_on_a_fresh_registry(api_client_with_seed) -> None:
    headers = await _admin()
    # The first request starts the lifespan, which discovers the drivers; only after it is the
    # registry made fresh, as in a process that never imported the QL module.
    assert (await api_client_with_seed.get(ADMIN, headers=headers)).status_code == 200
    ModelRegistry._models.clear()
    ModelRegistry._discovered = False
    resp = await api_client_with_seed.post(ADMIN, json=_body("QL-820NWB"), headers=headers)
    assert resp.status_code == 201, resp.text
    assert resp.json()["model"] == "QL-820NWB"


async def test_create_without_model_stays_a_schema_error(api_client_with_seed) -> None:
    """A tape printer needs a model (schema rule); the registry check never sees ``None``."""
    resp = await api_client_with_seed.post(
        ADMIN, json=_body(None, "ptouch"), headers=await _admin()
    )
    assert resp.status_code == 422, resp.text
    assert "printer_model_unknown" not in resp.text


async def test_update_does_not_touch_model(api_client_with_seed) -> None:
    """(guard) The update payload has no model; one sent anyway is ignored, not validated."""
    headers = await _admin()
    body = _body("PT-P750W", "ptouch")
    created = await api_client_with_seed.post(ADMIN, json=body, headers=headers)
    assert created.status_code == 201, created.text
    resp = await api_client_with_seed.put(
        f"{ADMIN}/{body['slug']}", json={"model": "NOPE-1", "name": "renamed"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["model"] == "PT-P750W"
    assert resp.json()["name"] == "renamed"
