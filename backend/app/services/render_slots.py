"""The process-wide render slots: CPU-bound page drawing in a thread, bounded and timed (#293).

The sheet preview (``_draw_page``) and the page-job render (``render_page``) both draw in a
worker thread. At most ``MAX_CONCURRENT_RENDERS`` such threads run at once in the process.

A slot is held until its thread has really ended, not until the caller stops waiting (266-07):
a slot freed early would let the next caller start one thread more than the cap. A Python
thread cannot be killed, so a render that exceeds its time limit is reported to its caller as
``RenderTimeoutError`` while its thread keeps the slot. Such a render counts as *stuck* until
the thread ends; the count is logged and shown by the readiness check ``render_slots``.

Stuck renders are counted per API key (``owner_of``). A key with a stuck render gets no
further slot (``OwnerRenderStuckError``), so one key cannot hang every slot by sending hanging
input again. Callers without a key (``NO_KEY``: browser sessions, SSO, the hub itself) share
one owner, so a per-owner lock would let one user lock every user out. Instead the group may
hold at most ``NO_KEY_STUCK_LIMIT`` (all slots but one) stuck renders; past that a caller
without a key is refused at once (``RenderUnavailableError``), and one slot is always left
that the group cannot hang.

Accepted risk: several *different* keys can each hang one render and so take every slot.
Keys are issued by an admin; a key that does this is revoked, and the hub restarted.

Waiting for a slot is bounded too: with every slot stuck a caller is refused at once,
otherwise it waits at most the time limit (``RenderUnavailableError``).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from typing import Any, Final
from uuid import UUID

from app.config import get_settings

__all__ = [
    "MAX_CONCURRENT_RENDERS",
    "NO_KEY",
    "NO_KEY_STUCK_LIMIT",
    "OwnerRenderStuckError",
    "RenderTimeoutError",
    "RenderUnavailableError",
    "free_slots",
    "owner_of",
    "render_bounded",
    "stuck_renders",
]

logger = logging.getLogger(__name__)

MAX_CONCURRENT_RENDERS: Final = 2  # renders at once, process-wide (spec 18, CPU)
NO_KEY: Final = "no-key"
"""The owner of every render without an API key (browser sessions, SSO, the hub itself).
Not locked per owner, but bounded by ``NO_KEY_STUCK_LIMIT`` (see the module docstring)."""
NO_KEY_STUCK_LIMIT: Final = MAX_CONCURRENT_RENDERS - 1
"""Stuck renders the callers without a key may hold together: one slot always stays theirs
to lose, never the last."""


class RenderTimeoutError(Exception):
    """The render ran longer than its time limit; its thread still holds its slot."""


class RenderUnavailableError(Exception):
    """No slot was free in time: every slot is stuck, or the wait reached the time limit."""


class OwnerRenderStuckError(Exception):
    """The owner has a stuck render already; it gets no further slot until that one ends."""


@dataclass
class _Slots:
    gate: asyncio.Semaphore
    loop: asyncio.AbstractEventLoop
    in_use: int = 0
    stuck: int = 0
    stuck_by_owner: dict[Hashable, int] = field(default_factory=dict)


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


def owner_of(api_key_id: UUID | None) -> Hashable:
    """The render owner of a caller: its API key, or ``NO_KEY`` for every caller without one."""
    return NO_KEY if api_key_id is None else api_key_id


def stuck_renders() -> int:
    """Renders past their time limit whose thread has not ended yet (0 without a loop)."""
    slots = _slots
    return 0 if slots is None else slots.stuck


def free_slots() -> int:
    """Slots no render holds right now (``MAX_CONCURRENT_RENDERS`` without a loop)."""
    slots = _slots
    return MAX_CONCURRENT_RENDERS if slots is None else MAX_CONCURRENT_RENDERS - slots.in_use


def _refusal(slots: _Slots, owner: Hashable | None) -> Exception | None:
    """Why ``owner`` gets no slot now: a key with a stuck render, or the group without a key
    at its limit. ``None``: it may render."""
    if owner is None:
        return None
    stuck = slots.stuck_by_owner.get(owner, 0)
    if owner == NO_KEY:
        return RenderUnavailableError() if stuck >= NO_KEY_STUCK_LIMIT else None
    return OwnerRenderStuckError() if stuck else None


def default_timeout_s() -> float:
    return get_settings().render_timeout_s


async def render_bounded[T](
    fn: Callable[..., T],
    *args: Any,
    label: str,
    owner: Hashable | None = None,
    timeout_s: float | None = None,
    on_start: Callable[[], None] | None = None,
    on_end: Callable[[], None] | None = None,
) -> T:
    """``fn(*args)`` in a thread under a render slot, within ``timeout_s`` seconds.

    ``label`` names the render in the log (an id and a kind, never payload data). ``owner``
    (see ``owner_of``) is refused with ``OwnerRenderStuckError`` while it has a stuck render;
    ``NO_KEY`` with ``RenderUnavailableError`` once it holds ``NO_KEY_STUCK_LIMIT`` of them.
    With every slot stuck the call raises ``RenderUnavailableError`` at once; otherwise it
    waits at most ``timeout_s`` for a slot (then the same error). ``on_start`` runs when the
    slot is taken, ``on_end`` once the thread has ended (both on the event loop, without an
    await in between). Raises ``RenderTimeoutError`` past the limit; the thread keeps its slot
    until it ends.
    """
    limit = default_timeout_s() if timeout_s is None else timeout_s
    slots = _current()
    refused = _refusal(slots, owner)
    if refused is not None:
        raise refused
    if slots.stuck >= MAX_CONCURRENT_RENDERS:
        raise RenderUnavailableError()
    try:
        await asyncio.wait_for(slots.gate.acquire(), limit)
    except TimeoutError:
        raise RenderUnavailableError() from None
    # No await from the acquire to the callback: the slot is always given back by the task.
    slots.in_use += 1
    refused = _refusal(slots, owner)
    if refused is not None:  # the owner got stuck, or the group full, while this call waited
        slots.in_use -= 1
        slots.gate.release()
        raise refused
    state = {"stuck": False}
    try:
        if on_start is not None:
            on_start()
    except BaseException:
        slots.in_use -= 1
        slots.gate.release()
        raise
    task = asyncio.ensure_future(asyncio.to_thread(fn, *args))

    def _end(done: asyncio.Future[Any]) -> None:
        slots.in_use -= 1
        slots.gate.release()
        if state["stuck"]:
            slots.stuck -= 1
            if owner is not None:
                left = slots.stuck_by_owner.get(owner, 0) - 1
                if left > 0:
                    slots.stuck_by_owner[owner] = left
                else:
                    slots.stuck_by_owner.pop(owner, None)
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
        if owner is not None:
            slots.stuck_by_owner[owner] = slots.stuck_by_owner.get(owner, 0) + 1
        logger.warning(
            "Render %s exceeded %ss; its thread keeps a render slot until it ends "
            "(%d of %d slots stuck)",
            label,
            limit,
            slots.stuck,
            MAX_CONCURRENT_RENDERS,
        )
        raise RenderTimeoutError() from None
