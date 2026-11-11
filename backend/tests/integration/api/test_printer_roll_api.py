"""The roll record endpoints, and the colour in the status and tape reads (#229)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import app.models  # noqa: F401
import bcrypt
import httpx
import pytest
import pytest_asyncio
from app.api.dependencies.printer_runtime import get_printer_runtime
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_print, require_read
from app.models.api_key import ApiKey
from app.models.printer import Printer
from app.models.printer_roll import PrinterRoll
from app.models.printer_status_cache import PrinterStatusCache
from app.services.event_bus import EventBus
from app.services.roll_tracker import RollTracker
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.helpers.fake_printer_runtime import FakeRuntime


@pytest.fixture(autouse=True)
def _trust_legacy_pangolin_user(monkeypatch: pytest.MonkeyPatch):
    from app.config import get_settings

    monkeypatch.setenv("LABELYARD_TRUST_LEGACY_PANGOLIN_USER", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def api(async_session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator:
    from app.api.routes.printer_roll import router as roll_router
    from app.api.routes.printers import router
    from app.db.session import get_session
    from fastapi import FastAPI

    async with async_session_factory() as session:
        app = FastAPI()
        app.state.event_bus = EventBus()
        app.include_router(router)
        app.include_router(roll_router)

        async def _override() -> AsyncIterator[AsyncSession]:
            yield session

        app.dependency_overrides[get_session] = _override
        fake = AuthContext(source="api-key", scope="admin", api_key_id=uuid4(), ip="127.0.0.1")
        for dep in (require_read, require_print):
            app.dependency_overrides[dep] = lambda _c=fake: _c
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://t",
            headers={"X-Pangolin-User": "tester"},
        ) as c:
            yield c, app, async_session_factory


async def _printer(factory, slug: str = "p") -> UUID:
    async with factory() as s:
        p = Printer(
            name=slug, slug=slug, model="x", backend="mock", connection={"host": "127.0.0.1"}
        )
        s.add(p)
        await s.commit()
        return p.id


async def _roll(factory, pid: UUID, **kw) -> None:
    async with factory() as s:
        s.add(PrinterRoll(printer_id=pid, **kw))
        await s.commit()


async def _cache(factory, pid: UUID, width: int | None, *, age_s: float = 5) -> None:
    stamp = datetime.now(UTC) - timedelta(seconds=age_s)
    parsed = {"online": True, "loaded_tape_mm": width, "media_raw": f"{width}mm"}
    async with factory() as s:
        s.add(
            PrinterStatusCache(printer_id=pid, parsed=parsed, captured_at=stamp, updated_at=stamp)
        )
        await s.commit()


async def test_read_roll_empty_before_first_probe(api) -> None:
    client, _, factory = api
    pid = await _printer(factory)
    r = await client.get(f"/api/v1/printers/{pid}/roll")
    assert r.status_code == 200
    assert r.json() == {
        "width_mm": None,
        "media_raw": None,
        "colour": None,
        "set_at": None,
        "prompt_pending": False,
    }


async def test_read_roll_unknown_printer_is_404(api) -> None:
    client, _, _ = api
    assert (await client.get(f"/api/v1/printers/{uuid4()}/roll")).status_code == 404
    assert (
        await client.put(f"/api/v1/printers/{uuid4()}/roll", json={"colour": None})
    ).status_code == 404


async def test_set_colour_clears_prompt(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _roll(factory, pid, width_mm=62, media_raw="62mm", prompt_pending=True)
    q = app.state.event_bus.subscribe(f"printer:{pid}:tape", "t")
    r = await client.put(f"/api/v1/printers/{pid}/roll", json={"colour": "red", "width_mm": 62})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["colour"], body["prompt_pending"], body["width_mm"]) == ("red", False, 62)
    assert body["set_at"] is not None
    assert (await client.get(f"/api/v1/printers/{pid}/roll")).json()["colour"] == "red"
    event = q.get_nowait()
    assert event.event_type == "printer.roll_changed"
    assert event.data["prompt_pending"] is False


async def test_skip_sets_no_colour(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _roll(factory, pid, width_mm=62, media_raw="62mm", colour="red", prompt_pending=True)
    await _cache(factory, pid, 62)
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    r = await client.put(f"/api/v1/printers/{pid}/roll", json={"colour": None, "width_mm": 62})
    assert r.status_code == 200
    assert r.json()["set_at"] is None
    status = (await client.get(f"/api/v1/printers/{pid}/status")).json()
    assert status["tape_colour"] is None
    assert status["roll_prompt"] is False


async def test_status_and_tape_carry_the_colour(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _roll(factory, pid, width_mm=62, media_raw="62mm", colour="blue")
    await _cache(factory, pid, 62)
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    status = (await client.get(f"/api/v1/printers/{pid}/status")).json()
    assert (status["tape_colour"], status["roll_prompt"]) == ("blue", False)
    assert (await client.get(f"/api/v1/printers/{pid}/tape")).json()["colour"] == "blue"


async def test_status_raises_prompt_for_a_changed_roll(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _cache(factory, pid, 29)
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    await RollTracker(None, factory).observe(pid, 29, "29mm")
    status = (await client.get(f"/api/v1/printers/{pid}/status")).json()
    assert (status["roll_prompt"], status["tape_colour"]) == (True, None)


async def test_stale_status_reports_no_colour_and_no_prompt(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _roll(factory, pid, width_mm=62, media_raw="62mm", colour="blue", prompt_pending=True)
    await _cache(factory, pid, 62, age_s=100_000)
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    status = (await client.get(f"/api/v1/printers/{pid}/status")).json()
    assert (status["stale"], status["tape_colour"], status["roll_prompt"]) == (True, None, False)
    assert (await client.get(f"/api/v1/printers/{pid}/tape")).status_code == 404


async def test_unpolled_printer_reports_no_colour_and_no_prompt(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _roll(factory, pid, width_mm=62, media_raw="62mm", colour="blue", prompt_pending=True)
    await _cache(factory, pid, 62)
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime(set())
    status = (await client.get(f"/api/v1/printers/{pid}/status")).json()
    assert (status["polled"], status["tape_colour"], status["roll_prompt"]) == (False, None, False)


async def test_colour_of_another_width_is_not_reported(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _roll(factory, pid, width_mm=62, media_raw="62mm", colour="blue")
    await _cache(factory, pid, 12)  # the roll was swapped, the next probe has not run yet
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    assert (await client.get(f"/api/v1/printers/{pid}/status")).json()["tape_colour"] is None


async def test_set_colour_without_roll_is_409(api) -> None:
    client, _, factory = api
    pid = await _printer(factory)
    r = await client.put(f"/api/v1/printers/{pid}/roll", json={"colour": "red"})
    assert r.status_code == 409
    assert r.json()["detail"]["type"] == "no-roll-loaded"
    pid2 = await _printer(factory, "q")
    await _roll(factory, pid2, width_mm=None, media_raw=None)
    r = await client.put(f"/api/v1/printers/{pid2}/roll", json={"colour": "red"})
    assert (r.status_code, r.json()["detail"]["type"]) == (409, "no-roll-loaded")


async def test_set_colour_for_old_roll_is_409(api) -> None:
    client, _, factory = api
    pid = await _printer(factory)
    await _roll(factory, pid, width_mm=29, media_raw="29mm", prompt_pending=True)
    r = await client.put(f"/api/v1/printers/{pid}/roll", json={"colour": "red", "width_mm": 62})
    assert r.status_code == 409
    assert r.json()["detail"]["type"] == "roll-changed"
    row = (await client.get(f"/api/v1/printers/{pid}/roll")).json()
    assert (row["colour"], row["prompt_pending"]) == (None, True)


async def test_put_without_width_colours_the_stored_roll(api) -> None:
    client, _, factory = api
    pid = await _printer(factory)
    await _roll(factory, pid, width_mm=29, media_raw="29mm", prompt_pending=True)
    r = await client.put(f"/api/v1/printers/{pid}/roll", json={"colour": "green"})
    assert (r.status_code, r.json()["colour"]) == (200, "green")


async def test_bad_colour_and_extra_field_are_422(api) -> None:
    client, _, factory = api
    pid = await _printer(factory)
    await _roll(factory, pid, width_mm=29, media_raw="29mm")
    url = f"/api/v1/printers/{pid}/roll"
    assert (await client.put(url, json={"colour": "pink"})).status_code == 422
    assert (await client.put(url, json={"colour": "red", "extra": 1})).status_code == 422


async def test_put_racing_a_detected_change_never_colours_the_new_roll(api) -> None:
    """The roll changes between the endpoint's read and its write: 409, no colour kept."""
    client, _, factory = api
    pid = await _printer(factory)
    await _roll(factory, pid, width_mm=62, media_raw="62mm", prompt_pending=True)
    from app.repositories import printer_roll as roll_repo

    real = roll_repo.set_colour

    async def swapped_first(session, printer_id, **kw):
        await RollTracker(None, factory).observe(printer_id, 12, "12mm")
        return await real(session, printer_id, **kw)

    roll_repo.set_colour = swapped_first  # type: ignore[assignment]
    try:
        r = await client.put(f"/api/v1/printers/{pid}/roll", json={"colour": "red", "width_mm": 62})
    finally:
        roll_repo.set_colour = real  # type: ignore[assignment]
    assert (r.status_code, r.json()["detail"]["type"]) == (409, "roll-changed")
    row = (await client.get(f"/api/v1/printers/{pid}/roll")).json()
    assert (row["width_mm"], row["colour"], row["prompt_pending"]) == (12, None, True)


