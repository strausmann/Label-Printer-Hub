# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Grocy's label printer webhook: ``POST /api/v1/webhook/grocy/label`` (#281, R-281-1 to R-281-11).

The real app and lifespan run against a temp database with one tape printer. Its backend is a
recording ``MockPrinterBackend`` (one shared instance, so ``printed_images`` survives an app
restart). The keys are real rows in the database: the route authenticates them itself
(``require_print_token``), nothing is overridden. Every wait is bounded.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import app.models  # noqa: F401
import bcrypt
import pytest
from app.auth.verifier import _cache as verifier_cache
from app.config import get_settings
from app.models.api_key import ApiKey
from app.models.job import Job as DbJob
from app.models.printer import Printer
from app.printer_backends.exceptions import PrinterOfflineError
from app.printer_backends.mock_backend import MockPrinterBackend
from app.schemas.grocy_label import GROCY_LABEL_BUDGET_S, MAX_GROCY_LABEL_BODY
from app.services.backend_router import BackendRouter
from app.services.event_bus import BusEvent
from app.services.rate_limiter import _rate_limiter
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

pytestmark = pytest.mark.asyncio

URL = "/api/v1/webhook/grocy/label"
WAIT_S = 6.0
TERMINAL = frozenset({"done", "failed", "failed_restart", "cancelled"})
PRODUCT = {"product": "Oat milk", "grocycode": "grcy:p:12"}
STOCK_ENTRY = {
    "product": "Oat milk",
    "grocycode": "grcy:p:12:63a1b2c3d4e5f",
    "due_date": "DD: 2026-12-01",
}


def _key(word: str, fill: str) -> str:
    """A made-up key in the real format, built at runtime (no literal for secret scanners)."""
    return "lh_pat_" + word + fill * (43 - len(word))


PRINT_KEY = _key("grocyprint", "A")
ADMIN_KEY = _key("grocyadmin", "C")
RESTRICTED_KEY = _key("grocyrestricted", "R")
LIMITED_KEY = _key("grocylimited", "L")
UNKNOWN_KEY = _key("grocyunknown", "U")


def _key_row(plaintext: str, scopes: list[str], **extra: Any) -> ApiKey:
    return ApiKey(
        name=f"grocy-{scopes[0]}",
        key_hash=bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode(),
        key_prefix=plaintext[:16],
        scopes=scopes,
        enabled=True,
        **extra,
    )


@dataclass
class Hub:
    backend: MockPrinterBackend
    printer_id: UUID
    keys: dict[str, UUID]
    events: list[BusEvent] = field(default_factory=list)

    @asynccontextmanager
    async def running(
        self, settings: dict[str, Any] | None = None, *, enabled: bool = True
    ) -> AsyncIterator[tuple[AsyncClient, Any]]:
        import app.db.engine as eng
        from app.main import create_app

        app = create_app()
        inner = app._app
        async with (
            inner.router.lifespan_context(inner),
            AsyncClient(transport=ASGITransport(app=inner), base_url="http://t") as client,
        ):
            values = {"integrations.grocy.label.enabled": enabled, **(settings or {})}
            async with eng.async_session() as s:
                await inner.state.settings_store.set_many(s, values)
            channel = f"printer:{self.printer_id}:queue"
            queue = inner.state.event_bus.subscribe(channel, "t8-events")

            async def _drain() -> None:
                while True:
                    event = await queue.get()
                    if event is not None:
                        self.events.append(event)

            drain = asyncio.create_task(_drain())
            try:
                yield client, inner
            finally:
                drain.cancel()
                inner.state.event_bus.unsubscribe(channel, "t8-events")

    def slow_preflight(self, seconds: float, *, error: Exception | None = None) -> None:
        original = self.backend.preflight_check

        async def slow() -> Any:
            await asyncio.sleep(seconds)
            if error is not None:
                raise error
            return await original()

        self.backend.preflight_check = slow  # type: ignore[method-assign]


