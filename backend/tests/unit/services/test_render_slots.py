"""#293: a render past its time limit is reported to its caller and shown as stuck.

A hung render is simulated with a ``threading.Event`` the test controls; the time limit is
passed in (a fraction of a second), never the 60 s default. A Python thread cannot be killed:
the slot of a stuck render stays taken until its thread ends, then it is free again.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable, Iterator
from uuid import uuid4

import pytest
from app.config import Settings
from app.services import render_slots
from app.services.readiness import _check_render_slots
from app.sheets import print_service as sps

pytestmark = pytest.mark.anyio

SHORT_S = 0.05  # the injected time limit
WAIT_S = 5.0  # bound of every wait on the test's own events


async def _until(cond: Callable[[], bool]) -> None:
    async with asyncio.timeout(WAIT_S):
        while not cond():
            await asyncio.sleep(0.01)


class _Hang:
    """A render that blocks until the test releases it."""

    def __init__(self) -> None:
        self.entered = threading.Semaphore(0)
        self.release = threading.Event()
        self.ended: list[int] = []

    def __call__(self, n: int, *_: object) -> int:
        self.entered.release()
        self.release.wait(WAIT_S)
        self.ended.append(n)
        return n


@pytest.fixture
def hang() -> Iterator[_Hang]:
    h = _Hang()
    yield h
    h.release.set()  # never leave a thread blocked behind a failed assertion


async def test_a_render_past_its_limit_raises_and_keeps_its_slot_until_the_thread_ends(
    hang: _Hang,
) -> None:
    with pytest.raises(render_slots.RenderTimeoutError):
        await render_slots.render_bounded(hang, 1, label="t", owner=None, timeout_s=SHORT_S)
    # The thread draws on: its slot stays taken and it counts as stuck.
    assert render_slots.stuck_renders() == 1
    assert render_slots.free_slots() == render_slots.MAX_CONCURRENT_RENDERS - 1
    hang.release.set()
    await _until(lambda: render_slots.stuck_renders() == 0)
    assert hang.ended == [1]
    assert render_slots.free_slots() == render_slots.MAX_CONCURRENT_RENDERS


async def test_with_every_slot_stuck_a_render_is_refused_at_once(hang: _Hang) -> None:
    """F2: no thread beyond the cap, and no caller waiting for a slot that may never free."""
    for n in range(render_slots.MAX_CONCURRENT_RENDERS):
        with pytest.raises(render_slots.RenderTimeoutError):
            await render_slots.render_bounded(hang, n, label="t", owner=None, timeout_s=SHORT_S)
    assert render_slots.stuck_renders() == render_slots.MAX_CONCURRENT_RENDERS
    started: list[int] = []
    async with asyncio.timeout(WAIT_S / 10):  # refused at once, not after the limit
        with pytest.raises(render_slots.RenderUnavailableError):
            await render_slots.render_bounded(
                lambda: started.append(1), label="t", owner=None, timeout_s=WAIT_S
            )
    assert started == []
    hang.release.set()
    await _until(lambda: render_slots.stuck_renders() == 0)
    assert (
        await render_slots.render_bounded(lambda: 7, label="t", owner=None, timeout_s=WAIT_S) == 7
    )


async def test_waiting_for_a_slot_ends_at_the_time_limit(hang: _Hang) -> None:
    """F2: the slots are busy, not stuck: a caller waits at most its limit for one."""
    busy = [
        asyncio.create_task(
            render_slots.render_bounded(hang, n, label="t", owner=None, timeout_s=WAIT_S)
        )
        for n in range(render_slots.MAX_CONCURRENT_RENDERS)
    ]
    for _ in busy:
        assert await asyncio.to_thread(hang.entered.acquire, True, WAIT_S)
    assert render_slots.free_slots() == 0 and render_slots.stuck_renders() == 0
    with pytest.raises(render_slots.RenderUnavailableError):
        await render_slots.render_bounded(lambda: 1, label="t", owner=None, timeout_s=SHORT_S)
    hang.release.set()
    assert await asyncio.gather(*busy) == [0, 1]
    assert render_slots.free_slots() == render_slots.MAX_CONCURRENT_RENDERS


async def test_a_failing_on_start_gives_its_slot_back() -> None:
    """F3: an exception between taking the slot and starting the thread leaks no slot."""

    def boom() -> None:
        raise RuntimeError("on_start")

    with pytest.raises(RuntimeError, match="on_start"):
        await render_slots.render_bounded(lambda: 1, label="t", owner=None, on_start=boom)
    assert render_slots.free_slots() == render_slots.MAX_CONCURRENT_RENDERS
    assert render_slots.gate().locked() is False
    for _ in range(render_slots.MAX_CONCURRENT_RENDERS + 1):  # every slot can still be taken
        assert await render_slots.render_bounded(lambda: 2, label="t", owner=None) == 2


async def test_one_owner_cannot_hang_every_slot(hang: _Hang) -> None:
    """F1: an owner with a stuck render gets no further slot; another owner renders on."""
    mine, theirs = uuid4(), uuid4()
    with pytest.raises(render_slots.RenderTimeoutError):
        await render_slots.render_bounded(hang, 1, label="t", owner=mine, timeout_s=SHORT_S)
    started: list[int] = []
    with pytest.raises(render_slots.OwnerRenderStuckError):
        await render_slots.render_bounded(
            lambda: started.append(1), label="t", owner=mine, timeout_s=WAIT_S
        )
    assert started == []
    assert render_slots.free_slots() == 1  # one slot stuck, one free
    assert await render_slots.render_bounded(lambda: 3, label="t", owner=theirs) == 3
    hang.release.set()
    await _until(lambda: render_slots.stuck_renders() == 0)
    assert await render_slots.render_bounded(lambda: 4, label="t", owner=mine) == 4


async def test_an_owner_with_a_stuck_render_is_refused_without_waiting_for_a_slot(
    hang: _Hang,
) -> None:
    """F1: refused at once, even while the other slot is busy (not after the wait limit)."""
    mine = uuid4()
    with pytest.raises(render_slots.RenderTimeoutError):
        await render_slots.render_bounded(hang, 1, label="t", owner=mine, timeout_s=SHORT_S)
    busy = asyncio.create_task(
        render_slots.render_bounded(hang, 2, label="t", owner=None, timeout_s=WAIT_S)
    )
    await _until(lambda: render_slots.free_slots() == 0)
    async with asyncio.timeout(WAIT_S / 10):
        with pytest.raises(render_slots.OwnerRenderStuckError):
            await render_slots.render_bounded(lambda: 3, label="t", owner=mine, timeout_s=WAIT_S)
    hang.release.set()
    assert await busy == 2
    await _until(lambda: render_slots.stuck_renders() == 0)


async def test_a_keys_second_render_waits_for_its_turn_and_never_gets_a_second_slot(
    hang: _Hang,
) -> None:
    """Round 2, ruling 1: a key holds at most ``OWNER_LIMIT`` slots, running or stuck. Its next
    render waits for the key's own turn (at most its limit) and is refused there, even after
    the other slot became free."""
    mine = uuid4()
    other = _Hang()
    try:
        first = asyncio.create_task(
            render_slots.render_bounded(hang, 1, label="t", owner=mine, timeout_s=0.2)
        )
        busy = asyncio.create_task(
            render_slots.render_bounded(other, 2, label="t", owner=None, timeout_s=WAIT_S)
        )
        await _until(lambda: render_slots.free_slots() == 0)
        waiting = asyncio.create_task(
            render_slots.render_bounded(lambda: 3, label="t", owner=mine, timeout_s=0.6)
        )
        with pytest.raises(render_slots.RenderTimeoutError):
            await first
        other.release.set()  # a slot is free now, but not for ``mine``
        assert await busy == 2
        with pytest.raises(render_slots.RenderUnavailableError):
            await waiting
        assert render_slots.free_slots() == render_slots.MAX_CONCURRENT_RENDERS - 1
    finally:
        other.release.set()
    hang.release.set()
    await _until(lambda: render_slots.stuck_renders() == 0)
    assert render_slots.free_slots() == render_slots.MAX_CONCURRENT_RENDERS
    assert render_slots.owner_gates() == 0


async def test_two_renders_of_one_key_started_together_never_take_every_slot(
    hang: _Hang,
) -> None:
    """Round 2, ruling 1 (TOCTOU, P1): two hanging renders of one key that start before either
    is stuck. One starts, the other never starts a thread; one slot stays free for others."""
    key = uuid4()
    results = await asyncio.gather(
        render_slots.render_bounded(hang, 1, label="preview", owner=key, timeout_s=0.2),
        render_slots.render_bounded(hang, 2, label="page job", owner=key, timeout_s=0.2),
        return_exceptions=True,
    )
    kinds = sorted(type(r).__name__ for r in results)
    assert kinds == ["RenderTimeoutError", "RenderUnavailableError"]
    assert render_slots.stuck_renders() == 1
    assert render_slots.free_slots() == render_slots.MAX_CONCURRENT_RENDERS - 1
    assert await render_slots.render_bounded(lambda: 3, label="t", owner=uuid4()) == 3
    hang.release.set()
    await _until(lambda: render_slots.stuck_renders() == 0)
    assert hang.ended == [1] or hang.ended == [2]  # only one thread ever ran
    assert render_slots.owner_gates() == 0


async def test_a_preview_and_a_page_job_of_one_key_started_together_leave_a_slot(
    hang: _Hang, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round 2, ruling 1: the preview path and the page-job path share the key's limit."""
    from app.services.page_jobs import render_page

    from tests.helpers.page_jobs import RecordingHandler, payload, registered

    monkeypatch.setattr(sps, "_draw_page", hang)
    key = uuid4()

    async def preview() -> object:
        with sps.preview_slot(key, key):
            return await sps.draw_page_bounded(1, timeout_s=0.2)

    with registered(RecordingHandler(), render=lambda _p: hang(2)):
        results = await asyncio.gather(
            preview(),
            render_slots.render_bounded(
                render_page, payload(), label="page job", owner=key, timeout_s=0.2
            ),
            return_exceptions=True,
        )
    timeouts = (render_slots.RenderTimeoutError, sps.RenderTimeoutApiError)
    refusals = (render_slots.RenderUnavailableError, sps.RenderUnavailableApiError)
    assert sum(isinstance(r, timeouts) for r in results) == 1, results
    assert sum(isinstance(r, refusals) for r in results) == 1, results
    assert render_slots.stuck_renders() == 1
    assert render_slots.free_slots() == render_slots.MAX_CONCURRENT_RENDERS - 1
    hang.release.set()
    await _until(lambda: render_slots.stuck_renders() == 0)
    assert len(hang.ended) == 1


