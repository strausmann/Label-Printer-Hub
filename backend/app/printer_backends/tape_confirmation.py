# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""How a tape printer confirms that the labels it was sent are printed (#393).

Two channels, both measured on a QL-820NWB and a PT-P750W:

- **IPP.** The printer takes the unchanged Brother raster bytes as an IPP Print-Job with
  ``document-format: application/octet-stream`` and reports the job's state: ``9`` completed,
  ``8`` aborted, ``7`` canceled, with ``job-impressions-completed`` as the printed count.
- **Label counter.** ``prtMarkerLifeCount`` (SNMP, unit sheets) counts single labels. Read before
  sending and polled after it, it says how many labels came out.

Which channel works for a printer is decided by a test print and stored with the printer
(``ConfirmationRecord``); a printer without a record is probed once per backend instance.
TCP 9100 (``raw``) stays the transport of every printer without IPP: the counter confirms it.

``TapeIppTransport`` is the IPP side, ``TapeSendState`` the bookkeeping a backend keeps between
sending and the check after sending (``post_send.check_after_send``).
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import math
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, Literal

import httpx

from app.printer_backends.exceptions import (
    PrintFailedError,
    TapeLabelTooLongError,
    refused_before_sending,
)
from app.printer_backends.ipp.client import IppClient
from app.printer_backends.ipp.codec import Attr, Tag
from app.printer_backends.ipp.errors import (
    IppError,
    IppNotFoundError,
    IppStatusError,
    IppUnreachableError,
)

_logger = logging.getLogger(__name__)

CONFIRM_BASE_S: Final = 15.0
"""First value: seconds every confirmation may take on top of the labels (a printer that wakes
up, the first cut). The timeout is ``CONFIRM_BASE_S + labels * CONFIRM_PER_LABEL_S``."""

CONFIRM_PER_LABEL_S: Final = 8.0
"""First value: seconds per label sent. Measured: a QL-820NWB prints a 62 mm x 17 mm label in
about 3 s, a PT-P750W a 12 mm label in about 7 s; 8 s covers both."""

TAPE_MIN_SPEED_MM_S: Final = 20.0
"""Millimetres of tape per second the confirmation wait assumes on top of the per-label time
(R26-2): a long label takes as long as its length needs. The slowest model the hub drives is the
PT-P750W, with a data-sheet print speed of up to 30 mm/s; 20 mm/s leaves a third as margin (a
cold head, a low battery, a slower firmware). The QL printers are faster, so they are covered."""

CONFIRM_PRINTING_FACTOR: Final = 2.0
"""While the printer still reports ``printing`` (``hrPrinterStatus``, or IPP job state 5) at the
end of the wait, the wait goes on, up to this many times the computed wait (R26-2). The hard
bound keeps a printer that reports ``printing`` for ever from holding the queue."""

CONFIRM_POLL_S: Final = 1.0
"""Seconds between two reads of the IPP job state or the label counter."""

CANCEL_STOP_S: Final = 10.0
"""First value: seconds a cancelled IPP job may take to reach its stop point (Cancel-Job is
asynchronous: the printer reports ``processing-to-stop-point`` first)."""

COUNTER_JUMP_SLACK: Final = 50
"""A counter that rose by more than the labels sent plus this is not ours to interpret (another
sender, a replaced printer): it is accepted as printed with a warning."""

COUNTER_REFUSALS_TO_STOP: Final = 3
"""Reads in a row whose agent refused the label counter (noSuchName, noSuchObject,
noSuchInstance) before the hub stops asking for it (R26-1). A printer without the counter refuses
every read, so it is found within the first three reads of a print (the check after sending
reads about once a second); a single forged or garbled answer on the network no longer switches
the confirmation off. Asking a printer without the counter costs one extra SNMP request per read,
three times."""

COUNTER_RETRY_S: Final = 3600.0
"""Seconds after which a counter the hub stopped asking for is asked for again (R26-1): a
printer that answers it again, or an attacker who has left, does not keep the confirmation off
until a restart. Every test print asks again at once."""

