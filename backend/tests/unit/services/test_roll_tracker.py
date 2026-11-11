"""Roll-change detection: one prompt per changed roll, also across a restart (#229)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.models.printer_roll import PrinterRoll
from app.services.event_bus import EventBus
from app.services.roll_tracker import RollTracker
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio


async def _row(factory: async_sessionmaker[AsyncSession], pid: UUID) -> PrinterRoll | None:
    async with factory() as s:
        return await s.get(PrinterRoll, pid)


def _events(bus: EventBus, pid: UUID):
    return bus.subscribe(f"printer:{pid}:tape", "t")


async def test_pt_and_ql_both_prompt(async_session_factory) -> None:
    bus = EventBus()
    tracker = RollTracker(bus, async_session_factory)
    pt, ql = uuid4(), uuid4()
    assert (await tracker.observe(pt, 12, '12mm(0.47")')).prompt_pending is True
    assert (await tracker.observe(ql, 62, '62mm / 2.4"')).prompt_pending is True
    assert (await _row(async_session_factory, pt)).prompt_pending is True
    assert (await _row(async_session_factory, ql)).prompt_pending is True


async def test_roll_change_clears_colour_and_raises_prompt(async_session_factory) -> None:
    bus = EventBus()
    pid = uuid4()
    q = _events(bus, pid)
    async with async_session_factory() as s:
        s.add(PrinterRoll(printer_id=pid, width_mm=62, media_raw="62mm", colour="red"))
        await s.commit()
    change = await RollTracker(bus, async_session_factory).observe(pid, 29, "29mm")
    row = await _row(async_session_factory, pid)
    assert change is not None
    assert (row.width_mm, row.media_raw, row.colour, row.set_at) == (29, "29mm", None, None)
    assert row.prompt_pending is True
    assert q.qsize() == 1
    event = q.get_nowait()
    assert event.event_type == "printer.roll_changed"
    assert event.data == {"width_mm": 29, "media_raw": "29mm", "prompt_pending": True}


async def test_same_roll_does_not_reprompt(async_session_factory) -> None:
    bus = EventBus()
    pid = uuid4()
    q = _events(bus, pid)
    tracker = RollTracker(bus, async_session_factory)
    results = [await tracker.observe(pid, 62, "62mm") for _ in range(3)]
    assert [r is not None for r in results] == [True, False, False]
    assert q.qsize() == 1


async def test_first_probe_after_restart_detects_change_once(async_session_factory) -> None:
    bus = EventBus()
    pid = uuid4()
    q = _events(bus, pid)
    async with async_session_factory() as s:
        s.add(PrinterRoll(printer_id=pid, width_mm=62, media_raw="62mm", colour="blue"))
        await s.commit()
    fresh = RollTracker(bus, async_session_factory)  # the hub just started
    first = await fresh.observe(pid, 12, "12mm")
    second = await fresh.observe(pid, 12, "12mm")
    assert first is not None and second is None
    assert q.qsize() == 1
    assert (await _row(async_session_factory, pid)).colour is None


async def test_stored_roll_unchanged_after_restart_stays_quiet(async_session_factory) -> None:
    bus = EventBus()
    pid = uuid4()
    async with async_session_factory() as s:
        s.add(PrinterRoll(printer_id=pid, width_mm=62, media_raw="62mm", colour="blue"))
        await s.commit()
    assert await RollTracker(bus, async_session_factory).observe(pid, 62, "62mm") is None
    assert (await _row(async_session_factory, pid)).colour == "blue"


async def test_no_tape_clears_without_prompt(async_session_factory) -> None:
    pid = uuid4()
    async with async_session_factory() as s:
        s.add(
            PrinterRoll(
                printer_id=pid, width_mm=62, media_raw="62mm", colour="red", prompt_pending=True
            )
        )
        await s.commit()
    tracker = RollTracker(EventBus(), async_session_factory)
    assert await tracker.observe(pid, None, None) is None  # the first one is not believed
    change = await tracker.observe(pid, None, None)
    row = await _row(async_session_factory, pid)
    assert change is not None and change.prompt_pending is False
    assert (row.width_mm, row.colour, row.prompt_pending) == (None, None, False)


async def test_cassette_out_and_back_prompts_again(async_session_factory) -> None:
    pid = uuid4()
    tracker = RollTracker(EventBus(), async_session_factory)
    await tracker.observe(pid, 62, "62mm")
    await tracker.observe(pid, None, None)
    await tracker.observe(pid, None, None)  # two in a row: the cassette is out
    back = await tracker.observe(pid, 62, "62mm")
    assert back is not None and back.prompt_pending is True


async def test_zero_width_and_blank_media_are_no_tape(async_session_factory) -> None:
    pid = uuid4()
    change = await RollTracker(EventBus(), async_session_factory).observe(pid, 0, "  ")
    assert change is not None and (change.width_mm, change.media_raw) == (None, None)
    assert change.prompt_pending is False


async def test_put_between_tracker_read_and_write_is_not_lost(async_session_factory) -> None:
    """A colour PUT commits after the tracker read the row: the new roll must not inherit it."""
    from app.repositories import printer_roll as roll_repo

    pid = uuid4()
    async with async_session_factory() as s:
        s.add(
            PrinterRoll(
                printer_id=pid, width_mm=62, media_raw="62mm", colour=None, prompt_pending=True
            )
        )
        await s.commit()
    tracker = RollTracker(EventBus(), async_session_factory)
    fired = []

    async def put_now() -> None:
        if fired:
            return
        fired.append(1)
        async with async_session_factory() as s:
            assert await roll_repo.set_colour(
                s,
                pid,
                colour="red",
                width_mm=62,
                media_raw=None,
                now=datetime.now(UTC),
            )

    tracker._after_read = put_now  # deterministic hook: runs between the read and the write
    change = await tracker.observe(pid, 12, "12mm")
    row = await _row(async_session_factory, pid)
    assert change is not None
    assert (row.width_mm, row.media_raw, row.colour, row.prompt_pending) == (12, "12mm", None, True)


async def test_media_raw_is_trimmed_and_capped(async_session_factory) -> None:
    pid = uuid4()
    change = await RollTracker(EventBus(), async_session_factory).observe(pid, 12, " " + "x" * 200)
    assert change is not None and change.media_raw == "x" * 64
    assert (await _row(async_session_factory, pid)).media_raw == "x" * 64


async def _seed(factory, pid: UUID, *, colour: str | None = "red") -> None:
    async with factory() as s:
        s.add(PrinterRoll(printer_id=pid, width_mm=62, media_raw="62mm", colour=colour))
        await s.commit()


async def test_single_no_tape_probe_keeps_colour(async_session_factory) -> None:
    """One probe that sees no tape is a hiccup; the recorded colour survives it (263-37)."""
    bus = EventBus()
    pid = uuid4()
    q = _events(bus, pid)
    await _seed(async_session_factory, pid)
    tracker = RollTracker(bus, async_session_factory)
    assert await tracker.observe(pid, None, None) is None
    row = await _row(async_session_factory, pid)
    assert (row.width_mm, row.media_raw, row.colour) == (62, "62mm", "red")
    assert q.qsize() == 0
    # The same cassette is back: no new question for the operator.
    assert await tracker.observe(pid, 62, "62mm") is None
    assert (await _row(async_session_factory, pid)).colour == "red"
    assert q.qsize() == 0


async def test_two_no_tape_probes_clear_colour(async_session_factory) -> None:
    bus = EventBus()
    pid = uuid4()
    await _seed(async_session_factory, pid)
    tracker = RollTracker(bus, async_session_factory)
    assert await tracker.observe(pid, None, None) is None
    change = await tracker.observe(pid, None, None)
    assert change is not None and change.width_mm is None
    row = await _row(async_session_factory, pid)
    assert (row.width_mm, row.colour, row.prompt_pending) == (None, None, False)


async def test_a_tape_probe_resets_the_no_tape_count(async_session_factory) -> None:
    """No tape, tape, no tape is not two in a row."""
    pid = uuid4()
    await _seed(async_session_factory, pid)
    tracker = RollTracker(EventBus(), async_session_factory)
    for width, raw in ((None, None), (62, "62mm"), (None, None)):
        assert await tracker.observe(pid, width, raw) is None
    assert (await _row(async_session_factory, pid)).colour == "red"


async def test_a_different_roll_is_still_found_at_once(async_session_factory) -> None:
    """The debounce is for "no tape" only; another cassette counts on the first probe."""
    pid = uuid4()
    await _seed(async_session_factory, pid)
    assert await RollTracker(EventBus(), async_session_factory).observe(pid, 29, "29mm")