async def test_a_cancelled_callers_hanging_render_counts_as_stuck(hang: _Hang) -> None:
    """Round 2, ruling 2 (P3): the render is marked stuck by a timer started with the thread.
    A caller that went away before the limit leaves a render that readiness still counts,
    and that still locks its key."""
    key = uuid4()
    task = asyncio.create_task(
        render_slots.render_bounded(hang, 1, label="t", owner=key, timeout_s=0.1)
    )
    assert await asyncio.to_thread(hang.entered.acquire, True, WAIT_S)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert render_slots.stuck_renders() == 0  # not yet past its limit
    await _until(lambda: render_slots.stuck_renders() == 1)
    check = _check_render_slots()
    assert check.metric == {"stuck": 1, "slots": render_slots.MAX_CONCURRENT_RENDERS}
    with pytest.raises(render_slots.OwnerRenderStuckError):
        await render_slots.render_bounded(lambda: 2, label="t", owner=key)
    hang.release.set()
    await _until(lambda: render_slots.stuck_renders() == 0)
    assert render_slots.free_slots() == render_slots.MAX_CONCURRENT_RENDERS


async def test_a_normal_render_is_never_marked_stuck() -> None:
    """The timer is cancelled at the end of the thread."""
    assert await render_slots.render_bounded(lambda: 1, label="t", owner=None, timeout_s=0.05) == 1
    await asyncio.sleep(0.1)
    assert render_slots.stuck_renders() == 0