@pytest.fixture
async def hub(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Hub]:
    import app.db.engine as eng
    from app.integrations import (  # type: ignore[attr-defined]
        IntegrationRegistry,
        _discover_plugins,
    )

    if not IntegrationRegistry.names():
        _discover_plugins()
    get_settings.cache_clear()
    _rate_limiter.clear()
    verifier_cache.clear()
    backend = MockPrinterBackend()
    monkeypatch.setattr(BackendRouter, "_build_one", staticmethod(lambda _cfg: backend))
    monkeypatch.setattr(
        "app.services.printer_runtime._resolve_model_id_from_config",
        AsyncMock(return_value="PT-P750W"),
    )
    async with eng.async_session() as s:
        printer = Printer(
            name="Tape",
            slug="tape-1",
            model="PT-P750W",
            backend="ptouch",
            connection={"host": "198.51.100.10", "port": 9100},
            enabled=True,
        )
        off = Printer(
            name="Tape off",
            slug="tape-off",
            model="PT-P750W",
            backend="ptouch",
            connection={"host": "198.51.100.11", "port": 9100},
            enabled=False,
        )
        rows = {
            "print": _key_row(PRINT_KEY, ["print"]),
            "admin": _key_row(ADMIN_KEY, ["admin"]),
            # Restricted to a printer that is not the label printer.
            "restricted": _key_row(RESTRICTED_KEY, ["print"], allowed_printer_ids=[str(uuid4())]),
            "limited": _key_row(LIMITED_KEY, ["print"], rate_limit_per_minute=1),
        }
        s.add_all([printer, off, *rows.values()])
        await s.commit()
        keys = {name: row.id for name, row in rows.items()}
        printer_id = printer.id
    yield Hub(backend=backend, printer_id=printer_id, keys=keys)
    _rate_limiter.clear()
    verifier_cache.clear()
    get_settings.cache_clear()


async def _post(
    client: AsyncClient, body: Any = PRODUCT, *, token: str = PRINT_KEY, **kwargs: Any
) -> Any:
    if "content" not in kwargs and "data" not in kwargs:
        kwargs["json"] = body
    return await client.post(f"{URL}?token={token}", **kwargs)


async def _until(predicate: Callable[[], Awaitable[bool]], timeout: float = WAIT_S) -> None:
    async with asyncio.timeout(timeout):
        while not await predicate():
            await asyncio.sleep(0.02)


async def _row(job_id: str | UUID) -> DbJob:
    import app.db.engine as eng

    async with eng.async_session() as s:
        row = await s.get(DbJob, UUID(str(job_id)))
        assert row is not None
        return row


async def _row_count() -> int:
    import app.db.engine as eng

    async with eng.async_session() as s:
        return int((await s.execute(select(func.count()).select_from(DbJob))).scalar_one())


async def _ends(job_id: str, state: str, timeout: float = WAIT_S) -> DbJob:
    """Wait for ``state``; another terminal state fails at once and names its error."""

    async def _in_state() -> bool:
        row = await _row(job_id)
        if row.state != state and row.state in TERMINAL:
            raise AssertionError(f"job ended {row.state} ({row.error}), expected {state}")
        return row.state == state

    await _until(_in_state, timeout)
    return await _row(job_id)


def _error_code(body: Any) -> str:
    return str(body["detail"]["error_code"])


# --- printing ------------------------------------------------------------------------------


async def test_product_label_prints_through_the_queue(hub: Hub) -> None:
    async with hub.running() as (client, _app):
        r = await _post(client)
        assert r.status_code == 202, r.text
        row = await _ends(r.json()["job_id"], "done")
    assert len(hub.backend.printed_images) == 1
    assert row.payload["content_type"] == "qr_two_lines"
    assert row.payload["label_data"]["source_app"] == "grocy"
    assert row.payload["label_data"]["qr_payload"] == "grcy:p:12"
    assert row.payload["deferred"] is True
    assert row.api_key_id == hub.keys["print"]
    assert row.printer_id == hub.printer_id


async def test_header_key_is_accepted(hub: Hub) -> None:
    async with hub.running() as (client, _app):
        r = await client.post(URL, json=PRODUCT, headers={"X-Label-Hub-Key": PRINT_KEY})
        assert r.status_code == 202, r.text
        await _ends(r.json()["job_id"], "done")


