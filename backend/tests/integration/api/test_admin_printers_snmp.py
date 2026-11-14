"""The SNMP community is write-only (#296, R-296-5).

No printer response (admin or read routes) carries ``connection.snmp.community``; it reports
``connection.snmp.community_set`` instead. On create and update, a ``snmp`` object without a
``community`` key, or with ``null``, keeps the stored community (``"public"`` on create); a
non-empty string replaces it. The audit trail keeps redacting it.

The planted community is an obviously fake value; every check also greps the raw response
text and the captured logs for it. Hosts are TEST-NET addresses; every SNMP query the printer
runtime would send is patched, so no network is touched.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import app.models  # noqa: F401
import bcrypt
import pytest
from app.models.api_key import ApiKey
from app.models.printer import Printer, PrinterAudit
from app.printer_backends.snmp_helper import PreflightStatus
from sqlalchemy import select

pytestmark = pytest.mark.asyncio

PLANTED = "s3cret-t1-community"
ADMIN = "/api/v1/admin/printers"


@pytest.fixture(autouse=True)
def _no_snmp() -> Iterator[None]:
    """The runtime wires printers with ``snmp.discover``; keep every SNMP query local."""
    preflight = AsyncMock(return_value=PreflightStatus(hr_printer_status="idle", loaded_tape_mm=12))
    with (
        patch(
            "app.services.printer_runtime._resolve_model_id_from_config",
            AsyncMock(return_value="PT-P750W"),
        ),
        patch("app.services.producers.status_probe_producer.query_preflight", preflight),
        patch(
            "app.services.producers.status_probe_producer.query_identity",
            AsyncMock(return_value=None),
        ),
    ):
        yield


def _factory():
    import app.db.engine as _engine_module

    return _engine_module.async_session


async def _key(scopes: list[str]) -> dict[str, str]:
    plaintext = f"lh_pat_{uuid4().hex}"
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    async with _factory()() as s:
        s.add(
            ApiKey(
                name=f"snmp-{uuid4().hex[:6]}",
                key_hash=hashed,
                key_prefix=plaintext[:16],
                scopes=scopes,
                allowed_printer_ids=[],
                enabled=True,
                rate_limit_per_minute=600,
            )
        )
        await s.commit()
    return {"X-Label-Hub-Key": plaintext}


async def _insert_printer(community: str | None = PLANTED, discover: bool = True) -> Printer:
    slug = f"snmp-{uuid4().hex[:8]}"
    snmp: dict[str, Any] = {"discover": discover}
    if community is not None:
        snmp["community"] = community
    async with _factory()() as s:
        printer = Printer(
            name=slug,
            slug=slug,
            model="PT-P750W",
            backend="ptouch",
            connection={"host": "192.0.2.41", "port": 9100, "snmp": snmp},
        )
        s.add(printer)
        await s.commit()
        await s.refresh(printer)
        return printer


async def _stored_connection(printer_id: UUID) -> dict[str, Any]:
    async with _factory()() as s:
        row = (await s.execute(select(Printer).where(Printer.id == printer_id))).scalar_one()
        return dict(row.connection or {})


def _assert_no_community(snmp: dict[str, Any]) -> None:
    assert "community" not in snmp
    assert snmp["community_set"] is True


async def test_admin_read_has_community_set_not_value(api_client_with_seed, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    printer = await _insert_printer()
    headers = await _key(["admin"])

    one = await api_client_with_seed.get(f"{ADMIN}/{printer.slug}", headers=headers)
    assert one.status_code == 200, one.text
    assert one.json()["connection"]["snmp"] == {"discover": True, "community_set": True}
    assert PLANTED not in one.text

    listed = await api_client_with_seed.get(ADMIN, headers=headers)
    assert listed.status_code == 200, listed.text
    row = next(p for p in listed.json() if p["slug"] == printer.slug)
    assert row["connection"]["snmp"] == {"discover": True, "community_set": True}
    assert PLANTED not in listed.text
    assert PLANTED not in caplog.text


async def test_admin_read_without_stored_community_reports_false(api_client_with_seed) -> None:
    printer = await _insert_printer(community=None, discover=False)
    headers = await _key(["admin"])
    resp = await api_client_with_seed.get(f"{ADMIN}/{printer.slug}", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["connection"]["snmp"] == {"discover": False, "community_set": False}


async def test_printer_read_key_never_sees_community(api_client_with_seed, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    printer = await _insert_printer()
    for scopes in (["read"], ["admin"]):
        headers = await _key(scopes)
        listed = await api_client_with_seed.get("/api/v1/printers", headers=headers)
        assert listed.status_code == 200, listed.text
        row = next(p for p in listed.json() if p["id"] == str(printer.id))
        _assert_no_community(row["connection"]["snmp"])
        assert PLANTED not in listed.text

        one = await api_client_with_seed.get(f"/api/v1/printers/{printer.id}", headers=headers)
        assert one.status_code == 200, one.text
        _assert_no_community(one.json()["connection"]["snmp"])
        assert PLANTED not in one.text
    assert PLANTED not in caplog.text


async def _put_snmp(client, slug: str, snmp: dict[str, Any]):
    headers = await _key(["admin"])
    body = {"connection": {"host": "192.0.2.41", "port": 9100, "snmp": snmp}}
    return await client.put(f"{ADMIN}/{slug}", json=body, headers=headers)


async def test_update_without_community_keeps_stored(api_client_with_seed, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    printer = await _insert_printer()
    resp = await _put_snmp(api_client_with_seed, printer.slug, {"discover": True})
    assert resp.status_code == 200, resp.text
    assert PLANTED not in resp.text
    _assert_no_community(resp.json()["connection"]["snmp"])
    assert (await _stored_connection(printer.id))["snmp"] == {
        "discover": True,
        "community": PLANTED,
    }
    assert PLANTED not in caplog.text


async def test_update_with_null_community_keeps_stored(api_client_with_seed) -> None:
    printer = await _insert_printer()
    resp = await _put_snmp(
        api_client_with_seed, printer.slug, {"discover": False, "community": None}
    )
    assert resp.status_code == 200, resp.text
    assert (await _stored_connection(printer.id))["snmp"]["community"] == PLANTED


async def test_update_with_community_replaces_it(api_client_with_seed) -> None:
    printer = await _insert_printer()
    resp = await _put_snmp(
        api_client_with_seed, printer.slug, {"discover": True, "community": "n3w"}
    )
    assert resp.status_code == 200, resp.text
    assert "n3w" not in resp.text
    assert (await _stored_connection(printer.id))["snmp"]["community"] == "n3w"


async def test_update_of_a_row_without_community_stores_public(api_client_with_seed) -> None:
    printer = await _insert_printer(community=None, discover=False)
    resp = await _put_snmp(api_client_with_seed, printer.slug, {"discover": True})
    assert resp.status_code == 200, resp.text
    assert (await _stored_connection(printer.id))["snmp"]["community"] == "public"


async def test_update_with_empty_community_and_discover_is_refused(api_client_with_seed) -> None:
    printer = await _insert_printer()
    resp = await _put_snmp(api_client_with_seed, printer.slug, {"discover": True, "community": ""})
    assert resp.status_code == 422, resp.text
    assert PLANTED not in resp.text
    assert (await _stored_connection(printer.id))["snmp"]["community"] == PLANTED


async def test_create_without_community_stores_public(api_client_with_seed) -> None:
    headers = await _key(["admin"])
    slug = f"snmp-new-{uuid4().hex[:6]}"
    body = {
        "name": slug,
        "slug": slug,
        "model": "PT-P750W",
        "backend": "ptouch",
        "connection": {"host": "192.0.2.42", "port": 9100, "snmp": {"discover": True}},
    }
    resp = await api_client_with_seed.post(ADMIN, json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    _assert_no_community(resp.json()["connection"]["snmp"])
    stored = await _stored_connection(UUID(resp.json()["id"]))
    assert stored["snmp"] == {"discover": True, "community": "public"}


async def test_create_with_community_stores_it_and_hides_it(api_client_with_seed) -> None:
    headers = await _key(["admin"])
    slug = f"snmp-new-{uuid4().hex[:6]}"
    body = {
        "name": slug,
        "slug": slug,
        "model": "PT-P750W",
        "backend": "ptouch",
        "connection": {
            "host": "192.0.2.42",
            "port": 9100,
            "snmp": {"discover": True, "community": PLANTED},
        },
    }
    resp = await api_client_with_seed.post(ADMIN, json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    assert PLANTED not in resp.text
    stored = await _stored_connection(UUID(resp.json()["id"]))
    assert stored["snmp"]["community"] == PLANTED


async def test_audit_trail_still_redacts(api_client_with_seed) -> None:
    printer = await _insert_printer()
    resp = await _put_snmp(api_client_with_seed, printer.slug, {"discover": True})
    assert resp.status_code == 200, resp.text
    async with _factory()() as s:
        audit = (
            (await s.execute(select(PrinterAudit).where(PrinterAudit.printer_id == printer.id)))
            .scalars()
            .all()
        )
    assert len(audit) == 1
    assert audit[0].after_json is not None
    assert audit[0].after_json["connection"]["snmp"]["community"] == "***REDACTED***"
    assert audit[0].before_json is not None
    assert audit[0].before_json["connection"]["snmp"]["community"] == "***REDACTED***"
    assert PLANTED not in str(audit[0].after_json)
    assert PLANTED not in str(audit[0].before_json)


async def test_discovery_without_any_community_is_refused(api_client_with_seed) -> None:
    """An old row that stored ``""``: nothing to keep, so discovery cannot be switched on."""
    printer = await _insert_printer(community="", discover=False)
    resp = await _put_snmp(api_client_with_seed, printer.slug, {"discover": True})
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["error_code"] == "snmp_community_required"
    assert (await _stored_connection(printer.id))["snmp"] == {"discover": False, "community": ""}
