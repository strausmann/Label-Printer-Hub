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
        await render_slots.render_bounded(hang, 1, label="t", timeout_s=SHORT_S)
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
            await render_slots.render_bounded(hang, n, label="t", timeout_s=SHORT_S)
    assert render_slots.stuck_renders() == render_slots.MAX_CONCURRENT_RENDERS
    started: list[int] = []
    async with asyncio.timeout(WAIT_S / 10):  # refused at once, not after the limit
        with pytest.raises(render_slots.RenderUnavailableError):
            await render_slots.render_bounded(
                lambda: started.append(1), label="t", timeout_s=WAIT_S
            )
    assert started == []
    hang.release.set()
    await _until(lambda: render_slots.stuck_renders() == 0)
    assert await render_slots.render_bounded(lambda: 7, label="t", timeout_s=WAIT_S) == 7


async def test_waiting_for_a_slot_ends_at_the_time_limit(hang: _Hang) -> None:
    """F2: the slots are busy, not stuck: a caller waits at most its limit for one."""
    busy = [
        asyncio.create_task(render_slots.render_bounded(hang, n, label="t", timeout_s=WAIT_S))
        for n in range(render_slots.MAX_CONCURRENT_RENDERS)
    ]
    for _ in busy:
        assert await asyncio.to_thread(hang.entered.acquire, True, WAIT_S)
    assert render_slots.free_slots() == 0 and render_slots.stuck_renders() == 0
    with pytest.raises(render_slots.RenderUnavailableError):
        await render_slots.render_bounded(lambda: 1, label="t", timeout_s=SHORT_S)
    hang.release.set()
    assert await asyncio.gather(*busy) == [0, 1]
    assert render_slots.free_slots() == render_slots.MAX_CONCURRENT_RENDERS


async def test_a_failing_on_start_gives_its_slot_back() -> None:
    """F3: an exception between taking the slot and starting the thread leaks no slot."""

    def boom() -> None:
        raise RuntimeError("on_start")

    with pytest.raises(RuntimeError, match="on_start"):
        await render_slots.render_bounded(lambda: 1, label="t", on_start=boom)
    assert render_slots.free_slots() == render_slots.MAX_CONCURRENT_RENDERS
    assert render_slots.gate().locked() is False
    for _ in range(render_slots.MAX_CONCURRENT_RENDERS + 1):  # every slot can still be taken
        assert await render_slots.render_bounded(lambda: 2, label="t") == 2


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
    busy = asyncio.create_task(render_slots.render_bounded(hang, 2, label="t", timeout_s=WAIT_S))
    await _until(lambda: render_slots.free_slots() == 0)
    async with asyncio.timeout(WAIT_S / 10):
        with pytest.raises(render_slots.OwnerRenderStuckError):
            await render_slots.render_bounded(lambda: 3, label="t", owner=mine, timeout_s=WAIT_S)
    hang.release.set()
    assert await busy == 2
    await _until(lambda: render_slots.stuck_renders() == 0)


async def test_an_owner_that_gets_stuck_while_its_next_call_waits_is_refused(
    hang: _Hang,
) -> None:
    """F1: the check is repeated once the slot is taken (the owner got stuck meanwhile)."""
    mine = uuid4()
    other = _Hang()  # the busy render, released on its own
    try:
        first = asyncio.create_task(
            render_slots.render_bounded(hang, 1, label="t", owner=mine, timeout_s=0.3)
        )
        busy = asyncio.create_task(
            render_slots.render_bounded(other, 2, label="t", timeout_s=WAIT_S)
        )
        await _until(lambda: render_slots.free_slots() == 0)
        waiting = asyncio.create_task(
            render_slots.render_bounded(lambda: 3, label="t", owner=mine, timeout_s=WAIT_S)
        )
        with pytest.raises(render_slots.RenderTimeoutError):
            await first  # ``mine`` is stuck now; ``waiting`` is still in the queue
        other.release.set()  # the busy render ends and hands its slot to ``waiting``
        with pytest.raises(render_slots.OwnerRenderStuckError):
            await waiting
        assert await busy == 2
        assert render_slots.free_slots() == render_slots.MAX_CONCURRENT_RENDERS - 1
    finally:
        other.release.set()
    hang.release.set()
    await _until(lambda: render_slots.stuck_renders() == 0)
    assert render_slots.free_slots() == render_slots.MAX_CONCURRENT_RENDERS


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


async def test_a_caller_without_a_key_waiting_for_a_slot_is_refused_once_the_group_is_full(
    hang: _Hang,
) -> None:
    """The group limit is checked again once the slot is taken (it filled while waiting)."""
    no_key = render_slots.owner_of(None)
    other = _Hang()
    try:
        first = asyncio.create_task(
            render_slots.render_bounded(hang, 1, label="t", owner=no_key, timeout_s=0.3)
        )
        busy = asyncio.create_task(
            render_slots.render_bounded(other, 2, label="t", owner=uuid4(), timeout_s=WAIT_S)
        )
        await _until(lambda: render_slots.free_slots() == 0)
        waiting = asyncio.create_task(
            render_slots.render_bounded(lambda: 3, label="t", owner=no_key, timeout_s=WAIT_S)
        )
        with pytest.raises(render_slots.RenderTimeoutError):
            await first
        other.release.set()
        with pytest.raises(render_slots.RenderUnavailableError):
            await waiting
        assert await busy == 2
    finally:
        other.release.set()
    hang.release.set()
    await _until(lambda: render_slots.stuck_renders() == 0)
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

    monkeypatch.setenv("PRINTER_HUB_RENDER_TIMEOUT_S", value)
    with pytest.raises(pydantic.ValidationError, match="render_timeout_s"):
        Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.mark.parametrize("value", ["0.5", "60", "600"])
def test_the_render_timeout_setting_accepts_sane_values(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRINTER_HUB_RENDER_TIMEOUT_S", value)
    assert Settings(_env_file=None).render_timeout_s == float(value)  # type: ignore[call-arg]


async def test_a_normal_render_is_unaffected() -> None:
    assert await render_slots.render_bounded(lambda a, b: a + b, 2, 3, label="t") == 5
    assert render_slots.stuck_renders() == 0
    assert render_slots.free_slots() == render_slots.MAX_CONCURRENT_RENDERS


async def test_a_render_error_is_still_raised_and_frees_its_slot() -> None:
    def broken() -> None:
        raise ValueError("bug")

    with pytest.raises(ValueError, match="bug"):
        await render_slots.render_bounded(broken, label="t", timeout_s=WAIT_S)
    assert render_slots.free_slots() == render_slots.MAX_CONCURRENT_RENDERS


async def test_one_warning_per_stuck_render_without_payload(
    hang: _Hang, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger=render_slots.__name__)
    secret = "ZQX-private-label-text"
    with pytest.raises(render_slots.RenderTimeoutError):
        await render_slots.render_bounded(
            hang, 1, secret, label="page job J (sheet_page)", timeout_s=SHORT_S
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
        await render_slots.render_bounded(hang, 1, label="t")
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
        await render_slots.render_bounded(hang, 1, label="t", timeout_s=SHORT_S)
    one = _check_render_slots()
    assert one.status == "ok"
    assert one.metric == {"stuck": 1, "slots": render_slots.MAX_CONCURRENT_RENDERS}
    with pytest.raises(render_slots.RenderTimeoutError):
        await render_slots.render_bounded(hang, 2, label="t", timeout_s=SHORT_S)
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
            render_slots.render_bounded(render_page, payload(), label="page job", timeout_s=WAIT_S)
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
