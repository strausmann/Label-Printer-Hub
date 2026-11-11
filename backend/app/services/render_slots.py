"""The process-wide render slots: CPU-bound page drawing in a thread, bounded and timed (#293).

The sheet preview (``_draw_page``) and the page-job render (``render_page``) both draw in a
worker thread. At most ``MAX_CONCURRENT_RENDERS`` such threads run at once in the process.

A slot is held until its thread has really ended, not until the caller stops waiting (266-07):
a slot freed early would let the next caller start one thread more than the cap. A Python
thread cannot be killed, so a render that exceeds its time limit is reported to its caller as
``RenderTimeoutError`` while its thread keeps the slot. Such a render counts as *stuck* until
the thread ends; the count is logged and shown by the readiness check ``render_slots``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from app.config import get_settings

__all__ = [
    "MAX_CONCURRENT_RENDERS",
    "RenderTimeoutError",
    "render_bounded",
    "stuck_renders",
]

logger = logging.getLogger(__name__)

MAX_CONCURRENT_RENDERS: Final = 2  # renders at once, process-wide (spec 18, CPU)


class RenderTimeoutError(Exception):
    """The render ran longer than its time limit; its thread still holds its slot."""


@dataclass
class _Slots:
    gate: asyncio.Semaphore
    loop: asyncio.AbstractEventLoop
    stuck: int = 0


_slots: _Slots | None = None


def _current() -> _Slots:
    """The slots of the running event loop; rebuilt if the loop changed (tests)."""
    global _slots
    loop = asyncio.get_running_loop()
    if _slots is None or _slots.loop is not loop:
        _slots = _Slots(asyncio.Semaphore(MAX_CONCURRENT_RENDERS), loop)
    return _slots


def gate() -> asyncio.Semaphore:
    """The semaphore behind the render slots (for tests and the sheet preview)."""
    return _current().gate


def stuck_renders() -> int:
    """Renders past their time limit whose thread has not ended yet (0 without a loop)."""
    slots = _slots
    return 0 if slots is None else slots.stuck


def default_timeout_s() -> float:
    return get_settings().render_timeout_s


async def render_bounded[T](
    fn: Callable[..., T],
    *args: Any,
    label: str,
    timeout_s: float | None = None,
    on_start: Callable[[], None] | None = None,
    on_end: Callable[[], None] | None = None,
    on_timeout: Callable[[], None] | None = None,
) -> T:
    """``fn(*args)`` in a thread under a render slot, within ``timeout_s`` seconds.

    ``label`` names the render in the log (an id and a kind, never payload data). ``on_start``
    runs when the slot is taken (not for a caller cancelled while waiting for one), ``on_end``
    once the thread has ended, ``on_timeout`` when the caller is answered with the time limit
    (all on the event loop, without an await in between). Raises ``RenderTimeoutError`` past
    the limit; the thread keeps its slot until it ends.
    """
    limit = default_timeout_s() if timeout_s is None else timeout_s
    slots = _current()
    await slots.gate.acquire()
    # No await from the acquire to the callback: the slot is always given back by the task.
    state = {"stuck": False}
    if on_start is not None:
        on_start()
    task = asyncio.ensure_future(asyncio.to_thread(fn, *args))

    def _end(done: asyncio.Future[Any]) -> None:
        slots.gate.release()
        if state["stuck"]:
            slots.stuck -= 1
            logger.info(
                "Stuck render %s ended; its slot is free (%d still stuck)", label, slots.stuck
            )
        if on_end is not None:
            on_end()
        if not done.cancelled():
            done.exception()  # retrieved: a render nobody waits for any more is not logged twice

    task.add_done_callback(_end)
    try:
        return await asyncio.wait_for(asyncio.shield(task), limit)
    except TimeoutError:
        if task.done():  # finished in the same instant: its result counts
            return task.result()
        state["stuck"] = True
        slots.stuck += 1
        logger.warning(
            "Render %s exceeded %ss; its thread keeps a render slot until it ends "
            "(%d of %d slots stuck)",
            label,
            limit,
            slots.stuck,
            MAX_CONCURRENT_RENDERS,
        )
        if on_timeout is not None:
            on_timeout()
        raise RenderTimeoutError() from None