async def test_concurrent_probe_and_put_end_in_a_consistent_state(api) -> None:
    client, _, factory = api
    pid = await _printer(factory)
    await _roll(factory, pid, width_mm=62, media_raw="62mm", prompt_pending=True)
    results = await asyncio.gather(
        RollTracker(None, factory).observe(pid, 12, "12mm"),
        client.put(f"/api/v1/printers/{pid}/roll", json={"colour": "red", "width_mm": 62}),
    )
    row = (await client.get(f"/api/v1/printers/{pid}/roll")).json()
    assert results[0] is not None
    assert row["width_mm"] == 12
    assert row["colour"] is None  # the colour belonged to the old roll
    assert row["prompt_pending"] is True


# ------------------------------------------------------------------ keys and ACL (full app)


def _factory():
    import app.db.engine as _engine_module

    return _engine_module.async_session


async def _key(scopes: list[str], allowed: list[str]) -> str:
    plaintext = f"lh_pat_{uuid4().hex}"
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    async with _factory()() as s:
        s.add(
            ApiKey(
                name=f"roll-{uuid4().hex[:6]}",
                key_hash=hashed,
                key_prefix=plaintext[:16],
                scopes=scopes,
                allowed_printer_ids=allowed,
                enabled=True,
                rate_limit_per_minute=600,
            )
        )
        await s.commit()
    return plaintext