async def test_per_owner_semaphores_are_dropped_when_unused() -> None:
    for _ in range(20):
        assert await render_slots.render_bounded(lambda: 1, label="t", owner=uuid4()) == 1
    assert render_slots.owner_gates() == 0


async def test_with_three_slots_a_stuck_group_render_keeps_its_group_place_until_the_end(
    hang: _Hang, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G6 (reviewer's test): with 3 slots and an owner limit of 2, one group render stuck, then
    two group renders started together: one runs (and hangs), the other is refused, one slot
    stays free. Freeing the group's place at the timeout would let both start."""
    monkeypatch.setattr(render_slots, "MAX_CONCURRENT_RENDERS", 3)
    monkeypatch.setattr(render_slots, "OWNER_LIMIT", 2)
    monkeypatch.setattr(render_slots, "NO_KEY_STUCK_LIMIT", 2)
    monkeypatch.setattr(render_slots, "_slots", None)
    no_key = render_slots.owner_of(None)
    with pytest.raises(render_slots.RenderTimeoutError):
        await render_slots.render_bounded(hang, 1, label="t", owner=no_key, timeout_s=SHORT_S)
    results = await asyncio.gather(
        render_slots.render_bounded(hang, 2, label="t", owner=no_key, timeout_s=0.2),
        render_slots.render_bounded(hang, 3, label="t", owner=no_key, timeout_s=0.2),
        return_exceptions=True,
    )
    kinds = sorted(type(r).__name__ for r in results)
    assert kinds == ["RenderTimeoutError", "RenderUnavailableError"]
    assert render_slots.stuck_renders() == 2
    assert render_slots.free_slots() == 1
    hang.release.set()
    await _until(lambda: render_slots.stuck_renders() == 0)
    assert render_slots.free_slots() == 3


async def test_callers_without_a_key_can_hang_at_most_all_but_one_slot(
    hang: _Hang,
) -> None:
    """``NO_KEY`` may hold at most ``MAX_CONCURRENT_RENDERS - 1`` stuck renders: past that a
    caller without a key is refused at once (503), and one slot is always left that the
    group cannot hang; a key renders on it. Keys stay locked per key."""
    no_key = render_slots.owner_of(None)
    assert render_slots.NO_KEY_STUCK_LIMIT == render_slots.MAX_CONCURRENT_RENDERS - 1
    assert await render_slots.render_bounded(lambda: 1, label="t", owner=no_key) == 1
    for n in range(render_slots.NO_KEY_STUCK_LIMIT):
        with pytest.raises(render_slots.RenderTimeoutError):
            await render_slots.render_bounded(hang, n, label="t", owner=no_key, timeout_s=SHORT_S)
    started: list[int] = []
    async with asyncio.timeout(WAIT_S / 10):  # at once
        with pytest.raises(render_slots.RenderUnavailableError):
            await render_slots.render_bounded(
                lambda: started.append(1), label="t", owner=no_key, timeout_s=WAIT_S
            )
    assert started == []
    assert render_slots.free_slots() == 1  # the slot the group cannot hang
    key = uuid4()
    assert await render_slots.render_bounded(lambda: 2, label="t", owner=key) == 2
    with pytest.raises(render_slots.RenderTimeoutError):
        await render_slots.render_bounded(hang, 3, label="t", owner=key, timeout_s=SHORT_S)
    with pytest.raises(render_slots.OwnerRenderStuckError):
        await render_slots.render_bounded(lambda: 4, label="t", owner=key)
    hang.release.set()
    await _until(lambda: render_slots.stuck_renders() == 0)
    assert await render_slots.render_bounded(lambda: 5, label="t", owner=no_key) == 5


async def test_a_caller_without_a_key_waits_for_the_group_at_most_its_limit(
    hang: _Hang,
) -> None:
    """The group's slot is held by a render that got stuck while the next caller waited: that
    caller is refused at its limit, never handed a second slot of the group."""
    no_key = render_slots.owner_of(None)
    first = asyncio.create_task(
        render_slots.render_bounded(hang, 1, label="t", owner=no_key, timeout_s=0.1)
    )
    assert await asyncio.to_thread(hang.entered.acquire, True, WAIT_S)
    waiting = asyncio.create_task(
        render_slots.render_bounded(lambda: 2, label="t", owner=no_key, timeout_s=0.5)
    )
    with pytest.raises(render_slots.RenderTimeoutError):
        await first
    with pytest.raises(render_slots.RenderUnavailableError):
        await waiting
    assert render_slots.free_slots() == render_slots.MAX_CONCURRENT_RENDERS - 1
    hang.release.set()
    await _until(lambda: render_slots.stuck_renders() == 0)
    assert render_slots.free_slots() == render_slots.MAX_CONCURRENT_RENDERS


async def test_two_concurrent_renders_without_a_key_never_take_every_slot(hang: _Hang) -> None:
    """TOCTOU: two callers without a key that start at the same time, before either is stuck,
    must not both hold a slot. The second waits for the group's slot (at most the limit) and
    is refused; at no point are all slots taken by the group, a key always gets one."""
    no_key = render_slots.owner_of(None)
    first = asyncio.create_task(
        render_slots.render_bounded(hang, 1, label="t", owner=no_key, timeout_s=WAIT_S)
    )
    second = asyncio.create_task(
        render_slots.render_bounded(hang, 2, label="t", owner=no_key, timeout_s=0.2)
    )
    assert await asyncio.to_thread(hang.entered.acquire, True, WAIT_S)
    with pytest.raises(render_slots.RenderUnavailableError):
        await second
    assert not hang.entered.acquire(False)  # the second never started a thread
    assert render_slots.free_slots() == render_slots.MAX_CONCURRENT_RENDERS - 1
    assert await render_slots.render_bounded(lambda: 3, label="t", owner=uuid4()) == 3
    hang.release.set()
    assert await first == 1
    assert render_slots.free_slots() == render_slots.MAX_CONCURRENT_RENDERS
    # The group's slot is free again once the thread ended.
    assert await render_slots.render_bounded(lambda: 4, label="t", owner=no_key) == 4


async def test_renders_without_a_key_run_one_after_another(hang: _Hang) -> None:
    """A second caller without a key waits for the first to end, then renders."""
    no_key = render_slots.owner_of(None)
    first = asyncio.create_task(
        render_slots.render_bounded(hang, 1, label="t", owner=no_key, timeout_s=WAIT_S)
    )
    assert await asyncio.to_thread(hang.entered.acquire, True, WAIT_S)
    second = asyncio.create_task(
        render_slots.render_bounded(lambda: 2, label="t", owner=no_key, timeout_s=WAIT_S)
    )
    await asyncio.sleep(0.05)
    assert not second.done()
    hang.release.set()
    assert await first == 1
    assert await second == 2
    assert render_slots.free_slots() == render_slots.MAX_CONCURRENT_RENDERS


async def test_ui_user_b_gets_503_while_ui_user_a_has_a_stuck_render_and_a_key_previews(
    hang: _Hang, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Preview path: A keeps its own preview slot (429), B without a key gets 503
    ``render-unavailable`` at once, a key previews on the slot the group cannot hang."""
    monkeypatch.setattr(sps, "_draw_page", hang)
    no_key = render_slots.owner_of(None)
    user_a, user_b = ("ui", "a", "ip-a"), ("ui", "b", "ip-b")
    with pytest.raises(sps.RenderTimeoutApiError), sps.preview_slot(user_a, no_key):
        await sps.draw_page_bounded(1, timeout_s=SHORT_S)
    monkeypatch.setattr(sps, "_draw_page", lambda n: n * 10)
    with pytest.raises(sps.TooManyPreviewsError), sps.preview_slot(user_a, no_key):
        pass
    with pytest.raises(sps.RenderUnavailableApiError) as caught, sps.preview_slot(user_b, no_key):
        await sps.draw_page_bounded(2, timeout_s=WAIT_S)
    assert caught.value.to_http().status_code == 503
    key = uuid4()
    with sps.preview_slot(key, key):
        assert await sps.draw_page_bounded(3, timeout_s=WAIT_S) == 30
    hang.release.set()
    await _until(lambda: render_slots.stuck_renders() == 0)


def test_callers_without_a_key_are_one_owner() -> None:
    key = uuid4()
    assert render_slots.owner_of(key) == key
    assert render_slots.owner_of(None) == render_slots.owner_of(None) == render_slots.NO_KEY


@pytest.mark.parametrize("value", ["0", "-1", "601", "inf", "nan"])
def test_the_render_timeout_setting_is_bounded(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """F4: no way to switch the limit off (``inf``) or to make it absurd."""
    import pydantic

    monkeypatch.setenv("LABELYARD_RENDER_TIMEOUT_S", value)
    with pytest.raises(pydantic.ValidationError, match="render_timeout_s"):
        Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.mark.parametrize("value", ["0.5", "60", "600"])
def test_the_render_timeout_setting_accepts_sane_values(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LABELYARD_RENDER_TIMEOUT_S", value)
    assert Settings(_env_file=None).render_timeout_s == float(value)  # type: ignore[call-arg]


async def test_a_normal_render_is_unaffected() -> None:
    assert await render_slots.render_bounded(lambda a, b: a + b, 2, 3, label="t", owner=None) == 5
    assert render_slots.stuck_renders() == 0
    assert render_slots.free_slots() == render_slots.MAX_CONCURRENT_RENDERS


async def test_a_render_error_is_still_raised_and_frees_its_slot() -> None:
    def broken() -> None:
        raise ValueError("bug")

    with pytest.raises(ValueError, match="bug"):
        await render_slots.render_bounded(broken, label="t", owner=None, timeout_s=WAIT_S)
    assert render_slots.free_slots() == render_slots.MAX_CONCURRENT_RENDERS


async def test_one_warning_per_stuck_render_without_payload(
    hang: _Hang, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger=render_slots.__name__)
    secret = "ZQX-private-label-text"
    with pytest.raises(render_slots.RenderTimeoutError):
        await render_slots.render_bounded(
            hang, 1, secret, label="page job J (sheet_page)", owner=None, timeout_s=SHORT_S
        )
    warnings = [r for r in caplog.records if "exceeded" in r.getMessage()]
    assert len(warnings) == 1
    assert "page job J (sheet_page)" in warnings[0].getMessage()
    assert all(secret not in r.getMessage() for r in caplog.records)
    hang.release.set()
    await _until(lambda: render_slots.stuck_renders() == 0)


async def test_without_an_explicit_limit_the_setting_applies(
    hang: _Hang, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert Settings.model_fields["render_timeout_s"].default == 60.0
    monkeypatch.setattr(render_slots, "default_timeout_s", lambda: SHORT_S)
    with pytest.raises(render_slots.RenderTimeoutError):
        await render_slots.render_bounded(hang, 1, label="t", owner=None)
    hang.release.set()
    await _until(lambda: render_slots.stuck_renders() == 0)


# ---------------------------------------------------------------------------- preview


async def test_a_preview_past_its_limit_is_a_504_and_keeps_the_key_slot_until_the_thread_ends(
    hang: _Hang, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A key whose render hangs keeps its preview slot until the thread ends: otherwise one key
    could hang every render slot by retrying and block all other callers."""
    monkeypatch.setattr(sps, "_draw_page", hang)
    key = uuid4()
    with pytest.raises(sps.RenderTimeoutApiError) as caught, sps.preview_slot(key):
        await sps.draw_page_bounded(1, timeout_s=SHORT_S)
    http = caught.value.to_http()
    assert http.status_code == 504
    assert http.detail["error_code"] == "render-timeout"  # type: ignore[index]
    with pytest.raises(sps.TooManyPreviewsError), sps.preview_slot(key):  # still drawing
        pass
    assert render_slots.stuck_renders() == 1
    hang.release.set()
    await _until(lambda: render_slots.stuck_renders() == 0)
    assert key not in sps._previews_in_progress  # freed once, at the thread's end
    with sps.preview_slot(key):
        pass


async def test_a_key_with_a_stuck_render_cannot_take_the_other_slot_but_another_key_can(
    hang: _Hang, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sps, "_draw_page", hang)
    key_a, key_b = uuid4(), uuid4()
    with pytest.raises(sps.RenderTimeoutApiError), sps.preview_slot(key_a):
        await sps.draw_page_bounded(1, timeout_s=SHORT_S)
    monkeypatch.setattr(sps, "_draw_page", lambda n: n * 10)
    with pytest.raises(sps.TooManyPreviewsError), sps.preview_slot(key_a):
        await sps.draw_page_bounded(2, timeout_s=WAIT_S)
    assert render_slots.free_slots() == 1  # key A holds one slot only
    with sps.preview_slot(key_b):
        assert await sps.draw_page_bounded(3, timeout_s=WAIT_S) == 30
    hang.release.set()
    await _until(lambda: key_a not in sps._previews_in_progress)
    with sps.preview_slot(key_a):
        assert await sps.draw_page_bounded(4, timeout_s=WAIT_S) == 40


# ---------------------------------------------------------------------------- readiness


async def test_readiness_shows_stuck_renders_and_fails_when_every_slot_is_stuck(
    hang: _Hang,
) -> None:
    assert _check_render_slots().status == "ok"
    with pytest.raises(render_slots.RenderTimeoutError):
        await render_slots.render_bounded(hang, 1, label="t", owner=None, timeout_s=SHORT_S)
    one = _check_render_slots()
    assert one.status == "ok"
    assert one.metric == {"stuck": 1, "slots": render_slots.MAX_CONCURRENT_RENDERS}
    with pytest.raises(render_slots.RenderTimeoutError):
        await render_slots.render_bounded(hang, 2, label="t", owner=None, timeout_s=SHORT_S)
    every = _check_render_slots()
    assert every.status == "fail"
    assert every.metric == {"stuck": 2, "slots": render_slots.MAX_CONCURRENT_RENDERS}
    hang.release.set()
    await _until(lambda: render_slots.stuck_renders() == 0)
    assert _check_render_slots().status == "ok"


# ---------------------------------------------------------------------------- sharing


async def test_a_running_page_job_does_not_starve_previews(
    hang: _Hang, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Page jobs and previews share the slots: while a page job draws, previews that do not
    hang run one after another on the other slot, and each frees its slot when it ends."""
    from app.services.page_jobs import render_page

    from tests.helpers.page_jobs import RecordingHandler, payload, registered

    with registered(RecordingHandler(), render=lambda _p: hang(0)):
        job = asyncio.create_task(
            render_slots.render_bounded(
                render_page, payload(), label="page job", owner=None, timeout_s=WAIT_S
            )
        )
        assert await asyncio.to_thread(hang.entered.acquire, True, WAIT_S)
        monkeypatch.setattr(sps, "_draw_page", lambda n: n)
        for n in range(5):
            async with asyncio.timeout(WAIT_S):
                with sps.preview_slot(uuid4()):
                    assert await sps.draw_page_bounded(n, timeout_s=WAIT_S) == n
            assert render_slots.free_slots() == 1  # the page job's slot, and only it, is taken
        hang.release.set()
        await job
    assert render_slots.free_slots() == render_slots.MAX_CONCURRENT_RENDERS


async def test_every_caller_names_its_owner() -> None:
    """T9b: an owner left out meant no per-owner limit at all. The argument has no default, so a
    new caller has to name the owner (``owner_of``) or say ``None`` on purpose."""
    with pytest.raises(TypeError, match="owner"):
        await render_slots.render_bounded(lambda: 1, label="t")  # type: ignore[call-arg]


async def test_an_on_end_that_raises_is_logged_and_does_not_escape_the_callback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """T9b: ``on_end`` runs in the task's done callback. An exception there went to the loop's
    handler and skipped retrieving the render's own exception; it is now logged by type."""
    loop = asyncio.get_running_loop()
    escaped: list[dict[str, object]] = []
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: escaped.append(context))

    def bad_end() -> None:
        raise RuntimeError("on_end broke")

    try:
        with caplog.at_level(logging.ERROR, logger="app.services.render_slots"):
            assert (
                await render_slots.render_bounded(lambda: 3, label="t", owner=None, on_end=bad_end)
                == 3
            )
            await asyncio.sleep(0)  # the done callback has run
    finally:
        loop.set_exception_handler(previous)
    assert escaped == []
    assert any("RuntimeError" in r.getMessage() for r in caplog.records), caplog.records
