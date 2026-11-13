"""#294: the event stream of a plain API key carries job events of its own jobs only.

``job.state_changed`` and ``run.state_changed`` (and the job frames of the snapshot) reach a
key without ``admin`` scope only for jobs and tape runs it submitted. Printer events
(``printer.status``, ``printer.tape_changed``) stay printer-scoped. A browser session signed
in with such a key is bound to it the same way; SSO users, admin keys and admin-key sessions
see every job of their printers. All keys are fake.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import app.models  # noqa: F401
import pytest
from app.config import get_settings
from app.models.job import Job, JobState
from app.models.print_batch import PrintBatch
from app.services.event_bus import BusEvent, EventBus

from tests.integration.api.test_auth_session import (
    _factory,
    _insert_key,
    _insert_printer,
    _sign_in,
)
from tests.integration.api.test_events_v1 import _bus, _connected, _key_header, _open
from tests.integration.api.test_events_v1 import hub_app as _hub_app_fixture

hub_app = _hub_app_fixture  # the same app fixture as the stream tests

pytestmark = pytest.mark.asyncio

FAKE_TRUST_TOKEN = "fake-trust-token-294-sse"


async def _job(printer_id: UUID, owner: UUID | None, state: str = JobState.FAILED.value) -> str:
    async with _factory()() as s:
        job = Job(printer_id=printer_id, payload={}, state=state, api_key_id=owner)
        s.add(job)
        await s.commit()
        return str(job.id)


async def _batch(printer_id: UUID, owner: UUID | None) -> str:
    async with _factory()() as s:
        batch = PrintBatch(
            printer_id=printer_id,
            job_ids=[],
            created_by=str(owner) if owner is not None else "pangolin-sso",
        )
        s.add(batch)
        await s.commit()
        return str(batch.id)


def _publish(bus: EventBus, channel: str, event_type: str, data: dict) -> None:
    bus.publish(
        channel,
        BusEvent(
            channel=channel,
            event_id=bus.next_event_id(channel),
            event_type=event_type,
            timestamp=datetime.now(UTC),
            data=data,
        ),
    )


def _job_event(bus: EventBus, printer_id: UUID, job_id: str) -> None:
    _publish(
        bus,
        f"printer:{printer_id}:queue",
        "job.state_changed",
        {
            "job_id": job_id,
            "from_state": "queued",
            "to_state": "printing",
            "queue_depth": 1,
            "error_code": None,
        },
    )


def _run_event(bus: EventBus, printer_id: UUID, run_id: str) -> None:
    _publish(
        bus,
        f"printer:{printer_id}:queue",
        "run.state_changed",
        {"run_id": run_id, "printer_id": str(printer_id), "state": "stopped"},
    )


def _status_event(bus: EventBus, printer_id: UUID) -> None:
    _publish(
        bus,
        f"printer:{printer_id}:state",
        "printer.status",
        {"hr_printer_status": "idle", "error_flags": [], "online": True},
    )


async def _next_job_level(stream) -> dict:
    """The next job.state_changed or run.state_changed frame (snapshot frames skipped)."""
    while True:
        ev = await stream.event()
        assert ev is not None, "stream ended"
        if ev["event"] in ("job.state_changed", "run.state_changed") and ev["id"] != "0":
            return ev


async def _world():
    printer = await _insert_printer(f"own-{uuid4().hex[:6]}")
    owner, owner_id = await _insert_key(["print"], allowed_printer_ids=[str(printer)])
    _other, other_id = await _insert_key(["print"], allowed_printer_ids=[str(printer)])
    return printer, owner, owner_id, other_id


async def test_a_key_gets_job_events_of_its_own_jobs_only(hub_app) -> None:
    app, _ = hub_app
    printer, owner, owner_id, other_id = await _world()
    mine = await _job(printer, owner_id)
    foreign = await _job(printer, other_id)
    orphan = await _job(printer, None)
    stream = await _open(app, _key_header(owner))
    try:
        await _connected(stream)
        bus = _bus(app)
        _job_event(bus, printer, foreign)
        _job_event(bus, printer, orphan)
        _job_event(bus, printer, str(uuid4()))  # no row (cleaned up): not delivered either
        _job_event(bus, printer, mine)
        ev = await _next_job_level(stream)
        assert ev["payload"]["data"]["job_id"] == mine
        _job_event(bus, printer, foreign)
        _job_event(bus, printer, mine)  # the cached answer still holds
        ev = await _next_job_level(stream)
        assert ev["payload"]["data"]["job_id"] == mine
    finally:
        await stream.close()


async def test_a_key_gets_run_events_of_its_own_runs_only(hub_app) -> None:
    app, _ = hub_app
    printer, owner, owner_id, other_id = await _world()
    mine = await _batch(printer, owner_id)
    foreign = await _batch(printer, other_id)
    orphan = await _batch(printer, None)
    stream = await _open(app, _key_header(owner))
    try:
        await _connected(stream)
        bus = _bus(app)
        _run_event(bus, printer, foreign)
        _run_event(bus, printer, orphan)
        _run_event(bus, printer, str(uuid4()))
        _run_event(bus, printer, mine)
        ev = await _next_job_level(stream)
        assert ev["event"] == "run.state_changed"
        assert ev["payload"]["data"]["run_id"] == mine
    finally:
        await stream.close()


async def test_printer_events_still_reach_every_key_of_the_printer(hub_app) -> None:
    app, _ = hub_app
    printer, owner, owner_id, other_id = await _world()
    foreign = await _job(printer, other_id)
    mine = await _job(printer, owner_id)
    stream = await _open(app, _key_header(owner))
    try:
        await _connected(stream)
        _job_event(_bus(app), printer, foreign)
        _status_event(_bus(app), printer)
        # The own job's frame comes after the foreign one's lookup, so no owner lookup is still
        # running when the stream is closed (a cancelled SQLite query can stall the loop's
        # teardown in the test).
        _job_event(_bus(app), printer, mine)
        seen_status = seen_mine = False
        while not (seen_status and seen_mine):
            ev = await stream.event()
            assert ev is not None
            if ev["id"] == "0":
                continue  # snapshot
            if ev["event"] == "printer.status":
                seen_status = True
            if ev["event"] == "job.state_changed":
                assert ev["payload"]["data"]["job_id"] == mine  # never the foreign job
                seen_mine = True
    finally:
        await stream.close()


async def test_an_admin_key_gets_every_job_event(hub_app) -> None:
    app, _ = hub_app
    printer, _owner, _owner_id, other_id = await _world()
    foreign = await _job(printer, other_id)
    orphan = await _job(printer, None)
    admin, _ = await _insert_key(["admin"])
    stream = await _open(app, _key_header(admin))
    try:
        await _connected(stream)
        _job_event(_bus(app), printer, foreign)
        _job_event(_bus(app), printer, orphan)
        assert (await _next_job_level(stream))["payload"]["data"]["job_id"] == foreign
        assert (await _next_job_level(stream))["payload"]["data"]["job_id"] == orphan
    finally:
        await stream.close()


def _session_cookie(client) -> dict[str, str]:
    return {"Cookie": f"lph_session={client.cookies.get('lph_session')}"}


async def test_a_print_key_session_gets_job_events_of_its_key_only(hub_app) -> None:
    """Fix round 1: a browser session minted from a print key is bound to that key."""
    app, client = hub_app
    printer, owner, owner_id, other_id = await _world()
    mine = await _job(printer, owner_id, JobState.QUEUED.value)
    foreign = await _job(printer, other_id, JobState.QUEUED.value)
    orphan = await _job(printer, None, JobState.QUEUED.value)
    my_run = await _batch(printer, owner_id)
    foreign_run = await _batch(printer, other_id)
    assert (await _sign_in(client, owner)).status_code == 204
    assert await _snapshot_job_ids(app, _session_cookie(client), printer) == {mine}
    stream = await _open(app, _session_cookie(client))
    try:
        await _connected(stream)
        bus = _bus(app)
        _job_event(bus, printer, foreign)
        _job_event(bus, printer, orphan)
        _run_event(bus, printer, foreign_run)
        _job_event(bus, printer, mine)
        _run_event(bus, printer, my_run)
        assert (await _next_job_level(stream))["payload"]["data"]["job_id"] == mine
        assert (await _next_job_level(stream))["payload"]["data"]["run_id"] == my_run
    finally:
        await stream.close()


async def test_an_admin_key_session_gets_every_job_event(hub_app) -> None:
    app, client = hub_app
    printer, _owner, _owner_id, other_id = await _world()
    foreign = await _job(printer, other_id)
    run = await _batch(printer, other_id)
    admin, _ = await _insert_key(["admin"])
    assert (await _sign_in(client, admin)).status_code == 204
    stream = await _open(app, _session_cookie(client))
    try:
        await _connected(stream)
        _job_event(_bus(app), printer, foreign)
        _run_event(_bus(app), printer, run)
        assert (await _next_job_level(stream))["payload"]["data"]["job_id"] == foreign
        assert (await _next_job_level(stream))["payload"]["data"]["run_id"] == run
    finally:
        await stream.close()


async def test_an_sso_user_gets_every_job_event(hub_app, monkeypatch) -> None:
    app, _ = hub_app
    monkeypatch.setenv("LABELYARD_SSO_TRUST_TOKEN", FAKE_TRUST_TOKEN)
    get_settings.cache_clear()
    printer, _owner, _owner_id, other_id = await _world()
    foreign = await _job(printer, other_id)
    stream = await _open(app, {"Remote-User": "alice", "X-Pangolin-Token": FAKE_TRUST_TOKEN})
    try:
        await _connected(stream)
        _job_event(_bus(app), printer, foreign)
        assert (await _next_job_level(stream))["payload"]["data"]["job_id"] == foreign
    finally:
        await stream.close()
        get_settings.cache_clear()


async def _snapshot_job_ids(app, headers: dict[str, str], printer: UUID) -> set[str]:
    stream = await _open(app, headers, f"printer_id={printer}")
    try:
        await _connected(stream)
        _status_event(_bus(app), printer)  # a live frame marks the end of the snapshot
        ids: set[str] = set()
        while True:
            ev = await stream.event()
            assert ev is not None
            if ev["id"] != "0":
                return ids
            if ev["event"] == "job.state_changed":
                ids.add(ev["payload"]["data"]["job_id"])
    finally:
        await stream.close()


async def test_the_snapshot_lists_a_keys_own_active_jobs_only(hub_app) -> None:
    app, _ = hub_app
    printer, owner, owner_id, other_id = await _world()
    queued = JobState.QUEUED.value
    mine = await _job(printer, owner_id, queued)
    foreign = await _job(printer, other_id, queued)
    orphan = await _job(printer, None, queued)
    assert await _snapshot_job_ids(app, _key_header(owner), printer) == {mine}
    admin, _ = await _insert_key(["admin"])
    assert await _snapshot_job_ids(app, _key_header(admin), printer) == {mine, foreign, orphan}


class _LiveRuns:
    """A stand-in queue whose tape runs are live: ``run_info`` names their owner key."""

    def __init__(self, owners: dict[str, UUID | None]) -> None:
        self._owners = owners

    def run_info(self, run_id: UUID):  # returns a duck-typed RunInfo
        from types import SimpleNamespace

        if str(run_id) not in self._owners:
            return None
        return SimpleNamespace(api_key_id=self._owners[str(run_id)])

    def has_job(self, _job_id: UUID) -> bool:
        return False


async def test_a_live_run_is_shown_to_its_key_only(hub_app) -> None:
    """Fix round 2 (I-2): while a run is in the queue, the queue's owner decides — there is no
    batch row to fall back on here, so only the live branch can deliver or hide it."""
    app, _ = hub_app
    printer, owner, owner_id, other_id = await _world()
    mine, foreign, keyless = str(uuid4()), str(uuid4()), str(uuid4())
    inner = app._app
    original = inner.state.print_queue
    inner.state.print_queue = _LiveRuns({mine: owner_id, foreign: other_id, keyless: None})
    stream = await _open(app, _key_header(owner))
    try:
        await _connected(stream)
        _run_event(_bus(app), printer, foreign)
        _run_event(_bus(app), printer, keyless)
        _run_event(_bus(app), printer, mine)
        ev = await _next_job_level(stream)
        assert (ev["event"], ev["payload"]["data"]["run_id"]) == ("run.state_changed", mine)
    finally:
        await stream.close()
        inner.state.print_queue = original


async def test_an_unknown_event_type_on_the_queue_channel_is_not_delivered(hub_app) -> None:
    """Fail closed: the filter knows two job event types; any other frame on a queue channel is
    held back from a plain key, even when it names the key's own job."""
    app, _ = hub_app
    printer, owner, owner_id, _other_id = await _world()
    mine = await _job(printer, owner_id)
    stream = await _open(app, _key_header(owner))
    try:
        await _connected(stream)
        bus = _bus(app)
        _publish(bus, f"printer:{printer}:queue", "job.progress", {"job_id": mine})
        _job_event(bus, printer, mine)
        while True:
            ev = await stream.event()
            assert ev is not None
            assert ev["event"] != "job.progress"
            if ev["event"] == "job.state_changed" and ev["id"] != "0":
                break
    finally:
        await stream.close()


async def test_an_owner_lookup_that_fails_delivers_nothing(hub_app, monkeypatch) -> None:
    """Fail closed: when the owner of a job or run cannot be looked up, the frame is held back."""
    import app.api.routes.events_v1 as events_v1

    app, _ = hub_app
    printer, owner, owner_id, _other_id = await _world()
    mine = await _job(printer, owner_id)
    run = await _batch(printer, owner_id)

    def broken(*_a, **_k):
        raise RuntimeError("lookup unavailable")

    monkeypatch.setattr(events_v1, "col", broken)  # used only by the owner lookups
    stream = await _open(app, _key_header(owner))
    try:
        await _connected(stream)
        _job_event(_bus(app), printer, mine)
        _run_event(_bus(app), printer, run)
        _status_event(_bus(app), printer)
        # The status frame travels on another channel and may overtake the queue frames, so
        # keep reading until the stream has been quiet for a while.
        while True:
            try:
                ev = await stream.event(timeout=1.5)
            except TimeoutError:
                break
            assert ev is not None
            assert ev["event"] not in ("job.state_changed", "run.state_changed") or ev["id"] == "0"
    finally:
        await stream.close()