async def _printer_with_roll(slug: str) -> UUID:
    async with _factory()() as s:
        p = Printer(
            name=slug,
            slug=slug,
            model="PT-P750W",
            backend="ptouch",
            connection={"host": "192.0.2.40", "port": 9100},
        )
        s.add(p)
        await s.commit()
        await s.refresh(p)
        s.add(PrinterRoll(printer_id=p.id, width_mm=62, media_raw="62mm", prompt_pending=True))
        await s.commit()
        return p.id


def _h(key: str) -> dict[str, str]:
    return {"X-Label-Hub-Key": key}


@pytest.mark.asyncio
async def test_read_key_cannot_set_colour(api_client_with_seed) -> None:
    pid = await _printer_with_roll(f"roll-a-{uuid4().hex[:6]}")
    key = await _key(["read"], [])
    url = f"/api/v1/printers/{pid}/roll"
    assert (await api_client_with_seed.get(url, headers=_h(key))).status_code == 200
    r = await api_client_with_seed.put(url, json={"colour": "red"}, headers=_h(key))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_restricted_key_cannot_set_other_printer(api_client_with_seed) -> None:
    own = await _printer_with_roll(f"roll-own-{uuid4().hex[:6]}")
    other = await _printer_with_roll(f"roll-other-{uuid4().hex[:6]}")
    key = await _key(["print"], [str(own)])
    body = {"colour": "red", "width_mm": 62}
    r = await api_client_with_seed.put(f"/api/v1/printers/{other}/roll", json=body, headers=_h(key))
    assert r.status_code == 403
    r = await api_client_with_seed.put(f"/api/v1/printers/{own}/roll", json=body, headers=_h(key))
    assert r.status_code == 200, r.text
    assert r.json()["colour"] == "red"


@pytest.mark.asyncio
async def test_restricted_key_cannot_read_other_roll(api_client_with_seed) -> None:
    own = await _printer_with_roll(f"roll-own-{uuid4().hex[:6]}")
    other = await _printer_with_roll(f"roll-other-{uuid4().hex[:6]}")
    key = await _key(["read"], [str(own)])
    assert (
        await api_client_with_seed.get(f"/api/v1/printers/{other}/roll", headers=_h(key))
    ).status_code == 403
    assert (
        await api_client_with_seed.get(f"/api/v1/printers/{own}/roll", headers=_h(key))
    ).status_code == 200


async def test_put_with_stale_media_text_is_409_and_with_current_text_is_200(api) -> None:
    client, _, factory = api
    pid = await _printer(factory)
    await _roll(factory, pid, width_mm=62, media_raw="62mm / 2.4", prompt_pending=True)
    url = f"/api/v1/printers/{pid}/roll"
    r = await client.put(url, json={"colour": "red", "width_mm": 62, "media_raw": "62mm"})
    assert (r.status_code, r.json()["detail"]["type"]) == (409, "roll-changed")
    r = await client.put(url, json={"colour": "red", "width_mm": 62, "media_raw": "62mm / 2.4"})
    assert r.status_code == 200


async def test_roll_prompt_is_off_while_the_stored_roll_is_not_the_loaded_one(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _roll(factory, pid, width_mm=62, media_raw="62mm", prompt_pending=True)
    await _cache(factory, pid, 12)  # swapped, the next probe has not run yet
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    assert (await client.get(f"/api/v1/printers/{pid}/status")).json()["roll_prompt"] is False
