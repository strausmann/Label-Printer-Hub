"""Page jobs: the queue's third item type, printed on IPP page printers (spec 11, 12.4).

A page job carries a ``PagePayload`` — everything needed to draw the page again at send
time — and the in-memory ``Job`` the queue uses for state and events. The payload is stored
as ``jobs.payload``; a payload without ``kind`` is a tape job (no data migration).

Two small registries keyed by payload ``kind`` keep the runner generic:

* the **renderer** turns a payload into PDF bytes (Plan 2 registers ``calibration_page``,
  Plan 3 ``sheet_page``);
* the **outcome handler** is told how the job ended (``on_started``, ``on_completed``,
  ``on_ended``, ``on_unknown``); the default handler does nothing.

``PagePrinter`` is what the runner needs of a printer. ``summary()`` and ``status()`` are
synchronous reads of the ``IppPrinterState`` the status producer keeps — never the database.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.page_render.transform import IDENTITY, Deviation
from app.printer_backends.ipp.attributes import IppStatusRecord, ProbeSummary
from app.printer_backends.ipp.client import IppClient
from app.services.job_lifecycle import Job

if TYPE_CHECKING:
    from app.services.producers.ipp_status_producer import IppPrinterState

_log = logging.getLogger(__name__)

PageKind = Literal["sheet_page", "calibration_page"]
PAGE_KINDS: tuple[PageKind, ...] = ("sheet_page", "calibration_page")


class CalibrationSnapshot(BaseModel):
    """The calibration applied when the page is drawn (Task 11 fills it).

    Integers keep stored values exact: offsets in hundredths of mm, scale in parts per
    million, rotation in micro-degrees (plan Global Constraints).
    """

    model_config = ConfigDict(extra="forbid")

    method: str
    dx_hmm: int = 0
    dy_hmm: int = 0
    sx_ppm: int = 1_000_000
    sy_ppm: int = 1_000_000
    rotation_udeg: int = 0


def snapshot_to_deviation(snap: CalibrationSnapshot | None) -> Deviation:
    """The deviation a snapshot stands for; no snapshot is the identity (no correction)."""
    if snap is None:
        return IDENTITY
    return Deviation(snap.dx_hmm, snap.dy_hmm, snap.sx_ppm, snap.sy_ppm, snap.rotation_udeg)


class PagePayload(BaseModel):
    """What a page job prints; ``detail`` is kind-specific and owned by the renderer."""

    kind: PageKind
    media: Literal["A4", "Letter"]
    tray: str
    render_dpi: int
    job_name: str
    calibration: CalibrationSnapshot | None = None
    detail: dict[str, Any] = {}


# ---------------------------------------------------------------------------- renderers

PageRenderer = Callable[[PagePayload], bytes]
_RENDERERS: dict[str, PageRenderer] = {}


class NoPageRendererError(LookupError):
    """No renderer is registered for the payload's kind."""


def register_page_renderer(kind: PageKind, fn: PageRenderer) -> None:
    _RENDERERS[kind] = fn


def render_page(payload: PagePayload) -> bytes:
    """PDF bytes for ``payload`` (CPU-bound: call it through ``asyncio.to_thread``)."""
    fn = _RENDERERS.get(payload.kind)
    if fn is None:
        raise NoPageRendererError(payload.kind)
    return fn(payload)


# ---------------------------------------------------------------------------- outcomes


class PageOutcomeHandler(Protocol):
    """How a page job ended, as the kind's owner wants to hear it.

    ``on_started`` is best-effort and at most once: the hub persists ``started`` before it
    calls the handler, so a crash in between leaves the callback undelivered (a restart sees
    ``started`` already true and does not replay it). Never depend on having seen it.
    The terminal callbacks are authoritative: ``on_completed`` means the page printed,
    ``on_ended`` carries ``started``, and ``on_unknown`` means the outcome cannot be known.
    """

    async def on_started(self, job_id: UUID) -> None: ...

    async def on_completed(self, job_id: UUID) -> None: ...

    async def on_ended(
        self,
        job_id: UUID,
        *,
        state: Literal["cancelled", "failed"],
        started: bool,
        error_code: str,
    ) -> None: ...

    async def on_unknown(self, job_id: UUID) -> None: ...


class _NoopHandler:
    """The default outcome handler: a kind without one is printed with no follow-up."""

    async def on_started(self, job_id: UUID) -> None:
        del job_id

    async def on_completed(self, job_id: UUID) -> None:
        del job_id

    async def on_ended(
        self,
        job_id: UUID,
        *,
        state: Literal["cancelled", "failed"],
        started: bool,
        error_code: str,
    ) -> None:
        del job_id, state, started, error_code

    async def on_unknown(self, job_id: UUID) -> None:
        del job_id


_NOOP = _NoopHandler()
_HANDLERS: dict[str, PageOutcomeHandler] = {}


def register_outcome_handler(kind: PageKind, handler: PageOutcomeHandler) -> None:
    _HANDLERS[kind] = handler


def unregister_outcome_handler(kind: PageKind, handler: PageOutcomeHandler) -> None:
    """Remove ``handler`` if it is still the one registered (a later owner's stays)."""
    if _HANDLERS.get(kind) is handler:
        del _HANDLERS[kind]


def outcome_handler(kind: str) -> PageOutcomeHandler:
    """The handler registered for ``kind``; a no-op handler when there is none."""
    return _HANDLERS.get(kind, _NOOP)


async def notify_ended(
    kind: str,
    job_id: UUID,
    *,
    state: Literal["cancelled", "failed"],
    started: bool,
    error_code: str,
) -> None:
    """Call ``on_ended``; a failing handler is logged and never breaks the caller."""
    try:
        await outcome_handler(kind).on_ended(
            job_id, state=state, started=started, error_code=error_code
        )
    except Exception:
        _log.exception("Page outcome handler on_ended failed for job %s", job_id)


# ---------------------------------------------------------------------------- jobs, printers


@dataclass
class PageJob:
    """A queue item: the in-memory ``Job`` (state, events) and the payload it prints."""

    job: Job
    payload: PagePayload
    resume_result: dict[str, Any] | None = None
    """Restart recovery: the stored ``result`` of a job the printer already holds (it names
    the IPP job id). ``None`` for a job that still has to be sent."""


class PagePrinter(Protocol):
    """What the page-job path needs of an IPP printer.

    ``own_job_ids`` is the producer's set of printer job ids the hub tracks itself: the
    runner adds the IPP job id as soon as Print-Job returns and discards it when the job is
    final, so ``jobs_ahead`` does not count the hub's own job.
    """

    id: UUID
    client: IppClient

    @property
    def own_job_ids(self) -> set[int]: ...

    def summary(self) -> ProbeSummary | None: ...

    def status(self) -> IppStatusRecord | None: ...


class IppPagePrinter:
    """``PagePrinter`` over one ``IppClient`` and the producer's ``IppPrinterState``.

    The client is owned by whoever built the printer (the lifespan closes it).
    """

    def __init__(self, *, id: UUID, client: IppClient, state: IppPrinterState) -> None:  # noqa: A002
        self.id = id
        self.client = client
        self._state = state

    @property
    def own_job_ids(self) -> set[int]:
        return self._state.own_job_ids

    def summary(self) -> ProbeSummary | None:
        return self._state.summary

    def status(self) -> IppStatusRecord | None:
        return self._state.status
