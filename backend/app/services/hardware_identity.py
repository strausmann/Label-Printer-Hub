# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Hardware identity of the device behind a printer's address (#231).

A status probe reports every identity candidate it saw (``ObservedIdentity``). This module picks
the best one, compares it with the stored one and stores it when there is none:

- ``serial`` (SNMP ``prtGeneralSerialNumber``) beats ``ipp_uuid`` (IPP ``printer-uuid``) beats
  ``mac`` (``ifPhysAddress``), the weakest because it names a network card, not the device;
- the comparison is always on the **stored kind**: a stored MAC is compared with the observed
  MAC, so a different device that reports a serial is never mistaken for a better reading of
  the same one;
- a probe that reports nothing, or nothing of the stored kind, never changes the stored
  identity and never counts as a mismatch.

Identity values are never logged, at any level; outcomes are logged by kind only. A ``different``
reading is recorded beside the stored identity (never over it) and starts a mismatch; what a
mismatch does (the hold, the event) is the caller's, told through ``on_mismatch``.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.printer_backends.snmp_helper import ObservedIdentity
from app.repositories import printer_identity as repo

_log = logging.getLogger(__name__)

IdentityKind = Literal["serial", "ipp_uuid", "mac"]
IdentityOutcome = Literal["none", "stored", "seen", "kind_upgraded", "kept", "different"]
IdentitySink = Callable[[UUID, ObservedIdentity], Awaitable[IdentityOutcome]]
MismatchHook = Callable[[UUID, datetime | None], Awaitable[None]]
"""Called after a write that starts (``since``) or ends (``None``) a mismatch."""

# Lowest rank first: an identity is only ever replaced by a higher-ranked kind.
_RANK: dict[str, int] = {"mac": 0, "ipp_uuid": 1, "serial": 2}
_PICK_ORDER: tuple[IdentityKind, ...] = ("serial", "ipp_uuid", "mac")

# At most one write of ``hardware_id_seen_at`` per printer in this time for an unchanged identity.
SEEN_THROTTLE_S = 600
_MAX_ATTEMPTS = 3
_SERIAL_MAX = 128
_SERIAL_STRIP = " \t\r\n\x00"
_UUID_PREFIX = "urn:uuid:"
_HEX12 = re.compile(r"^[0-9a-f]{12}$")


@dataclass(frozen=True)
class HardwareIdentity:
    """One identity: what kind it is and its normalised value."""

    kind: IdentityKind
    value: str


def _serial(value: str | None) -> str | None:
    # Some agents pad the OCTET STRING with NULs.
    text = (value or "").strip(_SERIAL_STRIP)[:_SERIAL_MAX].strip(_SERIAL_STRIP)
    return text or None


def _uuid(value: str | None) -> str | None:
    text = (value or "").strip().lower()
    if text.startswith(_UUID_PREFIX):
        text = text[len(_UUID_PREFIX) :]
    return text.strip() or None


def _mac(value: str | None) -> str | None:
    digits = re.sub(r"[^0-9a-f]", "", (value or "").strip().lower())
    if not _HEX12.match(digits) or set(digits) == {"0"}:
        return None
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2))


def normalise(observed: ObservedIdentity) -> ObservedIdentity:
    """Clean every candidate: trimmed serial, bare lower-case uuid, ``aa:bb:..`` MAC."""
    return ObservedIdentity(
        serial=_serial(observed.serial),
        ipp_uuid=_uuid(observed.ipp_uuid),
        mac=_mac(observed.mac),
    )


def _value_of(observed: ObservedIdentity, kind: str) -> str | None:
    return {"serial": observed.serial, "ipp_uuid": observed.ipp_uuid, "mac": observed.mac}.get(kind)


def pick_identity(observed: ObservedIdentity) -> HardwareIdentity | None:
    """The best candidate: serial, then IPP uuid, then MAC; ``None`` when there is none."""
    return _pick(normalise(observed))


def _pick(clean: ObservedIdentity) -> HardwareIdentity | None:
    """``pick_identity`` for a candidate set that is already normalised."""
    for kind in _PICK_ORDER:
        value = _value_of(clean, kind)
        if value is not None:
            return HardwareIdentity(kind, value)
    return None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _session(session_factory: async_sessionmaker[AsyncSession] | None) -> AsyncSession:
    if session_factory is not None:
        return session_factory()
    from app.db.engine import async_session

    return async_session()


