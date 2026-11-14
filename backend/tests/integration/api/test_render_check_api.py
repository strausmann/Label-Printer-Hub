# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""POST /api/v1/render/check (#285): read scope, bounded body, per-item verdicts in order."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import app.models  # noqa: F401
import bcrypt
import pytest
from app.models.api_key import ApiKey
from app.schemas.label_data import LabelData
from app.services.lookup_service import LookupFailedError

_URL = "/api/v1/render/check"
_OK = LabelData(
    title="ThinkPad", primary_id="ASSET-001", qr_payload="https://x.invalid/1", source_app="snipeit"
)


async def _insert_key(scopes: list[str], rate_limit: int = 600) -> str:
    import app.db.engine as _engine_module

    plaintext = f"lh_pat_{uuid4().hex}"
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    async with _engine_module.async_session() as s:
        s.add(
            ApiKey(
                name=f"render-check-{uuid4().hex[:6]}",
                key_hash=hashed,
                key_prefix=plaintext[:16],
                scopes=scopes,
                allowed_printer_ids=[],
                enabled=True,
                rate_limit_per_minute=rate_limit,
            )
        )
        await s.commit()
    return plaintext


def _item(identifier: str = "ASSET-001") -> dict[str, object]:
    return {
        "content_type": "qr_two_lines",
        "lookup": {"app": "snipeit", "identifier": identifier},
    }


def _body(*items: dict[str, object], tape_mm: int = 62) -> dict[str, object]:
    return {"tape_mm": tape_mm, "items": list(items)}


@pytest.mark.asyncio
async def test_check_read_key_200(api_client_with_seed):
    key = await _insert_key(["read"])
    with patch("app.api.routes.print._lookup_service.lookup", new=AsyncMock(return_value=_OK)):
        resp = await api_client_with_seed.post(
            _URL, json=_body(_item()), headers={"X-Label-Hub-Key": key}
        )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "results": [
            {
                "index": 0,
                "ok": True,
                "error_code": None,
                "error_message": None,
                "error_detail": None,
            }
        ]
    }


@pytest.mark.asyncio
async def test_check_unauthenticated_401(api_client_with_seed):
    with patch("app.api.routes.print._lookup_service.lookup", new=AsyncMock()) as svc:
        resp = await api_client_with_seed.post(_URL, json=_body(_item()))
    assert resp.status_code == 401
    svc.assert_not_called()


@pytest.mark.asyncio
async def test_check_51_items_422(api_client_with_seed):
    key = await _insert_key(["read"])
    with patch("app.api.routes.print._lookup_service.lookup", new=AsyncMock()) as svc:
        resp = await api_client_with_seed.post(
            _URL, json=_body(*[_item(f"A{i}") for i in range(51)]), headers={"X-Label-Hub-Key": key}
        )
    assert resp.status_code == 422
    svc.assert_not_called()


@pytest.mark.asyncio
async def test_check_identifier_over_256_422(api_client_with_seed):
    key = await _insert_key(["read"])
    resp = await api_client_with_seed.post(
        _URL, json=_body(_item("x" * 257)), headers={"X-Label-Hub-Key": key}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_check_unsupported_tape_409_unsupported_tape(api_client_with_seed):
    key = await _insert_key(["read"])
    with patch("app.api.routes.print._lookup_service.lookup", new=AsyncMock()) as svc:
        resp = await api_client_with_seed.post(
            _URL, json=_body(_item(), tape_mm=13), headers={"X-Label-Hub-Key": key}
        )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "unsupported_tape"
    assert resp.json()["error_detail"] == {"tape_mm": 13}
    svc.assert_not_called()


@pytest.mark.asyncio
async def test_check_results_keep_order(api_client_with_seed):
    key = await _insert_key(["read"])

    async def _lookup(app: str, identifier: str) -> LabelData:
        if identifier == "BAD":
            raise LookupFailedError("http://internal.invalid boom")
        return _OK

    with patch("app.api.routes.print._lookup_service.lookup", new=_lookup):
        resp = await api_client_with_seed.post(
            _URL,
            json=_body(_item("A"), _item("BAD"), _item("A")),
            headers={"X-Label-Hub-Key": key},
        )
    assert resp.status_code == 200, resp.text
    results = resp.json()["results"]
    assert [(r["index"], r["ok"]) for r in results] == [(0, True), (1, False), (2, True)]
    assert results[1]["error_code"] == "integration_lookup_failed"
    assert "internal.invalid" not in resp.text


@pytest.mark.asyncio
async def test_check_as_large_as_the_limit_is_served(api_client_with_seed):
    """Limit 5, ten distinct items, full bucket: the request's token pays for one lookup and
    the charge is capped at what the bucket holds. A cap of the capacity would refuse it forever."""
    key = await _insert_key(["read"], rate_limit=5)
    with patch("app.api.routes.print._lookup_service.lookup", new=AsyncMock(return_value=_OK)):
        resp = await api_client_with_seed.post(
            _URL,
            json=_body(*[_item(f"A{i}") for i in range(10)]),
            headers={"X-Label-Hub-Key": key},
        )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_check_over_the_rate_budget_429_before_any_lookup(api_client_with_seed):
    key = await _insert_key(["read"], rate_limit=10)
    with patch("app.api.routes.print._lookup_service.lookup", new=AsyncMock(return_value=_OK)):
        first = await api_client_with_seed.post(
            _URL, json=_body(_item("ONE")), headers={"X-Label-Hub-Key": key}
        )  # 9 tokens left
        assert first.status_code == 200
    with patch("app.api.routes.print._lookup_service.lookup", new=AsyncMock()) as svc:
        resp = await api_client_with_seed.post(
            _URL,
            json=_body(*[_item(f"A{i}") for i in range(10)]),  # token -> 8 left, needs 9
            headers={"X-Label-Hub-Key": key},
        )
    assert resp.status_code == 429, resp.text
    assert resp.json()["detail"]["error_code"] == "rate_limit_exceeded"
    assert int(resp.headers["Retry-After"]) >= 1
    svc.assert_not_called()


@pytest.mark.asyncio
async def test_check_charges_each_distinct_lookup_not_duplicates(api_client_with_seed):
    key = await _insert_key(["read"], rate_limit=6)
    # limit 6: a request with one distinct lookup costs just its own token. Charging the 40
    # duplicates (capped at the bucket) would drain it and refuse the second request.
    dup = _body(*[_item("SAME")] * 40)  # 40 items, one distinct lookup
    with patch("app.api.routes.print._lookup_service.lookup", new=AsyncMock(return_value=_OK)):
        first = await api_client_with_seed.post(_URL, json=dup, headers={"X-Label-Hub-Key": key})
        second = await api_client_with_seed.post(_URL, json=dup, headers={"X-Label-Hub-Key": key})
    assert first.status_code == 200 and second.status_code == 200


@pytest.mark.asyncio
async def test_check_unsupported_tape_is_not_charged(api_client_with_seed):
    key = await _insert_key(["read"], rate_limit=4)
    for _ in range(3):  # would exhaust the bucket if the tape refusal charged the lookups
        resp = await api_client_with_seed.post(
            _URL,
            json=_body(*[_item(f"A{i}") for i in range(3)], tape_mm=13),
            headers={"X-Label-Hub-Key": key},
        )
        assert resp.status_code == 409