async def test_slow_preflight_does_not_delay_the_response(hub: Hub) -> None:
    hub.slow_preflight(3.0)
    async with hub.running() as (client, _app):
        started = time.monotonic()
        r = await _post(client)
        elapsed = time.monotonic() - started
        assert r.status_code == 202, r.text
        assert elapsed < GROCY_LABEL_BUDGET_S
        assert (await _row(r.json()["job_id"])).state == "queued"
        await _ends(r.json()["job_id"], "done")
    assert len(hub.backend.printed_images) == 1


async def test_offline_printer_is_202_then_failed(hub: Hub) -> None:
    hub.slow_preflight(3.0, error=PrinterOfflineError("198.51.100.10 refused the connection"))
    async with hub.running() as (client, _app):
        started = time.monotonic()
        r = await _post(client)
        elapsed = time.monotonic() - started
        assert r.status_code == 202, r.text
        assert elapsed < GROCY_LABEL_BUDGET_S
        job_id = r.json()["job_id"]
        row = await _ends(job_id, "failed")
        await asyncio.sleep(0.05)  # let the drain task take the event
    assert row.error is not None
    assert row.error.startswith("printer_offline")
    assert "198.51.100.10" not in row.error  # no str(exc) of the backend error
    assert hub.backend.printed_images == []
    changed = [
        e
        for e in hub.events
        if e.event_type == "job.state_changed" and e.data.get("job_id") == job_id
    ]
    assert changed, "no job.state_changed event for the failed job"
    assert changed[-1].data["to_state"] == "failed"
    assert changed[-1].data["error_code"] == "printer_offline"


async def test_no_tape_is_202_then_failed(hub: Hub) -> None:
    hub.backend._loaded_tape_mm = None  # type: ignore[assignment]
    async with hub.running() as (client, _app):
        r = await _post(client)
        assert r.status_code == 202, r.text
        row = await _ends(r.json()["job_id"], "failed")
    assert row.error is not None
    assert row.error.startswith("no_tape_loaded")


async def test_stock_entry_uses_its_mapping(hub: Hub) -> None:
    async with hub.running() as (client, _app):
        r = await _post(client, STOCK_ENTRY)
        assert r.status_code == 202, r.text
        row = await _ends(r.json()["job_id"], "done")
    assert row.payload["content_type"] == "qr_three_lines"
    assert row.payload["label_data"]["secondary"][0] == "DD: 2026-12-01"


async def test_stock_entry_without_due_date_prints_two_lines(hub: Hub) -> None:
    body = {k: v for k, v in STOCK_ENTRY.items() if k != "due_date"}
    async with hub.running() as (client, _app):
        r = await _post(client, body)
        assert r.status_code == 202, r.text
        row = await _ends(r.json()["job_id"], "done", timeout=3.0)
    assert row.payload["content_type"] == "qr_two_lines"
    assert len(hub.backend.printed_images) == 1


async def test_product_mapped_to_three_lines_prints_two_lines(hub: Hub) -> None:
    mapping = {"integrations.grocy.label.product.content_type": "qr_three_lines"}
    async with hub.running(mapping) as (client, _app):
        r = await _post(client)
        assert r.status_code == 202, r.text
        row = await _ends(r.json()["job_id"], "done", timeout=3.0)
    assert row.payload["content_type"] == "qr_two_lines"


async def test_mapping_qr_only(hub: Hub) -> None:
    mapping = {"integrations.grocy.label.chore.content_type": "qr_only"}
    async with hub.running(mapping) as (client, _app):
        r = await _post(client, {"chore": "Descale kettle", "grocycode": "grcy:c:3"})
        assert r.status_code == 202, r.text
        row = await _ends(r.json()["job_id"], "done")
    assert row.payload["content_type"] == "qr_only"


# --- content errors: 202 with a failed job --------------------------------------------------


