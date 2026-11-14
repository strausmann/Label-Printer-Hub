# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Per-printer ACL on the printer read endpoints (#146).

Covers the list, the ``?slug=`` lookup, ``/tape`` and ``/queue`` for restricted
and unrestricted API keys and for browser sessions (which inherit the key's
``allowed_printer_ids``).  All keys and hosts are obviously fake test values.

Convention for a foreign printer looked up by ``?slug=``: the response is the
same 404 ``printer_not_found`` as for a slug that does not exist, so the
existence of a printer outside the caller's scope is not leaked.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import app.models  # noqa: F401
import bcrypt
import pytest
from app.models.api_key import ApiKey
from app.models.printer import Printer


def _factory():
    import app.db.engine as _engine_module

    return _engine_module.async_session


async def _insert_key(scopes: list[str], allowed_printer_ids: list[str]) -> str:
    plaintext = f"lh_pat_{uuid4().hex}"
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    async with _factory()() as s:
        s.add(
            ApiKey(
                name=f"read-acl-{uuid4().hex[:6]}",
                key_hash=hashed,
                key_prefix=plaintext[:16],
                scopes=scopes,
                allowed_printer_ids=allowed_printer_ids,
                enabled=True,
                rate_limit_per_minute=600,
            )
        )
        await s.commit()
    return plaintext


async def _insert_printer(slug: str) -> UUID:
    async with _factory()() as s:
        printer = Printer(
            name=slug,
            slug=slug,
            model="PT-P750W",
            backend="ptouch",
            connection={"host": "192.0.2.40", "port": 9100},
        )
        s.add(printer)
        await s.commit()
        await s.refresh(printer)
        return printer.id


@pytest.fixture
async def two_printers():
    suffix = uuid4().hex[:6]
    a = await _insert_printer(f"acl-read-a-{suffix}")
    b = await _insert_printer(f"acl-read-b-{suffix}")
    return a, b, f"acl-read-a-{suffix}", f"acl-read-b-{suffix}"


def _ids(resp) -> set[str]:
    return {p["id"] for p in resp.json()}


@pytest.mark.asyncio
async def test_list_filters_to_allowed_printers(api_client_with_seed, two_printers):
    a, _b, _, _ = two_printers
    key = await _insert_key(["read"], [str(a)])
    resp = await api_client_with_seed.get("/api/v1/printers", headers={"X-Label-Hub-Key": key})
    assert resp.status_code == 200, resp.text
    assert _ids(resp) == {str(a)}


@pytest.mark.asyncio
async def test_list_unrestricted_key_sees_all(api_client_with_seed, two_printers):
    a, b, _, _ = two_printers
    key = await _insert_key(["read"], [])
    resp = await api_client_with_seed.get("/api/v1/printers", headers={"X-Label-Hub-Key": key})
    assert resp.status_code == 200, resp.text
    assert {str(a), str(b)} <= _ids(resp)


@pytest.mark.asyncio
async def test_slug_lookup_of_foreign_printer_is_404(api_client_with_seed, two_printers):
    a, _, slug_a, slug_b = two_printers
    key = await _insert_key(["read"], [str(a)])
    headers = {"X-Label-Hub-Key": key}
    own = await api_client_with_seed.get(
        "/api/v1/printers", params={"slug": slug_a}, headers=headers
    )
    assert own.status_code == 200, own.text
    assert _ids(own) == {str(a)}
    foreign = await api_client_with_seed.get(
        "/api/v1/printers", params={"slug": slug_b}, headers=headers
    )
    assert foreign.status_code == 404, foreign.text
    assert foreign.json()["detail"]["error_code"] == "printer_not_found"
    # Indistinguishable from a slug that does not exist.
    missing = await api_client_with_seed.get(
        "/api/v1/printers", params={"slug": "acl-read-missing"}, headers=headers
    )
    assert missing.status_code == 404
    assert missing.json()["detail"]["error_code"] == foreign.json()["detail"]["error_code"]


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["tape", "queue"])
async def test_tape_and_queue_of_foreign_printer_403(api_client_with_seed, two_printers, suffix):
    a, b, _, _ = two_printers
    key = await _insert_key(["read"], [str(a)])
    resp = await api_client_with_seed.get(
        f"/api/v1/printers/{b}/{suffix}", headers={"X-Label-Hub-Key": key}
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["error_code"] == "printer_not_allowed"


@pytest.mark.asyncio
async def test_queue_of_allowed_printer_ok_and_unrestricted_ok(api_client_with_seed, two_printers):
    a, b, _, _ = two_printers
    restricted = await _insert_key(["read"], [str(a)])
    resp = await api_client_with_seed.get(
        f"/api/v1/printers/{a}/queue", headers={"X-Label-Hub-Key": restricted}
    )
    assert resp.status_code == 200, resp.text
    unrestricted = await _insert_key(["read"], [])
    resp = await api_client_with_seed.get(
        f"/api/v1/printers/{b}/queue", headers={"X-Label-Hub-Key": unrestricted}
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_session_list_tape_queue_follow_key_restriction(api_client_with_seed, two_printers):
    a, b, _slug_a, slug_b = two_printers
    key = await _insert_key(["print"], [str(a)])
    signed_in = await api_client_with_seed.post("/api/v1/auth/session", json={"key": key})
    assert signed_in.status_code in (200, 201, 204), signed_in.text
    listing = await api_client_with_seed.get("/api/v1/printers")
    assert listing.status_code == 200, listing.text
    assert _ids(listing) == {str(a)}
    foreign_slug = await api_client_with_seed.get("/api/v1/printers", params={"slug": slug_b})
    assert foreign_slug.status_code == 404
    assert (await api_client_with_seed.get(f"/api/v1/printers/{b}/tape")).status_code == 403
    assert (await api_client_with_seed.get(f"/api/v1/printers/{b}/queue")).status_code == 403
    assert (await api_client_with_seed.get(f"/api/v1/printers/{a}/queue")).status_code == 200
