# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The process-wide render slots: CPU-bound page drawing in a thread, bounded and timed (#293).

The sheet preview (``_draw_page``) and the page-job render (``render_page``) both draw in a
worker thread. At most ``MAX_CONCURRENT_RENDERS`` such threads run at once in the process.

A slot is held until its thread has really ended, not until the caller stops waiting (266-07):
a slot freed early would let the next caller start one thread more than the cap. A Python
thread cannot be killed, so a render that exceeds its time limit is reported to its caller as
``RenderTimeoutError`` while its thread keeps the slot. Such a render counts as *stuck* until
the thread ends. It is marked stuck by a timer started with the thread, not by the caller, so
a render whose caller went away (a cancelled request) counts too. The count is logged and
shown by the readiness check ``render_slots``.

Every owner (``owner_of``: each API key, and one group ``NO_KEY`` for all callers without a
key: browser sessions, SSO, the hub itself) holds at most ``OWNER_LIMIT`` (all slots but
one) slots at once, counted from taking the slot to the end of the thread, running or stuck.
A semaphore of that size per owner (created when first needed, dropped when unused) is taken
before the slot, always in that order, and held until the thread ends. So no single owner can
hang every slot, not even with renders started at the same time. On top of that, a key with a
stuck render is refused at once (``OwnerRenderStuckError``), and the group without a key is
refused at once while ``OWNER_LIMIT`` of its renders are stuck (``RenderUnavailableError``).

Waiting is bounded: with every slot stuck a caller is refused at once, otherwise it waits at
most the time limit for its owner's turn and its slot together (``RenderUnavailableError``).

Accepted residual risk: with 2 slots, two *different* owners (two keys, or one key and one UI
user) can together hang every slot; a single party cannot. Keys are issued by an admin; such
a key is revoked and the hub restarted.

Known limitation (accepted): the callers without a key share one owner and so block each other.
While one of them renders, the next waits; while one render of theirs is stuck, every caller
without a key gets ``RenderUnavailableError`` until it ends or the hub restarts. Signed-in UI
users are trusted, and the keys keep their slot.
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
    "OWNER_LIMIT",
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
OWNER_LIMIT: Final = MAX_CONCURRENT_RENDERS - 1
"""Slots one owner may hold at once, running or stuck: never the last one."""
NO_KEY: Final = "no-key"
"""The owner of every render without an API key (browser sessions, SSO, the hub itself)."""
NO_KEY_STUCK_LIMIT: Final = OWNER_LIMIT
"""Stuck renders of the group without a key at which its callers are refused at once."""


class RenderTimeoutError(Exception):
    """The render ran longer than its time limit; its thread still holds its slot."""


class RenderUnavailableError(Exception):
    """No slot was free in time: every slot is stuck, or the wait reached the time limit."""


class OwnerRenderStuckError(Exception):
    """The owner has a stuck render already; it gets no further slot until that one ends."""


@dataclass
class _OwnerGate:
    sem: asyncio.Semaphore
    users: int = 0  # callers waiting for it or holding it; dropped at 0


@dataclass
class _Slots:
    gate: asyncio.Semaphore
    loop: asyncio.AbstractEventLoop
    in_use: int = 0
    stuck: int = 0
    stuck_by_owner: dict[Hashable, int] = field(default_factory=dict)
    owner_gates: dict[Hashable, _OwnerGate] = field(default_factory=dict)


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


def owner_gates() -> int:
    """Per-owner semaphores alive right now (each dropped once nobody uses it)."""
    slots = _slots
    return 0 if slots is None else len(slots.owner_gates)


def _refusal(slots: _Slots, owner: Hashable | None) -> Exception | None:
    """Why ``owner`` gets no slot now: a key with a stuck render, or the group without a key
    with ``NO_KEY_STUCK_LIMIT`` stuck renders. ``None``: it may try."""
    if owner is None:
        return None
    stuck = slots.stuck_by_owner.get(owner, 0)
    if owner == NO_KEY:
        return RenderUnavailableError() if stuck >= NO_KEY_STUCK_LIMIT else None
    return OwnerRenderStuckError() if stuck else None


async def _acquire_until(sem: asyncio.Semaphore, deadline: float) -> None:
    """Take ``sem`` by ``deadline`` (loop time), else ``RenderUnavailableError``."""
    remaining = deadline - asyncio.get_running_loop().time()
    try:
        await asyncio.wait_for(sem.acquire(), max(remaining, 0))
    except TimeoutError:
        raise RenderUnavailableError() from None