STORE_TIMEOUT_S: Final = 10.0
"""Seconds one write of the confirmation record may take (review round 4, L3). Writes are
serialised per printer, so a write stuck on a locked database would hold every later writer
(status reads, the end of a test print); it is given up and logged instead. A SQLite commit of
one row takes milliseconds; ten seconds is far above any busy wait of the hub's database.

The timeout bounds the wait, not a call already running inside SQLite (#398): a statement that
waits on a locked database runs in the driver's thread and is not interrupted by the cancel;
there the bound is SQLite's busy timeout (5000 ms, ``app/db/engine.py``). A write that is given
up or fails is stored again by the next status read (``TapeSendState.flush``)."""

IPP_PORT: Final = 631
IPP_PATH: Final = "/ipp/print"
OCTET_STREAM: Final = "application/octet-stream"
_PROBE_ATTRIBUTES = (
    "ipp-versions-supported",
    "document-format-supported",
    "operations-supported",
    "printer-state",
)
_CANCEL_JOB: Final = 0x0008
_GET_JOB_ATTRIBUTES: Final = 0x0009
_IPP_STATE_COMPLETED = 9
_IPP_STATE_PROCESSING = 5
_IPP_STATE_FINAL = 7

ConfirmTransport = Literal["ipp", "raw"]


def _monotonic() -> float:
    """The clock of the counter retry window (a test replaces it)."""
    return time.monotonic()


def confirm_timeout_s(labels: int, length_mm: float = 0.0) -> float:
    """How long the printer has to confirm *labels* labels of *length_mm* tape in all (R26-2)."""
    return (
        CONFIRM_BASE_S
        + max(0, labels) * CONFIRM_PER_LABEL_S
        + max(0.0, length_mm) / TAPE_MIN_SPEED_MM_S
    )


def check_label_lengths(lengths_mm: list[float], max_mm: int) -> None:
    """Refuse before sending when a label is longer than the tape allows (R26-2).

    Raises ``TapeLabelTooLongError`` (``nothing_sent``) for the first label over *max_mm*.
    """
    for length in lengths_mm:
        if length > max_mm:
            raise refused_before_sending(
                TapeLabelTooLongError(length_mm=math.ceil(length), max_mm=max_mm)
            )


def label_length_mm(image: Any, dpi: int) -> float:
    """The length of tape a rendered label takes: its long side at *dpi* (R26-2).

    The long side is the length on every tape layout but a short label across a wide roll, where
    it is the width; that overestimates, which only makes the wait longer.
    """
    width, height = image.size
    return float(max(width, height)) * 25.4 / dpi


# ---------------------------------------------------------------------------- the record


@dataclass(frozen=True)
class ConfirmationRecord:
    """What a test print found out about a tape printer (#393), stored with the printer.

    ``confirm_transport``: ``ipp`` only when the test label went out as an IPP Print-Job and
    reached job state 9, else ``raw`` (TCP 9100). ``label_counter``: the label counter rose by
    exactly the labels sent. ``confirmed_at``: when the test print found it.
    ``ipp_incomplete``: the printer took an IPP job of a test print but did not complete it
    (aborted, canceled, no final state, forgotten). A later test print then stays on TCP 9100;
    after a Print-Job the printer did not take (unreachable, a refusal) it tries IPP again.
    ``counter_off``: the hub currently does not read the label counter, because the printer
    refused it ``COUNTER_REFUSALS_TO_STOP`` times in a row since (R26-1); the channel is then
    ``none`` until the counter answers again or a test print re-decides.
    """

    confirm_transport: ConfirmTransport
    label_counter: bool
    confirmed_at: datetime
    ipp_incomplete: bool = False
    counter_off: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "confirm_transport": self.confirm_transport,
            "label_counter": self.label_counter,
            "confirmed_at": self.confirmed_at.isoformat(),
            "ipp_incomplete": self.ipp_incomplete,
            "counter_off": self.counter_off,
        }

    @classmethod
    def from_json(cls, data: object) -> ConfirmationRecord | None:
        """The record stored in *data*; ``None`` for no record or one this code cannot read."""
        if not isinstance(data, Mapping):
            return None
        transport = data.get("confirm_transport")
        counter = data.get("label_counter")
        at = data.get("confirmed_at")
        incomplete = data.get("ipp_incomplete", False)  # absent in records before the field
        counter_off = data.get("counter_off", False)
        if transport not in ("ipp", "raw") or not isinstance(counter, bool):
            return None
        if not isinstance(incomplete, bool) or not isinstance(counter_off, bool):
            return None
        if not isinstance(at, str):
            return None
        try:
            confirmed_at = datetime.fromisoformat(at)
        except ValueError:
            return None
        if confirmed_at.tzinfo is None:
            confirmed_at = confirmed_at.replace(tzinfo=UTC)
        return cls(
            confirm_transport=transport,
            label_counter=counter,
            confirmed_at=confirmed_at,
            ipp_incomplete=incomplete,
            counter_off=counter_off,
        )

    @property
    def channel(self) -> Literal["ipp", "label_counter", "none"]:
        """How this printer's prints are confirmed: IPP job state, label counter, or not at all."""
        if self.confirm_transport == "ipp":
            return "ipp"
        return "label_counter" if self.label_counter and not self.counter_off else "none"