async def record_identity(
    printer_id: UUID,
    observed: ObservedIdentity,
    now: datetime,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    on_mismatch: MismatchHook | None = None,
) -> IdentityOutcome:
    """Store or compare the identity one successful probe saw; say what happened.

    - ``none``: the probe reported no usable identity; nothing is written.
    - ``stored``: nothing was stored yet; the best candidate is now.
    - ``seen``: the observed value of the stored kind equals the stored one.
    - ``kind_upgraded``: as ``seen``, and a higher-ranked kind was observed; it is stored now.
    - ``kept``: the stored kind was not observed this time; nothing is written.
    - ``different``: the observed value of the stored kind differs. The differing value is
      recorded next to the stored identity (``observed_*``, ``mismatch_since``); the stored
      identity is never replaced.

    A mismatch ends when the stored identity is seen again or a higher kind confirms it. A probe
    that reports nothing of the stored kind neither starts nor ends one.

    ``on_mismatch(printer_id, since)`` is called after the write that *starts* a mismatch
    (``since`` is its start) and after the one that *ends* it (``since`` is ``None``), never for
    a reading that leaves the state as it was. It receives no identity value.
    """
    clean = normalise(observed)
    picked = _pick(clean)
    if picked is None:
        return _done("none", None)
    lost_different = False
    for _attempt in range(_MAX_ATTEMPTS):
        async with _session(session_factory) as session:
            row = await repo.get(session, printer_id)
            if row is None:
                if await repo.insert(
                    session, printer_id, kind=picked.kind, value=picked.value, now=now
                ):
                    return _done("stored", picked.kind)
                continue  # a concurrent writer stored first: compare against that
            stored_kind, stored_value = row.hardware_id_kind, row.hardware_id
            if stored_kind is None or stored_value is None:  # a row without an identity yet
                if await repo.replace(
                    session,
                    printer_id,
                    expect_kind=stored_kind,
                    expect_value=stored_value,
                    kind=picked.kind,
                    value=picked.value,
                    now=now,
                ):
                    return _done("stored", picked.kind)
                continue
            observed_value = _value_of(clean, stored_kind)
            if observed_value is None:
                return _done("kept", stored_kind)
            was_mismatched = row.mismatch_since is not None
            if observed_value != stored_value:
                if (
                    was_mismatched
                    and row.observed_id == observed_value
                    and row.observed_kind == stored_kind
                ):
                    # Nothing new to record. Re-announce anyway: the hook is idempotent and
                    # restores a hold the caller lost while the database still says mismatch.
                    await _announce(on_mismatch, printer_id, row.mismatch_since)
                    return _done("different", stored_kind)
                if await repo.mark_mismatch(
                    session,
                    printer_id,
                    kind=stored_kind,
                    value=stored_value,
                    observed_kind=stored_kind,
                    observed_value=observed_value,
                    now=now,
                ):
                    if not was_mismatched:
                        await _announce(on_mismatch, printer_id, now)
                    return _done("different", stored_kind)
                lost_different = True  # the stored identity moved under us: compare again
                continue
            if _RANK.get(picked.kind, -1) > _RANK.get(stored_kind, -1):
                if await repo.replace(
                    session,
                    printer_id,
                    expect_kind=stored_kind,
                    expect_value=stored_value,
                    kind=picked.kind,
                    value=picked.value,
                    now=now,
                ):
                    if was_mismatched:
                        await _announce(on_mismatch, printer_id, None)
                    return _done("kind_upgraded", picked.kind)
                continue
            seen_at = row.hardware_id_seen_at
            stale = seen_at is None or (now - _aware(seen_at)).total_seconds() >= SEEN_THROTTLE_S
            if stale or was_mismatched:
                won = await repo.touch_seen(
                    session,
                    printer_id,
                    kind=stored_kind,
                    value=stored_value,
                    now=now,
                    clear_mismatch=was_mismatched,
                )
                if was_mismatched and won:
                    await _announce(on_mismatch, printer_id, None)
                elif was_mismatched:
                    continue  # the row changed under us: compare again
            return _done("seen", stored_kind)
    # Lost the race every time; the next probe compares again. A ``different`` reading whose
    # write kept losing is still ``different``: ``kept`` would say the stored kind was not seen.
    return _done("different" if lost_different else "kept", picked.kind)


async def _announce(hook: MismatchHook | None, printer_id: UUID, since: datetime | None) -> None:
    """Tell the caller a mismatch started (``since``) or ended (``None``); never raises."""
    if hook is None:
        return
    try:
        await hook(printer_id, since)
    except Exception as exc:
        _log.warning("identity mismatch hook failed (%s)", type(exc).__name__)


def _done(outcome: IdentityOutcome, kind: str | None) -> IdentityOutcome:
    _log.debug("hardware identity: %s (kind=%s)", outcome, kind)
    return outcome
