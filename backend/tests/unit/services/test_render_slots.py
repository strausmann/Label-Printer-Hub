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


def _free_slots() -> int:
    return render_slots.gate()._value


async def test_a_render_past_its_limit_raises_and_keeps_its_slot_until_the_thread_ends(
    hang: _Hang,
) -> None:
    with pytest.raises(render_slots.RenderTimeoutError):
        await render_slots.render_bounded(hang, 1, label="t", timeout_s=SHORT_S)
    # The thread draws on: its slot stays taken and it counts as stuck.
    assert render_slots.stuck_renders() == 1
    assert _free_slots() == render_slots.MAX_CONCURRENT_RENDERS - 1
    hang.release.set()
    await _until(lambda: render_slots.stuck_renders() == 0)
    assert hang.ended == [1]
    assert _free_slots() == render_slots.MAX_CONCURRENT_RENDERS


async def test_threads_stay_bounded_by_the_slots_while_renders_are_stuck(hang: _Hang) -> None:
    for n in range(render_slots.MAX_CONCURRENT_RENDERS):
        with pytest.raises(render_slots.RenderTimeoutError):
            await render_slots.render_bounded(hang, n, label="t", timeout_s=SHORT_S)
    assert render_slots.stuck_renders() == render_slots.MAX_CONCURRENT_RENDERS
    # A third render waits for a slot: it never starts a thread beyond the cap.
    third = asyncio.create_task(render_slots.render_bounded(lambda: 7, label="t", timeout_s=WAIT_S))
    await asyncio.sleep(0.05)
    assert not third.done()
    hang.release.set()
    assert await third == 7
    await _until(lambda: render_slots.stuck_renders() == 0)


async def test_a_normal_render_is_unaffected() -> None:
    assert await render_slots.render_bounded(lambda a, b: a + b, 2, 3, label="t") == 5
    assert render_slots.stuck_renders() == 0
    assert _free_slots() == render_slots.MAX_CONCURRENT_RENDERS


async def test_a_render_error_is_still_raised_and_frees_its_slot() -> None:
    def broken() -> None:
        raise ValueError("bug")

    with pytest.raises(ValueError, match="bug"):
        await render_slots.render_bounded(broken, label="t", timeout_s=WAIT_S)
    assert _free_slots() == render_slots.MAX_CONCURRENT_RENDERS


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
    assert _free_slots() == 1  # key A holds one slot only
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
            assert _free_slots() == 1  # the page job's slot, and only it, is taken
        hang.release.set()
        await job
    assert _free_slots() == render_slots.MAX_CONCURRENT_RENDERS