RecordSink = Callable[[ConfirmationRecord], Awaitable[None]]


# ---------------------------------------------------------------------------- IPP


@dataclass(frozen=True)
class IppOutcome:
    """How the IPP jobs of one send ended: ``completed`` all of them, else ``printed`` labels.

    ``pending``: the job that had no final state at the timeout (it may still print; the caller
    cancels it). ``vanished``: the printer no longer knew a job it had answered for before (some
    printers drop finished jobs quickly), so the label counter decides.
    """

    completed: bool
    printed: int
    pending: int | None = None
    vanished: bool = False
    # For a ``pending`` job: its labels, and the labels of the completed jobs before it.
    pending_labels: int = 0
    printed_before: int = 0


@dataclass(frozen=True)
class CancelOutcome:
    """How a Cancel-Job of a job without a final state ended (#393).

    ``cancelled``: the job reached a final state after the cancel; ``impressions`` is its last
    ``job-impressions-completed`` (a label finished on the way to the stop point counts).
    ``vanished``: the printer no longer knows the job (it may have finished and been purged),
    so the label counter decides. ``failed``: the cancel was not taken or the job did not stop
    within ``CANCEL_STOP_S``: the labels may still print.
    """

    result: Literal["cancelled", "vanished", "failed"]
    impressions: int | None = None


