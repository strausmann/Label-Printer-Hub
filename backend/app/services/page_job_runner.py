"""Sends, tracks and cancels one page job at an IPP printer (spec 11.3-11.5, OC-21, OC-23).

``PageJobRunner.run`` is awaited by the queue worker for one page job at a time (one hub job
at the printer). The sequence:

1. **Pre-flight** (OC-21): a live Get-Printer-Attributes *before* ``mark_printing``. Any IPP
   error, any blocking reason, or ``printer-is-accepting-jobs = false``
   raises ``Deferred``; the job never left ``queued`` (there is no ``PRINTING -> QUEUED``
   edge) and the queue holds it and pauses the printer.
2. ``mark_printing`` and ``result = {"phase": "uploading", "started": false}``.
3. Render the page from the payload (in a thread). A render error ends ``failed/render_failed``.
4. Print-Job. The error contract is in ``app.printer_backends.ipp.errors``: nothing sent or a
   refusal ends ``failed`` with ``started=False`` (``ipp_unreachable``, ``ipp_busy``,
   ``ipp_rejected``); an exchange that broke after the document went out, or an unusable
   answer, ends ``failed/interrupted`` with ``started=True`` persisted (the page may print).
5. Accepted: ``result`` gets the IPP job id; the id joins the printer's ``own_job_ids``.
6. Poll Get-Job-Attributes until a final state. ``started`` turns true at the first state
   5/6/9 or ``impressions_completed > 0`` and is persisted before any outcome is reported.
   An unreachable printer or a broken exchange while polling never ends the job: the runner
   keeps polling with a doubling back-off (OC-23). Answers the printer gives but the hub cannot
   use (an error status, a malformed body) end the job ``failed/interrupted`` after
   ``MAX_CONSECUTIVE_POLL_ERRORS`` in a row, so a misbehaving printer cannot hold the queue
   forever. ``client-error-not-found``
   (the printer forgot the job) ends ``failed/interrupted`` with ``started`` as observed.

Final states: 9 -> ``done``; 7 -> ``cancelled`` if never started, else ``failed/interrupted``;
8 -> ``failed/ipp_aborted`` if never started, else ``failed/interrupted`` (plan decision: a
started page whose outcome is unknown leaves its cells unconfirmed).

Cancel (``request_cancel``) is asynchronous at the printer (spike S2): Cancel-Job is sent, and
the polling decides the outcome. Right after Cancel-Job a printer reports ``processing`` with
``processing-to-stop-point``; that interim state is not taken as evidence that the page started.
``client-error-not-possible`` on Cancel-Job means the job already finished; the next poll
reads its final state. A cancel that arrives before the upload skips the Print-Job. A page
that was being fed when the cancel arrived and ends ``canceled`` with
``job-impressions-completed = 0`` counts as not started: the printer's counter is the evidence
the hub has (a partly fed sheet the printer does not count is not seen).

Messages are fixed text; a printer's own text never reaches the job record (spec 18).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from app.printer_backends.ipp.attributes import PRINTER_ATTRS, ProbeSummary, map_status
from app.printer_backends.ipp.client import PrintAccepted
from app.printer_backends.ipp.errors import (
    IppBadResponseError,
    IppBusyError,
    IppDecodeError,
    IppEncodeError,
    IppError,
    IppNotFoundError,
    IppResponseTooLargeError,
    IppStatusError,
    IppTransportError,
    IppUnreachableError,
)
from app.printer_backends.ipp.job_attrs import is_own_job, print_job_attributes, wire_job_name
from app.services.job_lifecycle import (
    InvalidStateTransitionError,
    Job,
    JobState,
    JobStateMachine,
)
from app.services.job_store import JobStore
from app.services.page_jobs import (
    IDENTITY_MISMATCH_CODE,
    PageJob,
    PagePrinter,
    notify_ended,
    outcome_handler,
    render_page,
)

_log = logging.getLogger(__name__)

# IPP job-state values (RFC 8011 5.3.7)
_PENDING, _HELD, _PROCESSING, _STOPPED, _CANCELED, _ABORTED, _COMPLETED = 3, 4, 5, 6, 7, 8, 9
_AT_PRINTER = {_PENDING: "waiting", _HELD: "waiting", _PROCESSING: "printing", _STOPPED: "stopped"}
_STARTED_STATES = frozenset({_PROCESSING, _STOPPED, _COMPLETED})
_NOT_POSSIBLE = 0x0404
_STOP_POINT = "processing-to-stop-point"
MAX_CONSECUTIVE_POLL_ERRORS = 5
"""Polls in a row that the printer answered unusably (an IPP error status other than
not-found, a non-IPP or malformed or oversized answer) before the job ends
``failed/interrupted``. Reachability problems never count (OC-23); a good poll resets it."""
_MIN_BACKOFF_S = 0.5
"""First back-off step when ``poll_interval_s`` is 0 (tests); doubled up to ``max_backoff_s``."""

# Upload errors after which the document may have reached the printer (errors.py contract).
_MAYBE_SENT: tuple[type[IppError], ...] = (
    IppTransportError,
    IppBadResponseError,
    IppDecodeError,
    IppResponseTooLargeError,
)
# Polling errors that never end the job: the printer is not reachable (OC-23).
_UNREACHABLE: tuple[type[IppError], ...] = (IppUnreachableError, IppTransportError)
# Polling errors where the printer answered, but unusably: counted, see
# MAX_CONSECUTIVE_POLL_ERRORS.
_UNUSABLE: tuple[type[IppError], ...] = (
    IppStatusError,
    IppBadResponseError,
    IppDecodeError,
    IppResponseTooLargeError,
)

_MESSAGES = {
    "render_failed": "The page could not be drawn.",
    "ipp_unreachable": "The printer could not be reached.",
    "ipp_busy": "The printer was busy and did not take the job.",
    "ipp_rejected": "The printer refused the document.",
    "ipp_request_invalid": "The print request could not be built.",
    "interrupted": "The printer may have printed the page; its outcome is unknown.",
    "ipp_aborted": "The printer aborted the job before printing.",
    IDENTITY_MISMATCH_CODE: "The device behind this printer changed; the job was not printed.",
}


class Deferred(Exception):  # noqa: N818 - the plan's interface name
    """The printer is not ready (pre-flight); the job stays ``queued`` and is retried later."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass
class _Active:
    """A page job between ``mark_printing`` and its final state."""

    printer: PagePrinter
    ipp_job_id: int | None = None
    cancel_requested: bool = False
    cancel_sent: bool = False
    identity_verified: bool = True
    """False for a resumed job until a poll showed that the printer's job is the hub's own:
    nothing (Cancel-Job) is sent to the id before that."""

    def cancel_pending(self) -> bool:
        """A cancel was asked for and not yet delivered (read across awaits: a method)."""
        return self.cancel_requested and not self.cancel_sent


Notify = Callable[..., None]
Sleep = Callable[[float], Awaitable[None]]


class PageJobRunner:
    """Runs page jobs; one ``run`` per job, awaited by the printer's queue worker."""

    def __init__(
        self,
        *,
        store: JobStore,
        notify: Notify,
        poll_interval_s: float = 2.0,
        max_backoff_s: float = 10.0,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._store = store
        self._notify = notify
        self._poll_interval_s = poll_interval_s
        self._max_backoff_s = max_backoff_s
        self._sleep = sleep
        self._active: dict[UUID, _Active] = {}

    # ------------------------------------------------------------------ public

    def is_tracking(self, job_id: UUID) -> bool:
        """True while the printer holds the job (accepted, not yet final)."""
        active = self._active.get(job_id)
        return active is not None and active.ipp_job_id is not None

    def is_active(self, job_id: UUID) -> bool:
        """True from ``mark_printing`` until the job is final (uploading or tracked)."""
        return job_id in self._active

    async def request_cancel(self, job_id: UUID) -> bool:
        """Ask the printer to cancel an active job. ``False``: the runner does not hold it.

        The outcome is decided by the polling, never assumed here.
        """
        active = self._active.get(job_id)
        if active is None:
            return False
        active.cancel_requested = True
        # A resumed job whose identity is not verified yet may be another client's job under a
        # reused id: the cancel stays pending and tracking sends it after the first poll that
        # shows the job is ours (or never, if it is not).
        if active.ipp_job_id is not None and not active.cancel_sent and active.identity_verified:
            await self._send_cancel(job_id, active)
        return True

    async def run(self, printer: PagePrinter, page_job: PageJob) -> None:
        """Send and track ``page_job``. Raises ``Deferred`` when the pre-flight says not now."""
        job = page_job.job
        job_id = UUID(job.id)
        summary = await self._preflight(printer)
        # No await between this check and the transition: a concurrent queue cancel either ran
        # before (the job is no longer QUEUED; the queue persisted it) or sees PRINTING.
        if job.state != JobState.QUEUED:
            return
        JobStateMachine.transition(job, JobState.PRINTING)
        active = _Active(printer=printer)
        self._active[job_id] = active
        try:
            self._emit(job, JobState.QUEUED, JobState.PRINTING)
            if not await self._store.mark_printing(job_id):
                # The row was ended elsewhere (cancelled through the database): never send.
                self._end_in_memory(job, JobState.CANCELLED)
                await notify_ended(
                    page_job.payload.kind,
                    job_id,
                    state="cancelled",
                    started=False,
                    error_code="cancelled",
                )
                return
            result: dict[str, Any] = {"phase": "uploading", "started": False}
            await self._store.set_result(job_id, result)
            await self._upload_and_track(page_job, active, summary, result)
        finally:
            self._release(job_id, active, printer)

    async def fail_identity_mismatch(self, page_job: PageJob) -> None:
        """End a job that never left ``queued`` because its printer's device changed (#231).

        The not-started failure path: the row and the in-memory job end ``failed`` with
        ``printer-identity-mismatch`` and ``started=False``, the event goes out, and the outcome
        handler's ``on_ended(started=False)`` runs (a sheet page frees its cells).
        """
        await self._fail(
            page_job,
            {"phase": "ended", "started": False},
            IDENTITY_MISMATCH_CODE,
            started=False,
        )

    async def resume(
        self, printer: PagePrinter, page_job: PageJob, *, cancel_requested: bool = False
    ) -> None:
        """Track a job the printer already holds, after a hub restart.

        ``page_job.resume_result`` is the stored ``result`` (IPP job id, ``started``); the
        polling is the one a freshly sent job gets, so the outcomes are the same. The in-memory
        job is ``printing`` already; nothing is sent. ``cancel_requested``: a cancel arrived
        while the job waited to resume; Cancel-Job goes out at the first poll, with the usual
        retry when the printer cannot be reached.
        """
        job_id = UUID(page_job.job.id)
        result = dict(page_job.resume_result or {})
        ipp_job_id = result["ipp_job_id"]
        result.setdefault("started", False)
        active = _Active(
            printer=printer,
            ipp_job_id=ipp_job_id,
            cancel_requested=cancel_requested,
            identity_verified=False,
        )
        self._active[job_id] = active
        printer.own_job_ids.add(ipp_job_id)
        try:
            await self._track(page_job, active, result)
        finally:
            self._release(job_id, active, printer)

    async def end_forgotten(self, page_job: PageJob) -> None:
        """End a job the printer no longer knows: ``failed/interrupted``, ``started`` as stored."""
        result = dict(page_job.resume_result or {})
        await self._fail(page_job, result, "interrupted", started=bool(result.get("started")))

    def _release(self, job_id: UUID, active: _Active, printer: PagePrinter) -> None:
        self._active.pop(job_id, None)
        if active.ipp_job_id is not None:
            printer.own_job_ids.discard(active.ipp_job_id)

    # ------------------------------------------------------------------ steps

    async def _preflight(self, printer: PagePrinter) -> ProbeSummary:
        try:
            attrs = await printer.client.get_printer_attributes(PRINTER_ATTRS)
        except IppError as exc:
            _log.info("Page job deferred: printer not usable (%s)", type(exc).__name__)
            raise Deferred("ipp_unreachable") from None
        record = map_status(attrs)
        # Any blocking reason defers, whatever the printer state: the status producer resumes
        # exactly when no blocking reason is left (OC-22), so the held job is retried then.
        if record.blocking_reason is not None:
            raise Deferred(record.blocking_reason)
        if record.summary.accepting_jobs is False:
            raise Deferred("not_accepting")
        return record.summary

    async def _upload_and_track(
        self,
        page_job: PageJob,
        active: _Active,
        summary: ProbeSummary,
        result: dict[str, Any],
    ) -> None:
        job, payload = page_job.job, page_job.payload
        job_id = UUID(job.id)
        try:
            pdf = await asyncio.to_thread(render_page, payload)
        except Exception as exc:
            _log.warning("Page job %s: rendering failed (%s)", job_id, type(exc).__name__)
            await self._fail(page_job, result, "render_failed", started=False)
            return
        if active.cancel_requested:
            await self._cancelled(page_job)
            return
        ops, job_attrs = print_job_attributes(
            summary,
            media=payload.media,
            tray=payload.tray,
            job_name=wire_job_name(payload.job_name, job_id),
        )
        try:
            accepted: PrintAccepted = await active.printer.client.print_job(pdf, job_attrs, ops)
        except IppUnreachableError:
            await self._fail(page_job, result, "ipp_unreachable", started=False)
            return
        except IppBusyError:
            await self._fail(page_job, result, "ipp_busy", started=False)
            return
        except IppStatusError as exc:
            await self._fail(
                page_job, result, "ipp_rejected", started=False, detail={"ipp_status": exc.name}
            )
            return
        except IppEncodeError:
            await self._fail(page_job, result, "ipp_request_invalid", started=False)
            return
        except _MAYBE_SENT as exc:
            _log.warning("Page job %s: upload interrupted (%s)", job_id, type(exc).__name__)
            await self._fail(page_job, result, "interrupted", started=True)
            return
        except Exception as exc:  # unknown failure after the upload began: assume it may print
            _log.exception("Page job %s: upload failed (%s)", job_id, type(exc).__name__)
            await self._fail(page_job, result, "interrupted", started=True)
            return
        active.ipp_job_id = accepted.job_id
        active.printer.own_job_ids.add(accepted.job_id)
        # Not ``accepted.job_uri``: the job row is readable with a plain ``read`` key and the
        # URI carries the printer's host, which only admins may see (spec 14, 18). Tracking and
        # recovery use ``ipp_job_id``; the printer's address comes from its own connection.
        result.update({"phase": "tracking", "ipp_job_id": accepted.job_id})
        if accepted.substituted:
            # The printer ignored or replaced some job attributes (spike S2); the UI can warn.
            result["attributes_substituted"] = True
        await self._store.set_result(job_id, result)
        if active.cancel_pending():
            await self._send_cancel(job_id, active)
        await self._track(page_job, active, result)

    async def _track(self, page_job: PageJob, active: _Active, result: dict[str, Any]) -> None:
        job = page_job.job
        job_id = UUID(job.id)
        ipp_job_id = active.ipp_job_id
        assert ipp_job_id is not None
        client = active.printer.client
        delay = self._poll_interval_s
        unusable = 0
        unknown_state_logged = False
        while True:
            await self._sleep(delay)
            if active.cancel_pending() and active.identity_verified:
                await self._send_cancel(job_id, active)
            try:
                info = await client.get_job(ipp_job_id)
            except IppNotFoundError:
                _log.warning("Page job %s: the printer no longer knows the job", job_id)
                await self._fail(page_job, result, "interrupted", started=result["started"])
                return
            except _UNREACHABLE as exc:
                delay = self._backoff(delay)
                _log.debug("Page job %s: poll failed (%s)", job_id, type(exc).__name__)
                continue
            except _UNUSABLE as exc:
                unusable += 1
                _log.debug("Page job %s: unusable answer (%s)", job_id, type(exc).__name__)
                if unusable >= MAX_CONSECUTIVE_POLL_ERRORS:
                    _log.warning(
                        "Page job %s: %d unusable answers in a row; giving up", job_id, unusable
                    )
                    await self._fail(page_job, result, "interrupted", started=result["started"])
                    return
                delay = self._backoff(delay)
                continue
            if not is_own_job(
                info.name, info.originating_user, wire_job_name(page_job.payload.job_name, job_id)
            ):
                # The printer reused the id for another client's job (it rebooted while the
                # hub was down): not ours. Same end as a job the printer forgot.
                _log.warning("Page job %s: the printer's job %s is not ours", job_id, ipp_job_id)
                await self._fail(page_job, result, "interrupted", started=result["started"])
                return
            if not _PENDING <= info.state <= _COMPLETED and not unknown_state_logged:
                # RFC 8011 job-state is 3..9. Anything else is shown as waiting and never ends
                # the job: the printer, not the hub, owns it. Logged once per job, no payload.
                unknown_state_logged = True
                _log.warning("job %s: unknown job-state %r", job_id, info.state)
            if not active.identity_verified:
                active.identity_verified = True
                if active.cancel_pending():
                    await self._send_cancel(job_id, active)
            unusable = 0
            delay = self._poll_interval_s
            job.at_printer_reasons = list(info.reasons)
            stopping = active.cancel_sent and _STOP_POINT in info.reasons
            evidence = (info.impressions_completed or 0) > 0 or (
                info.state in _STARTED_STATES and not stopping
            )
            if evidence and not result["started"]:
                result["started"] = True
                await self._store.set_result(job_id, result)
                await self._handler_call(page_job, "on_started")
            if info.state == _COMPLETED:
                await self._complete(page_job)
                return
            if info.state == _CANCELED:
                if result["started"]:
                    await self._fail(page_job, result, "interrupted", started=True)
                else:
                    await self._cancelled(page_job)
                return
            if info.state == _ABORTED:
                code = "interrupted" if result["started"] else "ipp_aborted"
                await self._fail(page_job, result, code, started=result["started"])
                return
            self._at_printer(job, _AT_PRINTER.get(info.state, "waiting"))

    def _backoff(self, delay: float) -> float:
        return min(self._max_backoff_s, max(delay * 2, self._poll_interval_s, _MIN_BACKOFF_S))

    async def _send_cancel(self, job_id: UUID, active: _Active) -> None:
        assert active.ipp_job_id is not None
        try:
            await active.printer.client.cancel_job(active.ipp_job_id)
        except IppNotFoundError:
            active.cancel_sent = True  # the polling reports the forgotten job
        except IppStatusError as exc:
            if exc.status == _NOT_POSSIBLE:
                active.cancel_sent = True  # already finished: the polling reads the final state
            else:
                _log.warning("Page job %s: Cancel-Job refused (%s)", job_id, exc.name)
        except IppError as exc:
            # Not sent or answer lost: retried from the polling loop.
            _log.warning("Page job %s: Cancel-Job failed (%s)", job_id, type(exc).__name__)
        else:
            active.cancel_sent = True

    # ------------------------------------------------------------------ outcomes

    async def _complete(self, page_job: PageJob) -> None:
        job = page_job.job
        # Database first: if the write fails the job is still ``printing`` for the queue's
        # backstop, and no event or waiter has claimed a completion that is not stored.
        await self._store.mark_done(UUID(job.id))
        self._end_in_memory(job, JobState.COMPLETED)
        await self._handler_call(page_job, "on_completed")

    async def _cancelled(self, page_job: PageJob) -> None:
        job = page_job.job
        await self._store.mark_cancelled(UUID(job.id), allow_printing=True)  # database first
        job.error_code = "cancelled"
        self._end_in_memory(job, JobState.CANCELLED)
        await notify_ended(
            page_job.payload.kind,
            UUID(job.id),
            state="cancelled",
            started=False,
            error_code="cancelled",
        )

    async def _fail(
        self,
        page_job: PageJob,
        result: dict[str, Any],
        code: str,
        *,
        started: bool,
        detail: dict[str, Any] | None = None,
    ) -> None:
        job = page_job.job
        job_id = UUID(job.id)
        message = _MESSAGES[code]
        if started and not result.get("started"):
            result["started"] = True
        result["phase"] = "ended"
        # One write for result and state, and before the in-memory end: ``started`` is
        # persisted before ``on_ended`` runs, and a crash leaves either the row as it was
        # (printing: restart recovery settles it from the printer) or the finished one. Two
        # commits would leave "printing" with ``phase=ended`` between them. A failing write
        # leaves the job ``printing`` for the queue's backstop; nothing was published.
        await self._store.mark_failed_code(job_id, code, message, detail, result=result)
        job.error_code = code
        job.error_message = message
        job.error_detail = detail
        job.error_msg = message
        self._end_in_memory(job, JobState.FAILED)
        await notify_ended(
            page_job.payload.kind, job_id, state="failed", started=started, error_code=code
        )

    async def _handler_call(
        self, page_job: PageJob, name: Literal["on_started", "on_completed"]
    ) -> None:
        job_id = UUID(page_job.job.id)
        try:
            await getattr(outcome_handler(page_job.payload.kind), name)(job_id)
        except Exception:
            _log.exception("Page outcome handler %s failed for job %s", name, job_id)

    # ------------------------------------------------------------------ in-memory + events

    def _emit(self, job: Job, from_state: JobState, to_state: JobState) -> None:
        try:
            self._notify(job, from_state, to_state)
        except Exception:
            _log.exception("Page job event failed for job %s", job.id)

    def _end_in_memory(self, job: Job, to_state: JobState) -> None:
        from_state = job.state
        try:
            JobStateMachine.transition(job, to_state)
        except InvalidStateTransitionError:
            _log.warning("Page job %s: unexpected state %s at %s", job.id, from_state, to_state)
            job._done_event.set()
            return
        self._emit(job, from_state, to_state)

    def _at_printer(self, job: Job, where: str) -> None:
        """Record where the printer reports the job; an event only when it changes."""
        changed = where != job.at_printer
        job.at_printer = where
        if changed:
            self._emit(job, JobState.PRINTING, JobState.PRINTING)