async def _failed_with(hub: Hub, code: str, **post: Any) -> None:
    async with hub.running() as (client, _app):
        r = await _post(client, **post)
        assert r.status_code == 202, r.text
        row = await _row(r.json()["job_id"])
    assert row.state == "failed"
    assert row.error is not None
    assert row.error.split(":")[0] == code
    assert row.printer_id == hub.printer_id
    assert row.api_key_id == hub.keys["print"]
    assert row.payload["label_data"]["source_app"] == "grocy"
    assert hub.backend.printed_images == []


async def test_invalid_grocycode_is_202_with_failed_job(hub: Hub) -> None:
    await _failed_with(hub, "grocy_label_invalid", body={"product": "Oat", "grocycode": "grcy:x:1"})


async def test_mismatched_name_is_202_with_failed_job(hub: Hub) -> None:
    await _failed_with(
        hub, "grocy_label_mismatch", body={"chore": "Descale kettle", "grocycode": "grcy:p:12"}
    )


async def test_unparseable_json_is_202_with_failed_job(hub: Hub) -> None:
    await _failed_with(
        hub,
        "grocy_label_invalid",
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )


async def test_json_that_is_not_an_object_is_202_with_failed_job(hub: Hub) -> None:
    await _failed_with(hub, "grocy_label_invalid", body=["grcy:p:12"])


async def test_name_over_512_is_202_with_failed_job(hub: Hub) -> None:
    await _failed_with(
        hub, "grocy_label_invalid", body={"product": "x" * 513, "grocycode": "grcy:p:12"}
    )


async def test_content_error_publishes_a_failed_event(hub: Hub) -> None:
    async with hub.running() as (client, _app):
        r = await _post(client, {"product": "Oat", "grocycode": "nope"})
        assert r.status_code == 202, r.text
        await asyncio.sleep(0.05)
    job_id = r.json()["job_id"]
    changed = [e for e in hub.events if e.data.get("job_id") == job_id]
    assert [e.data["to_state"] for e in changed] == ["failed"]
    assert changed[0].data["error_code"] == "grocy_label_invalid"


# --- authentication, switch and body ---------------------------------------------------------


async def test_disabled_answers_503_grocy_label_disabled(hub: Hub) -> None:
    async with hub.running(enabled=False) as (client, _app):
        r = await _post(client)
    assert r.status_code == 503
    assert _error_code(r.json()) == "grocy_label_disabled"
    assert await _row_count() == 0


async def test_unauthenticated_disabled_is_401_not_503(hub: Hub) -> None:
    async with hub.running(enabled=False) as (client, _app):
        r = await client.post(URL, json=PRODUCT)
    assert r.status_code == 401
    assert _error_code(r.json()) == "invalid_token"


async def test_wrong_token_401_and_nothing_queued(hub: Hub) -> None:
    async with hub.running() as (client, _app):
        r = await _post(client, token=UNKNOWN_KEY)
        no_token = await client.post(URL, json=PRODUCT)
    assert (r.status_code, no_token.status_code) == (401, 401)
    assert _error_code(r.json()) == "invalid_token"
    assert UNKNOWN_KEY not in r.text
    assert await _row_count() == 0


async def test_admin_key_403(hub: Hub) -> None:
    async with hub.running() as (client, _app):
        r = await _post(client, token=ADMIN_KEY)
    assert r.status_code == 403
    assert _error_code(r.json()) == "token_scope_too_wide"
    assert await _row_count() == 0


async def test_rate_limit_429(hub: Hub) -> None:
    async with hub.running() as (client, _app):
        first = await _post(client, token=LIMITED_KEY)
        second = await _post(client, token=LIMITED_KEY)
        assert first.status_code == 202, first.text
        await _ends(first.json()["job_id"], "done")
    assert second.status_code == 429
    assert second.headers["Retry-After"]
    assert await _row_count() == 1


async def test_form_body_415_json_required(hub: Hub) -> None:
    async with hub.running() as (client, _app):
        r = await _post(client, data={"product": "Oat milk", "grocycode": "grcy:p:12"})
    assert r.status_code == 415
    body = r.json()
    assert _error_code(body) == "json_required"
    assert "LABEL_PRINTER_HOOK_JSON" in body["detail"]["error_message"]
    assert await _row_count() == 0