class TapeIppTransport:
    """IPP Print-Job of Brother raster bytes to ``ipp://<host>:631/ipp/print`` (#393).

    Plain ``ipp://`` is HTTP, so there is no TLS to verify; the client is built with its
    defaults like every other IPP client of the hub. One client per request (the client keeps
    no connection alive anyway).
    """

    def __init__(
        self,
        host: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        query_timeout_s: float = 5.0,
        upload_timeout_s: float = 30.0,
    ) -> None:
        bracketed = f"[{host}]" if ":" in host and not host.startswith("[") else host
        self.uri = f"ipp://{bracketed}:{IPP_PORT}{IPP_PATH}"
        self._transport = transport
        self._query_timeout_s = query_timeout_s
        self._upload_timeout_s = upload_timeout_s

    def _client(self, upload_timeout_s: float | None = None) -> IppClient:
        return IppClient(
            self.uri,
            transport=self._transport,
            query_timeout_s=self._query_timeout_s,
            upload_timeout_s=self._upload_timeout_s
            if upload_timeout_s is None
            else upload_timeout_s,
        )

    async def offers_raster(self) -> bool:
        """Get-Printer-Attributes answers, lists ``application/octet-stream`` and can follow and
        stop a job.

        An ``operations-supported`` that lacks Get-Job-Attributes or Cancel-Job means 9100: the
        hub could take the job but never confirm or cancel it. A printer that does not report
        ``operations-supported`` is taken at its word (RFC 8011 makes both operations required).
        Raises ``IppError`` when the printer does not answer as an IPP printer.
        """
        async with self._client() as client:
            attrs = await client.get_printer_attributes(_PROBE_ATTRIBUTES)
        formats = attrs.get("document-format-supported") or []
        if not any(isinstance(f, str) and f.lower() == OCTET_STREAM for f in formats):
            return False
        operations = attrs.get("operations-supported")
        if operations:
            ids = {op for op in operations if isinstance(op, int) and not isinstance(op, bool)}
            if not {_CANCEL_JOB, _GET_JOB_ATTRIBUTES} <= ids:
                _logger.info("Tape printer cannot follow or cancel an IPP job; using TCP 9100")
                return False
        return True

    async def submit(self, data: bytes, labels: int = 1, length_mm: float = 0.0) -> int:
        """Send *data* (*labels* labels) as one Print-Job; returns the printer's job id.

        ``job-name`` is unique per send. The upload may take as long as the labels may take to
        print (an embedded server can throttle the upload while it prints), at least the
        default. Raises the client's ``IppError``s.
        """
        job_name = f"labelyard-tape-{uuid.uuid4().hex[:16]}"
        op_attrs = [
            Attr("job-name", Tag.NAME, [job_name]),
            Attr("document-format", Tag.MIME, [OCTET_STREAM]),
        ]
        upload_s = max(self._upload_timeout_s, confirm_timeout_s(labels, length_mm))
        async with self._client(upload_s) as client:
            accepted = await client.print_job(data, [], op_attrs)
        return accepted.job_id

    async def cancel(self, job_id: int, *, poll_s: float | None = None) -> CancelOutcome:
        """Best-effort Cancel-Job, then poll the job until it reached a final state.

        Logged, never raises. See ``CancelOutcome`` for what each result means.
        """
        poll = CONFIRM_POLL_S if poll_s is None else poll_s
        loop = asyncio.get_running_loop()
        impressions: int | None = None
        async with self._client() as client:
            try:
                await client.cancel_job(job_id)
            except IppNotFoundError:
                _logger.warning("IPP job gone before its cancel; the label counter decides")
                return CancelOutcome("vanished")
            except IppError as exc:
                _logger.warning("IPP job could not be cancelled (%s)", type(exc).__name__)
                return CancelOutcome("failed")
            # The deadline is checked after each Get-Job, so the real limit is CANCEL_STOP_S plus
            # one Get-Job timeout (``query_timeout_s``). A Get-Job error other than not-found is
            # retried until then and ends "failed", i.e. outcome_unknown: on purpose, a job we
            # cannot see stop may still print.
            deadline = loop.time() + CANCEL_STOP_S
            while True:
                try:
                    info = await client.get_job(job_id)
                except IppNotFoundError:
                    _logger.warning("Cancelled IPP job gone; the label counter decides")
                    return CancelOutcome("vanished")
                except IppError as exc:
                    _logger.warning("Cancelled IPP job not readable (%s)", type(exc).__name__)
                    info = None
                if info is not None:
                    if info.impressions_completed is not None:
                        impressions = max(0, info.impressions_completed)
                    if info.state >= _IPP_STATE_FINAL:
                        _logger.info("IPP job that was not confirmed in time cancelled")
                        return CancelOutcome("cancelled", impressions)
                if loop.time() >= deadline:
                    _logger.warning("Cancelled IPP job did not reach its stop point in time")
                    return CancelOutcome("failed", impressions)
                await asyncio.sleep(poll)

    async def wait(
        self,
        jobs: list[tuple[int, int]],
        *,
        timeout_s: float,
        poll_s: float = CONFIRM_POLL_S,
        hard_timeout_s: float | None = None,
    ) -> IppOutcome:
        """Poll each ``(job_id, labels)`` until a final state (``>= 7``) or the timeout.

        A job that still reports ``processing`` (5) at the timeout is polled on until
        *hard_timeout_s* (R26-2: a long label is not cancelled while it prints).

        ``9`` counts the job's labels as printed. ``7``/``8`` stop the wait with the labels of
        the completed jobs plus the failed job's last ``job-impressions-completed``. At the
        timeout the job still open is ``pending``. A job the printer answers ``not found`` for
        after it was seen once is ``vanished`` (the counter decides). Other errors are retried
        until the timeout. Never raises.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        hard_deadline = loop.time() + max(timeout_s, hard_timeout_s or 0.0)
        printed = 0
        async with self._client() as client:
            for job_id, labels in jobs:
                state: int | None = None
                impressions = 0
                seen = False
                while True:
                    try:
                        info = await client.get_job(job_id)
                    except IppNotFoundError:
                        if seen:
                            _logger.info("IPP job no longer known; the label counter decides")
                            return IppOutcome(False, printed, vanished=True)
                        info = None
                    except IppError as exc:
                        _logger.warning("IPP job state not readable (%s)", type(exc).__name__)
                        info = None
                    if info is not None:
                        seen = True
                        state = info.state
                        # Run 26, hardening note 7: a negative count is clamped here, at the
                        # source, not only by every consumer.
                        impressions = max(0, info.impressions_completed or impressions)
                        if info.state >= _IPP_STATE_FINAL:
                            if info.state == _IPP_STATE_COMPLETED:
                                printed += labels
                                break
                            return IppOutcome(False, printed + min(impressions, labels))
                    now = loop.time()
                    if now >= deadline and (state != _IPP_STATE_PROCESSING or now >= hard_deadline):
                        return IppOutcome(
                            False,
                            printed + min(impressions, labels),
                            pending=job_id,
                            pending_labels=labels,
                            printed_before=printed,
                        )
                    await asyncio.sleep(poll_s)
        return IppOutcome(True, printed)


# ---------------------------------------------------------------------------- per backend


@dataclass
class TapeSendState:
    """What a tape backend keeps from sending to the check after sending (#393).

    ``record`` is the stored detection (``None``: none yet; the probe decides). ``sink`` stores a
    new record (the runtime writes it to the printer row). ``labels_sent`` counts the labels sent
    since the read before sending; ``ipp_jobs`` the IPP jobs of those sends. ``detecting``: the
    current send is a test print that decides the record. ``detect_ipp_failed``: its Print-Job
    was not taken; ``detect_ipp_taken``: one of its IPP jobs was; ``detect_ipp_skipped``: it
    did not try IPP because an earlier test print's IPP job did not complete
    (``ConfirmationRecord.ipp_incomplete``).
    """

    host: str
    ipp: TapeIppTransport
    record: ConfirmationRecord | None = None
    sink: RecordSink | None = None
    labels_sent: int = 0
    ipp_jobs: list[tuple[int, int]] = field(default_factory=list)
    detecting: bool = False
    detect_ipp_failed: bool = False
    detect_ipp_taken: bool = False
    detect_ipp_skipped: bool = False
    # R26-2: the tape length of the labels sent since the read before sending, in mm.
    length_mm: float = 0.0
    # R26-1: refusals of the label counter in a row, and since when it is not asked for.
    counter_refusals: int = 0
    counter_off_at: float | None = None
    _counter_streak_at: float | None = None
    _probed: bool | None = None
    _probe_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _store_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # #398: ``record`` is newer than what the sink last stored (a write failed, or the record
    # was changed in memory only); the next status read stores it (``flush``).
    _unstored: bool = False
    # #398 (review I-2): the store ``flush`` started; it runs beside the status read.
    _flush_task: asyncio.Task[None] | None = None

    def load(self, record: ConfirmationRecord | None) -> None:
        """Take the record stored with the printer, when the backend is wired (#398, finding 4).

        A new backend asks for the label counter (its gate starts open), so a stored
        ``counter_off`` is stale: it is cleared in memory and stored by the first status read.
        Synchronous, like the wiring that calls it.
        """
        self.record = record
        self._reopen_counter_in_record()

    def _reopen_counter_in_record(self) -> None:
        if self.record is not None and self.record.counter_off:
            self.record = dataclasses.replace(self.record, counter_off=False)
            self._unstored = True

    async def flush(self) -> None:
        """Start storing ``record`` again if the last write of it did not reach the sink (#398).

        Both backends call it at the start of every status read, so a write that failed (a busy
        database), was given up or was only made in memory is stored at the next read, which
        is the next print or test print. It never waits on the database (review I-2): the
        write runs as a task beside the read, and nothing is started while a write of this
        printer is still running, so a busy database cannot make the preflight or the polls of
        a confirmation wait slower, nor stack up writes.
        """
        if not self._unstored or self.record is None or self.sink is None:
            return
        if self._store_lock.locked() or (
            self._flush_task is not None and not self._flush_task.done()
        ):
            return
        self._flush_task = asyncio.create_task(self._write(None))

    async def flushed(self) -> None:
        """Wait for the write ``flush`` started, if one runs (tests; ``close`` bounds it)."""
        if self._flush_task is not None:
            await asyncio.shield(self._flush_task)

    async def close(self, timeout_s: float | None = None) -> None:
        """Let a write ``flush`` started finish before the backend goes away (#398, review N-1).

        The runtime calls it when it detaches the printer and when the hub stops, so no write
        is left to run against a disposed database engine. Bounded by *timeout_s* (default
        ``STORE_TIMEOUT_S``); a write still running then is cancelled and awaited, so no task
        is left pending.
        """
        task = self._flush_task
        if task is None or task.done():
            return
        try:
            async with asyncio.timeout(STORE_TIMEOUT_S if timeout_s is None else timeout_s):
                await asyncio.shield(task)
        except TimeoutError:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            _logger.warning(
                "The print confirmation of a printer was not stored before it was detached"
            )
        except asyncio.CancelledError:
            task.cancel()  # the caller gave up waiting: the write does not outlive the backend
            raise

    def begin(self, *, detect: bool = False) -> None:
        """A new send starts (right after the read before sending)."""
        self.labels_sent = 0
        self.length_mm = 0.0
        self.ipp_jobs = []
        self.detecting = detect
        self.detect_ipp_failed = False
        self.detect_ipp_taken = False
        self.detect_ipp_skipped = False
        if detect:
            self.reset_counter_gate()

    def reset_counter_gate(self) -> None:
        """A test print re-decides everything, the label counter included (R26-1). The backend
        calls this before the test print's own read before sending (R3-2), so that read already
        asks for the counter; ``begin`` repeats it.

        A stored ``counter_off`` is cleared in memory at once and stored by the test print's own
        status read, which follows right away (#398, finding 3): a test print that is refused
        there leaves no "counter off" stored while the hub asks for the counter again.
        Synchronous, because ``begin`` is.
        """
        self.counter_refusals = 0
        self.counter_off_at = None
        self._counter_streak_at = None
        self._reopen_counter_in_record()

    def ask_counter(self) -> bool:
        """Whether the next status read asks for the label counter (R26-1).

        Once the retry window after a switch-off has passed, it is asked again. The refusals
        that switched it off do not count again: their streak began at least the window ago, so
        ``note_counter`` starts a fresh one (audit run 27, note 1).
        """
        return self.counter_off_at is None or _monotonic() - self.counter_off_at >= COUNTER_RETRY_S

    async def note_counter(self, *, refused: bool, answered: bool, asked: bool = True) -> None:
        """Count a read's answer for the label counter (R26-1).

        Only reads that *asked* for the counter count. *refused*: the agent refused it;
        ``COUNTER_REFUSALS_TO_STOP`` refusals in a row, within ``COUNTER_RETRY_S`` of the first,
        stop asking for it. Any other answer to the question (a count, or a value that is no
        count) ends the streak (review round 3, R3-6); a read that failed altogether never
        reaches here and counts neither way. *answered*: it returned a count, which also turns
        the counter back on. A change is stored in the record (``counter_off``), so the printer
        view shows it.
        """
        if not asked:
            return
        if refused:
            now = _monotonic()
            if (
                self._counter_streak_at is not None
                and now - self._counter_streak_at >= COUNTER_RETRY_S
            ):
                self.counter_refusals = 0  # a stale streak is not "in a row"
            if self.counter_refusals == 0:
                self._counter_streak_at = now
            self.counter_refusals += 1
            if self.counter_refusals < COUNTER_REFUSALS_TO_STOP:
                return
            if self.counter_off_at is None:
                _logger.warning(
                    "Tape printer refused the label counter %d times in a row; not asked for "
                    "%.0f s or until the next test print",
                    self.counter_refusals,
                    COUNTER_RETRY_S,
                )
            self.counter_off_at = now
            await self._mark_counter_off(True)
            return
        self.counter_refusals = 0
        self._counter_streak_at = None
        if answered:
            if self.counter_off_at is not None:
                _logger.info("Tape printer answers the label counter again")
            self.counter_off_at = None
            await self._mark_counter_off(False)

    async def _mark_counter_off(self, off: bool) -> None:
        if self.record is not None and self.record.counter_off != off:
            await self.store(dataclasses.replace(self.record, counter_off=off))

    async def use_ipp(self) -> bool:
        """Whether this send goes out over IPP.

        A test print tries IPP, also after a stored ``raw`` whose Print-Job the printer did not
        take (it may have been asleep or briefly unreachable; a refusal again falls back to 9100
        in the same send). Only after a stored ``raw`` whose IPP job the printer took but did
        not complete (``ipp_incomplete``) it goes over 9100 and the counter confirms it. Any
        other send follows the stored record; a stored ``raw`` is never overridden. Without a
        record the probe decides once per backend instance (cached); a failing probe means
        9100, logged once.
        """
        if self.detecting:
            if self.record is not None and self.record.ipp_incomplete:
                self.detect_ipp_skipped = True
                return False
            return True
        if self.record is not None:
            return self.record.confirm_transport == "ipp"
        if self._probed is None:
            async with self._probe_lock:
                if self._probed is None:
                    try:
                        self._probed = await self.ipp.offers_raster()
                    except IppError as exc:
                        _logger.info(
                            "Tape printer has no usable IPP (%s); sending over TCP 9100",
                            type(exc).__name__,
                        )
                        self._probed = False
                    except (OSError, httpx.HTTPError) as exc:
                        _logger.info(
                            "Tape printer has no usable IPP (%s); sending over TCP 9100",
                            type(exc).__name__,
                        )
                        self._probed = False
        return bool(self._probed)

    async def send(
        self,
        data: bytes,
        labels: int,
        raw: Callable[[], Awaitable[None]],
        length_mm: float = 0.0,
    ) -> None:
        """Send *labels* labels of raster *data*: over IPP when it is the transport, else *raw*.

        An IPP Print-Job the printer did not take (unreachable, a refusal status) sent nothing,
        so the same bytes go out over *raw*; in a test print that records IPP as not working.
        Any other IPP failure (the upload had begun, an unusable answer) may have printed: it
        raises ``PrintFailedError``. *raw* is the backend's 9100 send. An accepted job is never
        sent again over 9100.
        """
        if await self.use_ipp():
            try:
                job_id = await self.ipp.submit(data, labels, length_mm)
            except (IppUnreachableError, IppStatusError) as exc:
                # Not taken, so the same bytes go out over 9100. A refusal status (busy
                # included) is trusted to mean "nothing printed": a printer that lies, printing
                # and then refusing, gets a second copy. That is inside the trust the hub gives
                # its printers' answers (run 26, hardening note 6), like a forged status bit.
                _logger.warning(
                    "IPP Print-Job not taken (%s); sending over TCP 9100", type(exc).__name__
                )
                if self.detecting:
                    self.detect_ipp_failed = True
            except IppError as exc:
                # The upload had begun or the answer is unusable: the label may have printed.
                raise PrintFailedError(f"IPP print interrupted ({type(exc).__name__})") from exc
            else:
                self.ipp_jobs.append((job_id, labels))
                if self.detecting:
                    self.detect_ipp_taken = True
                self.labels_sent += labels
                self.length_mm += length_mm
                return
        await raw()
        self.labels_sent += labels
        self.length_mm += length_mm

    async def store(self, record: ConfirmationRecord) -> None:
        """Keep *record* and hand it to the sink; a failing sink is logged, never raised.

        Writes go to the sink one at a time, in the order they were made (audit run 27, R27-1):
        a slow write cannot commit after a later one and leave an outdated record stored. A
        write that fails, is given up or is cancelled marks the record unstored; the next status
        read stores it again (``flush``, #398 finding 2).
        """
        self.record = record
        if self.sink is None:
            return
        # Unstored until the write below succeeds, also when it is cancelled while it waits for
        # the lock (review M-1).
        self._unstored = True
        await self._write(record)

    async def _write(self, record: ConfirmationRecord | None) -> None:
        """Hand *record* to the sink under the store lock; ``None``: the record current when the
        lock is taken (``flush``, which must not write back an older one)."""
        sink = self.sink
        if sink is None:
            return
        async with self._store_lock:
            if record is None:
                record = self.record
                if record is None or not self._unstored:
                    return
            stored = False
            scope = asyncio.timeout(STORE_TIMEOUT_S)
            try:
                async with scope:
                    await sink(record)
                stored = True
            except TimeoutError:
                if scope.expired():
                    _logger.warning(
                        "The print confirmation of a printer was not stored in time (%.0f s); "
                        "it is stored again by the next status read",
                        STORE_TIMEOUT_S,
                    )
                else:  # #398, finding 7: the sink itself raised it
                    _logger.warning(
                        "The print confirmation of a printer could not be stored", exc_info=True
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                _logger.warning(
                    "The print confirmation of a printer could not be stored", exc_info=True
                )
            finally:
                if stored and self.record is record:  # a newer record in memory stays unstored
                    self._unstored = False
