# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""GET /api/v1/notices: the hub's one-time notes for the notification centre (spec 10i, I4)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import bcrypt
from app.models.api_key import ApiKey
from app.models.app_setting import AppSetting
from app.seed.sheet_seed import ADOPTED_KEY, CORRECTED_KEY, NOTICES_KEY


def _factory():
    import app.db.engine as _engine_module

    return _engine_module.async_session


async def _read_key(scope: str = "read") -> dict[str, str]:
    plaintext = f"lh_pat_{uuid4().hex}"
    async with _factory()() as s:
        s.add(
            ApiKey(
                name=f"notices-{uuid4().hex[:6]}",
                key_hash=bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode(),
                key_prefix=plaintext[:16],
                scopes=[scope],
                enabled=True,
                rate_limit_per_minute=6000,
            )
        )
        await s.commit()
    return {"X-Label-Hub-Key": plaintext}


async def _admin_key() -> dict[str, str]:
    return await _read_key("admin")


def _record(key: str, age: timedelta, kind: str = "sheet_type_verified", code: str = "6121"):
    at = (datetime.now(UTC) - age).isoformat().replace("+00:00", "Z")
    return {"id": f"sheet-type-verified:{key}:2", "kind": kind, "key": key, "code": code, "at": at}


async def _store(records: list[object]) -> None:
    async with _factory()() as s:
        s.add(AppSetting(key=NOTICES_KEY, value_json=json.dumps(records)))
        await s.commit()


async def test_notices_list_recent_records(api_client_with_seed) -> None:
    await _store(
        [
            _record("avery-zweckform-6121", timedelta(days=1)),
            _record("avery-zweckform-3490", timedelta(days=31), code="3490"),
            _record(
                "avery-zweckform-l4731rev", timedelta(hours=1), "sheet_type_updated", "L4731REV"
            ),
            "not a record",
        ]
    )
    resp = await api_client_with_seed.get("/api/v1/notices", headers=await _read_key())
    assert resp.status_code == 200
    body = resp.json()
    assert [(n["key"], n["kind"], n["code"]) for n in body] == [
        ("avery-zweckform-l4731rev", "sheet_type_updated", "L4731REV"),  # newest first
        ("avery-zweckform-6121", "sheet_type_verified", "6121"),
    ]
    assert set(body[0]) == {"id", "kind", "key", "code", "at"}
    assert body[1]["at"].endswith("Z")


async def test_notices_without_records_is_an_empty_list(api_client_with_seed) -> None:
    resp = await api_client_with_seed.get("/api/v1/notices", headers=await _read_key())
    assert resp.status_code == 200 and resp.json() == []


async def test_notices_need_a_read_key(api_client_with_seed) -> None:
    assert (await api_client_with_seed.get("/api/v1/notices")).status_code == 401
    ok = await api_client_with_seed.get("/api/v1/notices", headers=await _read_key())
    assert ok.status_code == 200


async def test_info_carries_no_notices(api_client_with_seed) -> None:
    await _store([_record("avery-zweckform-6121", timedelta(days=1))])
    anonymous = await api_client_with_seed.get("/api/v1/info")
    assert anonymous.status_code == 200 and "notices" not in anonymous.json()
    keyed = await api_client_with_seed.get("/api/v1/info", headers=await _read_key())
    assert "notices" not in keyed.json()
    # signed in: /info reads the session cookie
    key = (await _read_key("print"))["X-Label-Hub-Key"]
    signed_in = await api_client_with_seed.post("/api/v1/auth/session", json={"key": key})
    assert signed_in.status_code == 204
    with_session = await api_client_with_seed.get("/api/v1/info")
    assert with_session.status_code == 200 and "notices" not in with_session.json()


async def test_internal_rows_are_not_listed_by_the_settings_api(api_client_with_seed) -> None:
    async with _factory()() as s:
        for key in (ADOPTED_KEY, CORRECTED_KEY):
            s.add(AppSetting(key=key, value_json=json.dumps({"avery-zweckform-6121": 2})))
        await s.commit()
    await _store([_record("avery-zweckform-6121", timedelta(days=1))])
    admin = await _admin_key()
    resp = await api_client_with_seed.get("/api/v1/settings", headers=admin)
    assert resp.status_code == 200
    listed = {row["key"] for row in resp.json()}
    assert listed and not listed & {ADOPTED_KEY, CORRECTED_KEY, NOTICES_KEY}