async def test_json_lookalike_media_type_is_415(hub: Hub) -> None:
    async with hub.running() as (client, _app):
        r = await _post(
            client,
            content=json.dumps(PRODUCT).encode(),
            headers={"Content-Type": "application/jsonp"},
        )
        with_charset = await _post(
            client,
            content=json.dumps(PRODUCT).encode(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
    assert r.status_code == 415
    assert with_charset.status_code == 202, with_charset.text


class _Chunks:
    """A request body of ``count`` chunks of 64 KiB that counts how many were read."""

    def __init__(self, count: int) -> None:
        self.count = count
        self.consumed = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for _ in range(self.count):
            self.consumed += 1
            yield b" " * 65_536


async def test_declared_length_over_limit_413_reads_nothing(hub: Hub) -> None:
    chunks = _Chunks(40)
    async with hub.running() as (client, _app):
        r = await _post(
            client,
            content=chunks,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(MAX_GROCY_LABEL_BODY + 1),
            },
        )
    assert r.status_code == 413
    assert _error_code(r.json()) == "body_too_large"
    assert chunks.consumed <= 1  # the transport may hand over the first chunk with the request
    assert await _row_count() == 0


async def test_chunked_body_stops_after_limit(hub: Hub) -> None:
    chunks = _Chunks(40)
    async with hub.running() as (client, _app):
        r = await _post(client, content=chunks, headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    assert _error_code(r.json()) == "body_too_large"
    assert chunks.consumed <= 17
    assert await _row_count() == 0


async def test_body_at_limit_is_accepted(hub: Hub) -> None:
    head = json.dumps({**PRODUCT, "pad": ""}).encode()
    pad = MAX_GROCY_LABEL_BODY - len(head)
    body = json.dumps({**PRODUCT, "pad": "a" * pad}).encode()
    assert len(body) == MAX_GROCY_LABEL_BODY
    async with hub.running() as (client, _app):
        r = await _post(client, content=body, headers={"Content-Type": "application/json"})
        assert r.status_code == 202, r.text
        await _ends(r.json()["job_id"], "done")


# --- the target printer ----------------------------------------------------------------------


def _no_printer_named(text: str, hub: Hub) -> None:
    assert str(hub.printer_id) not in text
    assert "tape-1" not in text
    assert "tape-off" not in text
    assert "tape-gone" not in text


async def test_mapped_printer_403_does_not_name_it(hub: Hub) -> None:
    mapping = {"integrations.grocy.label.product.printer": "tape-1"}
    async with hub.running(mapping) as (client, _app):
        r = await _post(client, token=RESTRICTED_KEY)
    assert r.status_code == 403
    assert r.json()["detail"] == {
        "error_code": "printer_not_allowed",
        "error_message": "No access to the default printer",
    }
    _no_printer_named(r.text, hub)
    assert await _row_count() == 0


async def test_default_printer_403_does_not_name_it(hub: Hub) -> None:
    async with hub.running() as (client, _app):
        r = await _post(client, token=RESTRICTED_KEY)
        # A content error is not answered before the printer check: still 403.
        bad = await _post(client, {"grocycode": "nope"}, token=RESTRICTED_KEY)
    for answer in (r, bad):
        assert answer.status_code == 403
        assert answer.json()["detail"]["error_message"] == "No access to the default printer"
        _no_printer_named(answer.text, hub)
    assert await _row_count() == 0


async def test_unknown_slug_503_before_access_check_reveals_nothing(hub: Hub) -> None:
    mapping = {"integrations.grocy.label.product.printer": "tape-gone"}
    async with hub.running(mapping) as (client, _app):
        restricted = await _post(client, token=RESTRICTED_KEY)
        unrestricted = await _post(client)
    for answer in (restricted, unrestricted):
        assert answer.status_code == 503
        assert _error_code(answer.json()) == "grocy_label_printer_unavailable"
        _no_printer_named(answer.text, hub)
    assert await _row_count() == 0


async def test_disabled_mapped_printer_after_access_check(hub: Hub) -> None:
    mapping = {"integrations.grocy.label.product.printer": "tape-off"}
    async with hub.running(mapping) as (client, _app):
        restricted = await _post(client, token=RESTRICTED_KEY)
        unrestricted = await _post(client)
    assert restricted.status_code == 403
    assert restricted.json()["detail"]["error_code"] == "printer_not_allowed"
    assert unrestricted.status_code == 503
    assert _error_code(unrestricted.json()) == "grocy_label_printer_unavailable"
    for answer in (restricted, unrestricted):
        _no_printer_named(answer.text, hub)
    assert await _row_count() == 0


async def test_unreadable_code_uses_the_product_mapping(hub: Hub) -> None:
    """The printer of a content error comes from the product mapping (R-281-8, step 2)."""
    mapping = {"integrations.grocy.label.product.printer": "tape-gone"}
    async with hub.running(mapping) as (client, _app):
        r = await _post(client, {"chore": "x", "grocycode": "grcy:c:not-a-number"})
    assert r.status_code == 503
    assert _error_code(r.json()) == "grocy_label_printer_unavailable"


async def test_type_mapping_picks_the_printer(hub: Hub) -> None:
    """A chore mapped to an unknown printer does not affect a product label."""
    mapping = {"integrations.grocy.label.chore.printer": "tape-gone"}
    async with hub.running(mapping) as (client, _app):
        product = await _post(client)
        chore = await _post(client, {"chore": "Descale kettle", "grocycode": "grcy:c:3"})
        assert product.status_code == 202, product.text
        await _ends(product.json()["job_id"], "done")
    assert chore.status_code == 503


async def test_default_target_used_when_the_type_has_no_printer(hub: Hub) -> None:
    mapping = {"integrations.grocy.label.printer": "tape-gone"}
    async with hub.running(mapping) as (client, _app):
        r = await _post(client)
    assert r.status_code == 503
    assert _error_code(r.json()) == "grocy_label_printer_unavailable"


async def test_type_printer_wins_over_the_default_target(hub: Hub) -> None:
    mapping = {
        "integrations.grocy.label.printer": "tape-gone",
        "integrations.grocy.label.product.printer": "tape-1",
    }
    async with hub.running(mapping) as (client, _app):
        r = await _post(client)
        assert r.status_code == 202, r.text
        row = await _ends(r.json()["job_id"], "done")
    assert row.printer_id == hub.printer_id


async def test_default_target_routes_a_type_without_printer(hub: Hub) -> None:
    mapping = {"integrations.grocy.label.printer": "tape-1"}
    async with hub.running(mapping) as (client, _app):
        r = await _post(client, {"battery": "Smoke alarm", "grocycode": "grcy:b:4"})
        assert r.status_code == 202, r.text
        row = await _ends(r.json()["job_id"], "done")
    assert row.printer_id == hub.printer_id


async def test_unknown_default_slug_503_reveals_nothing(hub: Hub) -> None:
    mapping = {"integrations.grocy.label.printer": "tape-gone"}
    async with hub.running(mapping) as (client, _app):
        restricted = await _post(client, token=RESTRICTED_KEY)
    assert restricted.status_code == 503
    assert _error_code(restricted.json()) == "grocy_label_printer_unavailable"
    _no_printer_named(restricted.text, hub)
    assert await _row_count() == 0


# --- the token stays out of everything stored --------------------------------------------


async def test_token_not_in_job_or_events(hub: Hub) -> None:
    async with hub.running() as (client, _app):
        ok = await _post(client)
        bad = await _post(client, {"product": "Oat", "grocycode": "grcy:x:1"})
        assert (ok.status_code, bad.status_code) == (202, 202)
        await _ends(ok.json()["job_id"], "done")
        await asyncio.sleep(0.05)
    for job_id in (ok.json()["job_id"], bad.json()["job_id"]):
        row = await _row(job_id)
        for column, value in row.model_dump().items():
            assert PRINT_KEY not in json.dumps(value, default=str), column
            assert PRINT_KEY[:16] not in json.dumps(value, default=str), column
    assert hub.events, "no event was captured; the check would pass on nothing"
    for event in hub.events:
        assert PRINT_KEY not in json.dumps(event.data, default=str)


# --- restart ---------------------------------------------------------------------------------


async def test_deferred_job_interrupted_by_restart_fails_once(hub: Hub) -> None:
    hub.slow_preflight(3.0)
    async with hub.running() as (client, _app):
        r = await _post(client)
        assert r.status_code == 202, r.text
        job_id = r.json()["job_id"]
    # The app stopped while the preflight slept: the label was never handed to the queue,
    # and the stop ended it at once (review F4; a crash is the recovery's case, below).
    stopped = await _row(job_id)
    assert (stopped.state, stopped.error) == ("failed_restart", "deferred_interrupted")
    async with hub.running() as (_client, _app):
        row = await _ends(job_id, "failed_restart")
        await asyncio.sleep(3.5)  # past the old preflight: nothing comes back to life
    assert row.state == "failed_restart"
    assert (await _row(job_id)).state == "failed_restart"
    assert hub.backend.printed_images == []


# --- retry (review F1) -----------------------------------------------------------------------


async def test_retry_of_an_offline_failed_label_prints_it(hub: Hub) -> None:
    original = hub.backend.preflight_check
    hub.slow_preflight(0.0, error=PrinterOfflineError("offline"))
    async with hub.running() as (client, _app):
        r = await _post(client)
        assert r.status_code == 202, r.text
        failed_id = r.json()["job_id"]
        await _ends(failed_id, "failed")
        before = await _row_count()
        hub.backend.preflight_check = original  # type: ignore[method-assign]  # printer is back
        retry = await client.post(
            f"/api/v1/jobs/{failed_id}/retry", headers={"X-Label-Hub-Key": PRINT_KEY}
        )
        assert retry.status_code == 201, retry.text
        new_id = retry.json()["id"]
        assert new_id != failed_id
        row = await _ends(new_id, "done")
        assert await _row_count() == before + 1  # only the new job, no failed clone
    assert len(hub.backend.printed_images) == 1
    assert row.payload["label_data"]["qr_payload"] == "grcy:p:12"
    assert row.payload["content_type"] == "qr_two_lines"
    assert row.printer_id == hub.printer_id
    assert row.api_key_id == hub.keys["print"]
    assert (await _row(failed_id)).state == "failed"  # the original stays as history


async def test_retry_of_a_content_error_is_422_without_a_new_row(hub: Hub) -> None:
    async with hub.running() as (client, _app):
        r = await _post(client, {"product": "Oat", "grocycode": "grcy:x:1"})
        assert r.status_code == 202, r.text
        before = await _row_count()
        retry = await client.post(
            f"/api/v1/jobs/{r.json()['job_id']}/retry", headers={"X-Label-Hub-Key": PRINT_KEY}
        )
        assert retry.status_code == 422, retry.text
        assert await _row_count() == before
    assert hub.backend.printed_images == []


# --- cancel during the preflight (review F2) ------------------------------------------------


async def test_cancel_during_preflight_never_prints(hub: Hub) -> None:
    hub.slow_preflight(1.0)
    async with hub.running() as (client, _app):
        r = await _post(client)
        assert r.status_code == 202, r.text
        job_id = r.json()["job_id"]
        cancel = await client.post(
            f"/api/v1/jobs/{job_id}/cancel", headers={"X-Label-Hub-Key": PRINT_KEY}
        )
        assert 200 <= cancel.status_code < 300, cancel.text
        await asyncio.sleep(1.8)  # past the preflight and the render
        row = await _row(job_id)
    assert row.state == "cancelled"
    assert "rendered_tape_mm" not in row.payload
    assert hub.backend.printed_images == []
    # Review N4: the untracked cancel is announced, so a watcher does not stay on "queued".
    assert _job_events(hub, job_id) == [("queued", "cancelled")]


# --- events only for real state changes (review F3, F5) --------------------------------------


def _job_events(hub: Hub, job_id: str) -> list[tuple[str, str]]:
    return [
        (str(e.data["from_state"]), str(e.data["to_state"]))
        for e in hub.events
        if e.event_type == "job.state_changed" and e.data.get("job_id") == job_id
    ]


async def test_cancelled_job_whose_preflight_fails_is_not_announced_failed(hub: Hub) -> None:
    hub.slow_preflight(1.0, error=PrinterOfflineError("offline"))
    async with hub.running() as (client, _app):
        r = await _post(client)
        assert r.status_code == 202, r.text
        job_id = r.json()["job_id"]
        cancel = await client.post(
            f"/api/v1/jobs/{job_id}/cancel", headers={"X-Label-Hub-Key": PRINT_KEY}
        )
        assert 200 <= cancel.status_code < 300, cancel.text
        await asyncio.sleep(1.5)  # past the failing preflight
        row = await _row(job_id)
    assert row.state == "cancelled"
    assert ("queued", "failed") not in _job_events(hub, job_id)


async def test_cancel_between_payload_and_queue_hand_off_never_prints(
    hub: Hub, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The window after ``set_queued_payload`` and before ``submit_with_id`` (review F5)."""
    from app.services.print_queue import PrintQueue

    release = asyncio.Event()
    original = PrintQueue.submit_with_id

    async def held(self: PrintQueue, *args: Any, **kwargs: Any) -> UUID:
        await release.wait()
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(PrintQueue, "submit_with_id", held)
    async with hub.running() as (client, _app):
        r = await _post(client)
        assert r.status_code == 202, r.text
        job_id = r.json()["job_id"]

        async def completed() -> bool:
            return "rendered_tape_mm" in (await _row(job_id)).payload

        await _until(completed)
        cancel = await client.post(
            f"/api/v1/jobs/{job_id}/cancel", headers={"X-Label-Hub-Key": PRINT_KEY}
        )
        assert 200 <= cancel.status_code < 300, cancel.text
        release.set()
        await asyncio.sleep(0.5)  # the worker takes the job and refuses it
        row = await _row(job_id)
    assert row.state == "cancelled"
    assert hub.backend.printed_images == []
    events = _job_events(hub, job_id)
    assert not any(to in ("printing", "failed") for _from, to in events), events


# --- detach and crash (review F4) ------------------------------------------------------------


async def test_detach_ends_an_interrupted_deferred_job_at_once(hub: Hub) -> None:
    hub.slow_preflight(3.0)
    async with hub.running() as (client, app):
        r = await _post(client)
        assert r.status_code == 202, r.text
        job_id = r.json()["job_id"]
        await app.state.printer_runtime.detach(hub.printer_id)  # disabled or removed
        row = await _row(job_id)  # no re-attach: nothing else would end it
        await asyncio.sleep(3.5)  # past the old preflight
        later = await _row(job_id)
    assert (row.state, row.error) == ("failed_restart", "deferred_interrupted")
    assert later.state == "failed_restart"
    assert hub.backend.printed_images == []
    assert _job_events(hub, job_id) == [("queued", "failed_restart")]  # review N4


async def test_deferred_row_left_by_a_crash_ends_failed_restart(hub: Hub) -> None:
    """No graceful stop ran (a crash): the queue's recovery ends the row at the next start."""
    import app.db.engine as eng

    job = DbJob(
        printer_id=hub.printer_id,
        template_key=None,
        payload={
            "deferred": True,
            "content_type": "qr_two_lines",
            "label_data": {
                "source_app": "grocy",
                "title": "Oat milk",
                "primary_id": "12",
                "qr_payload": "grcy:p:12",
                "secondary": [],
                "items": [],
            },
        },
    )
    async with eng.async_session() as s:
        s.add(job)
        await s.commit()
        job_id = str(job.id)
    async with hub.running() as (_client, _app):
        row = await _ends(job_id, "failed_restart")
    assert row.error == "deferred_interrupted"
    assert hub.backend.printed_images == []