def default_timeout_s() -> float:
    return get_settings().render_timeout_s


async def render_bounded[T](
    fn: Callable[..., T],
    *args: Any,
    label: str,
    owner: Hashable | None,
    timeout_s: float | None = None,
    on_start: Callable[[], None] | None = None,
    on_end: Callable[[], None] | None = None,
) -> T:
    """``fn(*args)`` in a thread under a render slot, within ``timeout_s`` seconds.

    ``label`` names the render in the log (an id and a kind, never payload data). ``owner`` (see
    ``owner_of``; required, so no caller can forget it; ``None`` only on purpose, for a render
    no caller owns, which then has no per-owner limit) holds at most ``OWNER_LIMIT`` slots at
    once; a key with a stuck render is refused with ``OwnerRenderStuckError``, the group
    ``NO_KEY`` with ``RenderUnavailableError`` while ``NO_KEY_STUCK_LIMIT`` of its renders are
    stuck. With every slot stuck the call raises ``RenderUnavailableError`` at once; otherwise
    it waits at most ``timeout_s`` for its owner's turn and a slot (then the same error).
    ``on_start`` runs when the slot is taken, ``on_end`` once the thread has ended (both on the
    event loop, without an await in between). Raises ``RenderTimeoutError`` past the limit; the
    thread keeps its slot until it ends.
    """
    limit = default_timeout_s() if timeout_s is None else timeout_s
    slots = _current()
    loop = asyncio.get_running_loop()
    refused = _refusal(slots, owner)
    if refused is not None:
        raise refused
    if slots.stuck >= MAX_CONCURRENT_RENDERS:
        raise RenderUnavailableError()
    deadline = loop.time() + limit

    owner_gate: _OwnerGate | None = None
    if owner is not None:
        owner_gate = slots.owner_gates.get(owner)
        if owner_gate is None:
            owner_gate = slots.owner_gates[owner] = _OwnerGate(asyncio.Semaphore(OWNER_LIMIT))
        owner_gate.users += 1

    def _leave_owner() -> None:
        """This call no longer waits for or holds its owner's semaphore."""
        if owner_gate is None:
            return
        owner_gate.users -= 1
        if owner_gate.users == 0 and slots.owner_gates.get(owner) is owner_gate:
            del slots.owner_gates[owner]

    try:
        if owner_gate is not None:
            await _acquire_until(owner_gate.sem, deadline)
    except BaseException:
        _leave_owner()
        raise
    try:
        await _acquire_until(slots.gate, deadline)
    except BaseException:
        if owner_gate is not None:
            owner_gate.sem.release()
        _leave_owner()
        raise
    # No await from here to the callback: the slots are always given back by the task.
    slots.in_use += 1

    def _give_back() -> None:
        slots.in_use -= 1
        slots.gate.release()
        if owner_gate is not None:
            owner_gate.sem.release()
        _leave_owner()

    refused = _refusal(slots, owner)
    if refused is not None:  # the owner got stuck, or the group full, while this call waited
        _give_back()
        raise refused
    try:
        if on_start is not None:
            on_start()
    except BaseException:
        _give_back()
        raise
    state = {"stuck": False}

    def _mark_stuck() -> None:
        """The render passed its limit: counted as stuck until the thread ends (#293)."""
        if state["stuck"]:
            return
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

    task = asyncio.ensure_future(asyncio.to_thread(fn, *args))
    # Armed with the thread, not by the caller: a cancelled caller's render is counted too.
    timer = loop.call_later(limit, _mark_stuck)

    def _end(done: asyncio.Future[Any]) -> None:
        timer.cancel()
        _give_back()
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
            try:
                on_end()
            except Exception as exc:
                # A done callback must not raise: the loop would only log it, and the render's
                # own exception below would go unretrieved.
                logger.error("Render %s: on_end failed (%s)", label, type(exc).__name__)
        if not done.cancelled():
            done.exception()  # retrieved: a render nobody waits for any more is not logged twice

    task.add_done_callback(_end)
    try:
        return await asyncio.wait_for(asyncio.shield(task), limit)
    except TimeoutError:
        if task.done():  # finished in the same instant: its result counts
            return task.result()
        _mark_stuck()  # the timer may not have run yet; marking is idempotent
        timer.cancel()
        raise RenderTimeoutError() from None
