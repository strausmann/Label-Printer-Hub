# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""PrintService — submit_print_job pipeline using LayoutEngine.

Phase 1k.1a Task 15: TemplateLoader and LabelRenderer removed. The engine renders
for the currently loaded tape (preflight.loaded_tape_mm), so TapeMismatchError
is obsolete in this path. NoTapeLoadedError is raised when preflight returns
loaded_tape_mm=None.

PAUSED-Job path (submit_paused_with_id, resume_paused_job, on_tape_mismatch
branching) removed — superseded by the LayoutEngine's tape-agnostic rendering.

submit_batch_job preserved for Phase 1k.2 (batch print endpoint).
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from PIL import Image

from app.models.job import Job, JobState
from app.printer_backends.exceptions import (
    ConflictingOrientationError,
    NoTapeLoadedError,
    PrinterDisabledError,
    QrPayloadTooLongError,
    TapeMismatchError,
)
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.schemas.label_layout import LabelOrientation, LayoutDefault, QlLayoutPreset
from app.schemas.print_request import PrintOptions, PrintRequest, RawLabelData
from app.services.layout_engine import LayoutEngine
from app.services.print_error_codes import print_error_code
from app.services.print_queue import DEFERRED_INTERRUPTED, MAX_LABELS_PER_TAPE_JOB
from app.services.producers.print_queue_producer import publish_job_state_changed
from app.services.ql_layout import resolve_layout

_log = logging.getLogger(__name__)


MAX_BATCH_LOOKUPS = 8
"""263-78: integration lookups of one batch that run at once."""

# #281 R-281-11: the job error of a deferred job whose completion failed. A fixed sentence per
# code, never the exception text: a backend error can carry the printer's address.
_DEFERRED_FAILURE_MESSAGES: dict[str, str] = {
    "printer_disabled": "The printer is disabled.",
    "printer_offline": "The printer could not be reached.",
    "printer_cover_open": "The printer cover is open.",
    "no_tape_loaded": "No tape is loaded in the printer.",
    "tape_empty": "The tape is empty.",
    "tape_mismatch": "The loaded tape does not fit the label.",
    "unsupported_tape": "The loaded tape is not supported.",
    "content_type_data_mismatch": "The label data does not fit the content type.",
    "qr_payload_too_long": "The QR code content is too long for the loaded tape.",
}
_DEFERRED_FAILURE_FALLBACK = "The label could not be printed."

DEFERRED_STOP_BUDGET_S = 2.0
"""#281 review N1: the most a stop or detach waits to end its interrupted deferred jobs."""


class PrintService:
    """Orchestrate preflight → render → persist → queue.submit."""

    def __init__(
        self,
        *,
        printer_id: UUID,
        printer_slug: str = "",
        printer_enabled: bool = True,
        backend: Any,  # PrinterBackend protocol
        queue: Any,  # PrintQueue protocol
        store: Any,  # JobStore protocol
        engine: LayoutEngine,
        lookup_service: Any = None,  # optional LookupService protocol
        layout_defaults: Mapping[int, LayoutDefault] | None = None,
        event_bus: Any = None,  # optional EventBus: failed deferred jobs are announced on it
    ) -> None:
        self._printer_id = printer_id
        self._printer_slug = printer_slug
        self._printer_enabled = printer_enabled
        self._backend = backend
        self._queue = queue
        self._store = store
        self._engine = engine
        self._lookup_service = lookup_service
        self._layout_defaults: dict[int, LayoutDefault] = dict(layout_defaults or {})
        self._event_bus = event_bus
        # #281: the completions of deferred jobs that still run (cancelled on a stop/re-wire).
        # Task -> its job id; a job id leaves ``_unhanded`` once its payload is complete.
        self._deferred: dict[asyncio.Task[None], UUID] = {}
        self._unhanded: set[UUID] = set()

    @property
    def layout_defaults(self) -> dict[int, LayoutDefault]:
        """The stored layout default per tape width (a copy)."""
        return dict(self._layout_defaults)

    def set_layout_defaults(self, defaults: Mapping[int, LayoutDefault]) -> None:
        """Replace the printer's stored layout defaults per tape width (#258).

        The runtime calls this when an admin edit changes only the defaults, which needs
        no re-wire; the next job uses them.
        """
        self._layout_defaults = dict(defaults)

    def _resolve_layout(
        self, tape_mm: int, options: PrintOptions
    ) -> tuple[LabelOrientation, QlLayoutPreset | None]:
        """Request option, then the stored default for the loaded tape, then the tape default."""
        return resolve_layout(
            tape_mm,
            options.orientation,
            options.layout_preset,
            self._layout_defaults.get(tape_mm),
        )

    async def submit_print_job(
        self,
        request: PrintRequest,
        *,
        api_key_id: UUID | None = None,
        source_ip: str | None = None,
        label_transform: Callable[[LabelData], LabelData] | None = None,
        source_app: str = "manual",
    ) -> UUID:
        """Submit a print job: preflight → render → persist → queue.

        ``api_key_id`` / ``source_ip`` are stored on the job: the key owns it (#294).
        ``label_transform`` adjusts the resolved label data before it is rendered and stored
        (the webhook adds the quantity line, #284); ``source_app`` tags label data that the
        request carries itself.

        Raises:
            PrinterDisabledError (409): Drucker ist deaktiviert (enabled=False).
            NoTapeLoadedError (409): preflight returned loaded_tape_mm=None.
            UnsupportedTapeError (409): tape_mm not in TAPE_GEOMETRY.
            ContentTypeDataMismatchError (422): data missing required fields.
        """

        async def resolve(_tape_mm: int) -> LabelData:
            label_data = await self._resolve_label_data(request, source_app=source_app)
            return label_transform(label_data) if label_transform else label_data

        return await self._submit_label(
            resolve,
            content_type=request.content_type,
            options=request.options,
            template_key=None,
            api_key_id=api_key_id,
            source_ip=source_ip,
        )

    async def submit_test_label(
        self,
        build: Callable[[int], RawLabelData],
        *,
        api_key_id: UUID | None = None,
        source_ip: str | None = None,
    ) -> UUID:
        """Submit the test label (#228): the same path as ``submit_print_job``.

        One preflight decides the tape; ``build`` gets its width and returns the label data.
        The job is stored with ``template_key="test_label"`` and content type
        ``QR_THREE_LINES``, one copy.

        Raises: as ``submit_print_job``, plus ``PrinterOfflineError`` from the preflight.
        """

        async def resolve(tape_mm: int) -> LabelData:
            raw = build(tape_mm)
            return LabelData(
                source_app="manual",
                title=raw.title,
                primary_id=raw.primary_id,
                qr_payload=raw.qr_payload,
                secondary=raw.secondary,
                items=raw.items,
            )

        return await self._submit_label(
            resolve,
            content_type=ContentType.QR_THREE_LINES,
            options=PrintOptions(),
            template_key="test_label",
            api_key_id=api_key_id,
            source_ip=source_ip,
        )

    async def _submit_label(
        self,
        resolve: Callable[[int], Awaitable[LabelData]],
        *,
        content_type: ContentType,
        options: PrintOptions,
        template_key: str | None,
        api_key_id: UUID | None = None,
        source_ip: str | None = None,
    ) -> UUID:
        """enabled check → one preflight → label data → render → persist → queue."""
        if not self._printer_enabled:
            raise PrinterDisabledError(self._printer_id, self._printer_slug)

        preflight = await self._backend.preflight_check()
        if preflight.loaded_tape_mm is None:
            raise NoTapeLoadedError()
        tape_mm = preflight.loaded_tape_mm
        orientation, preset = self._resolve_layout(tape_mm, options)
        # The job stores what was actually rendered, so a restart re-renders the same label.
        options = options.model_copy(update={"orientation": orientation, "layout_preset": preset})

        label_data = await resolve(tape_mm)
        # asyncio.to_thread: render() is CPU-bound (QR generation + font rendering).
        # Offloading keeps the event loop responsive for concurrent requests.
        # Matches the pattern already used in submit_batch_job._prepare_one.
        image = await asyncio.to_thread(
            functools.partial(
                self._engine.render,
                tape_mm,
                content_type,
                label_data,
                orientation=orientation,
                preset=preset,
            )
        )

        job_id = uuid4()
        job = Job(
            id=job_id,
            printer_id=self._printer_id,
            template_key=template_key,
            payload={
                "label_data": label_data.model_dump(),
                "content_type": str(content_type),
                "rendered_tape_mm": tape_mm,
                "tape_mm": tape_mm,
                "options": options.model_dump(mode="json"),
            },
            api_key_id=api_key_id,
            source_ip=source_ip,
        )
        await self._store.save_queued(job)
        await self._queue.submit_with_id(
            job_id,
            self._printer_id,
            image,
            tape_mm=tape_mm,
            auto_cut=options.auto_cut,
            high_resolution=options.high_resolution,
            half_cut=options.half_cut,
            last_page=options.last_page,
            # The QL backend rotates on this flag only (#258); PT adapters ignore it.
            orientation=str(orientation),
        )
        return job_id

    # ------------------------------------------------------------------ deferred jobs (#281)

    async def accept_deferred_job(
        self,
        raw: RawLabelData,
        *,
        content_type: ContentType,
        source_app: str,
        api_key_id: UUID | None,
        source_ip: str | None,
    ) -> UUID:
        """Store a ``queued`` job and complete it after the caller has answered (R-281-11).

        The row holds the label data, the requested content type and ``deferred: true``, but
        no tape fields yet. A tracked task then runs preflight -> tape -> render (a
        ``qr_three_lines`` label without a secondary line prints as ``qr_two_lines``) ->
        completes the payload -> hands it to the queue. Any failure there sets the job
        ``failed`` with the code ``POST /api/v1/print`` would answer and publishes
        ``job.state_changed``. A restart before the hand-off ends the job ``failed_restart``
        (the queue's recovery); it is never printed twice.
        """
        label = LabelData(
            source_app=source_app,
            title=raw.title,
            primary_id=raw.primary_id,
            qr_payload=raw.qr_payload,
            secondary=raw.secondary,
            items=raw.items,
        )
        job_id = uuid4()
        await self._store.save_queued(
            Job(
                id=job_id,
                printer_id=self._printer_id,
                template_key=None,
                payload={
                    "deferred": True,
                    "label_data": label.model_dump(),
                    "content_type": str(content_type),
                },
                api_key_id=api_key_id,
                source_ip=source_ip,
            )
        )
        task = asyncio.create_task(
            self._complete_deferred(job_id, label, content_type),
            name=f"deferred-job-{job_id}",
        )
        self._deferred[task] = job_id
        self._unhanded.add(job_id)

        def _done(done: asyncio.Task[None]) -> None:
            self._deferred.pop(done, None)
            if not done.cancelled():  # a cancelled one is settled by ``cancel_deferred``
                self._unhanded.discard(job_id)

        task.add_done_callback(_done)
        return job_id

    async def record_failed_job(
        self,
        error_code: str,
        *,
        api_key_id: UUID | None,
        source_ip: str | None,
        source_app: str,
        message: str = _DEFERRED_FAILURE_FALLBACK,
    ) -> UUID:
        """Store a ``failed`` job on this printer for a label that could not be built.

        A content error of a webhook (``grocy_label_invalid``, ``grocy_label_mismatch``):
        the request was accepted, the failure is shown where the operator looks (the job
        page). ``message`` must be a fixed sentence; it never repeats the request.
        """
        job_id = uuid4()
        now = datetime.now(UTC)
        await self._store.save_queued(
            Job(
                id=job_id,
                printer_id=self._printer_id,
                template_key=None,
                state=JobState.FAILED.value,
                # ``content_error`` tells a retry there is no label to print again.
                payload={"label_data": {"source_app": source_app}, "content_error": error_code},
                error=f"{error_code}: {message}",
                api_key_id=api_key_id,
                source_ip=source_ip,
                finished_at=now,
            )
        )
        self._publish_failed(job_id, error_code)
        return job_id

    async def cancel_deferred(self) -> None:
        """Cancel the deferred completions that still run (a stop, a re-wire or a detach).

        A job whose payload was not completed yet ends ``failed_restart``
        (``deferred_interrupted``) right away, so a printer that is disabled or removed does
        not leave it ``queued`` until a later attach (review F4). A job already completed
        stays ``queued``: the queue holds it, or its recovery prints it once. A crash, where
        this never runs, is caught by the queue's recovery.

        The write is one statement for all of them, bounded by ``DEFERRED_STOP_BUDGET_S``, so
        a stop stays inside a container's grace period even when SQLite is locked; what it
        does not finish, the start-up recovery ends.
        """
        jobs = dict(self._deferred)
        for task in jobs:
            task.cancel()
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)
        interrupted = [job_id for job_id in jobs.values() if job_id in self._unhanded]
        if interrupted:
            await self._end_interrupted(interrupted)
        self._unhanded.difference_update(jobs.values())

    async def _end_interrupted(self, job_ids: list[UUID]) -> None:
        try:
            ended = await asyncio.wait_for(
                self._store.mark_queued_many_failed_restart(job_ids, DEFERRED_INTERRUPTED),
                timeout=DEFERRED_STOP_BUDGET_S,
            )
        except Exception as exc:  # TimeoutError, a locked database: the stop goes on
            _log.warning(
                "%d interrupted deferred job(s) left queued for the start-up recovery (%s)",
                len(job_ids),
                exc.__class__.__name__,
            )
            return
        for job_id in ended:
            publish_job_state_changed(
                self._event_bus,
                printer_id=self._printer_id,
                job_id=job_id,
                from_state=JobState.QUEUED.value,
                to_state=JobState.FAILED_RESTART.value,
                error_code=DEFERRED_INTERRUPTED,
            )

    async def _complete_deferred(
        self, job_id: UUID, label: LabelData, requested: ContentType
    ) -> None:
        try:
            if not self._printer_enabled:
                raise PrinterDisabledError(self._printer_id, self._printer_slug)
            preflight = await self._backend.preflight_check()
            if preflight.loaded_tape_mm is None:
                raise NoTapeLoadedError()
            tape_mm = preflight.loaded_tape_mm
            options = PrintOptions()
            orientation, preset = self._resolve_layout(tape_mm, options)
            options = options.model_copy(
                update={"orientation": orientation, "layout_preset": preset}
            )
            content_type = requested
            if content_type is ContentType.QR_THREE_LINES and not label.secondary:
                # R-281-7: only a stock entry with a due date has the third line.
                content_type = ContentType.QR_TWO_LINES
            image = await asyncio.to_thread(
                functools.partial(
                    self._engine.render,
                    tape_mm,
                    content_type,
                    label,
                    orientation=orientation,
                    preset=preset,
                )
            )
            completed = await self._store.set_queued_payload(
                job_id,
                {
                    "deferred": True,
                    "label_data": label.model_dump(),
                    "content_type": str(content_type),
                    "rendered_tape_mm": tape_mm,
                    "tape_mm": tape_mm,
                    "options": options.model_dump(mode="json"),
                },
            )
            self._unhanded.discard(job_id)
            if not completed:
                # Cancelled (or otherwise ended) while it was prepared: nothing to print.
                return
            await self._queue.submit_with_id(
                job_id,
                self._printer_id,
                image,
                tape_mm=tape_mm,
                auto_cut=options.auto_cut,
                high_resolution=options.high_resolution,
                half_cut=options.half_cut,
                last_page=options.last_page,
                orientation=str(orientation),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            code = print_error_code(exc)
            if code == "internal_error":
                _log.exception("Deferred job %s failed", job_id)
            detail: dict[str, Any] | None = None
            if isinstance(exc, TapeMismatchError):
                detail = {"expected_mm": exc.expected_mm, "loaded_mm": exc.loaded_mm}
            elif isinstance(exc, QrPayloadTooLongError):
                detail = {"length": exc.length, "max_bytes": exc.max_bytes}
            message = _DEFERRED_FAILURE_MESSAGES.get(code, _DEFERRED_FAILURE_FALLBACK)
            # Announced only when the row changed: a job the user cancelled meanwhile stays
            # cancelled and must not show up as failed (review F3).
            if await self._store.mark_failed_code(job_id, code, message, detail):
                self._publish_failed(job_id, code)

    def _publish_failed(self, job_id: UUID, error_code: str) -> None:
        """Announce a job that failed outside the queue worker (``job.state_changed``)."""
        publish_job_state_changed(
            self._event_bus,
            printer_id=self._printer_id,
            job_id=job_id,
            from_state=JobState.QUEUED.value,
            to_state=JobState.FAILED.value,
            error_code=error_code,
        )

    async def _resolve_label_data(
        self, request: PrintRequest, *, source_app: str = "manual"
    ) -> LabelData:
        """Resolve label data from raw request data or lookup service."""
        if request.data is not None:
            raw = request.data
            return LabelData(
                source_app=source_app,
                title=raw.title,
                primary_id=raw.primary_id,
                qr_payload=raw.qr_payload,
                secondary=raw.secondary,
                items=raw.items,
            )
        assert request.lookup is not None
        if self._lookup_service is None:
            msg = "lookup_service is required for lookup-based PrintRequest"
            raise RuntimeError(msg)
        return cast(
            LabelData,
            await self._lookup_service.lookup(
                request.lookup.app,
                request.lookup.identifier,
            ),
        )

    async def submit_batch_job(
        self,
        requests: list[PrintRequest],
        *,
        half_cut: bool,
        run_id: UUID | None = None,
        label_ids: list[UUID] | None = None,
        slot: UUID | None = None,
        api_key_id: UUID | None = None,
        source_ip: str | None = None,
    ) -> list[UUID]:
        """Render N items and submit them to the queue as one tape run (#277).

        *slot* is the queued-run claim the run takes over (263-76, ``dispatch_batch``). At most
        ``MAX_BATCH_LOOKUPS`` integration lookups of the batch run at once (263-78).

        The queue splits the run into sub-jobs of ``MAX_LABELS_PER_TAPE_JOB`` and sends groups
        of ``TAPE_GROUP_SIZE``. *run_id* names the run (the batch id of the API). *label_ids*,
        when given, receives the job id of every label (copies included) in print order.
        Every row records *api_key_id* and *source_ip*: the key owns the run's jobs (#294).
        Preflight wird 1x am Anfang für alle Items geprüft.

        NOTE: Diese Methode verwendet noch direkte LayoutEngine-Render-Aufrufe
        ohne TapeMismatchError — Phase 1k.2 wird sie vollständig anpassen.
        """
        if not requests:
            raise ValueError("submit_batch_job requires at least one request")

        # 1. Preflight (1x für alle)
        preflight = await self._backend.preflight_check()
        if preflight.loaded_tape_mm is None:
            raise NoTapeLoadedError()

        tape_mm = preflight.loaded_tape_mm
        # #258: one orientation for the whole batch; the backend rotates every image on that
        # one flag. Items without an orientation follow the one an item names explicitly;
        # different explicit orientations are refused instead of silently overridden.
        explicit = sorted({str(r.options.orientation) for r in requests if r.options.orientation})
        if len(explicit) > 1:
            raise ConflictingOrientationError(tuple(explicit))
        named = next((r.options for r in requests if r.options.orientation), requests[0].options)
        orientation, _ = self._resolve_layout(tape_mm, named)
        resolved_options = [
            req.options.model_copy(
                update={
                    "orientation": orientation,
                    # The batch-level cut mode goes into every stored row, so a recovery after a
                    # restart prints the run with the same cut as the live batch.
                    "half_cut": half_cut,
                    "layout_preset": self._resolve_layout(
                        tape_mm,
                        req.options.model_copy(update={"orientation": orientation}),
                    )[1],
                }
            )
            for req in requests
        ]

        # 2. Resolve LabelData ONCE per item, then render via LayoutEngine
        lookups = asyncio.Semaphore(MAX_BATCH_LOOKUPS)

        async def _prepare_one(
            req: PrintRequest, opts: PrintOptions
        ) -> tuple[Image.Image, dict[str, Any]]:
            async with lookups:
                label_data = await self._resolve_label_data(req)
            image = await asyncio.to_thread(
                functools.partial(
                    self._engine.render,
                    tape_mm,
                    req.content_type,
                    label_data,
                    orientation=opts.orientation,
                    preset=opts.layout_preset,
                )
            )
            return image, label_data.model_dump()

        prepared = await asyncio.gather(
            *[_prepare_one(r, o) for r, o in zip(requests, resolved_options, strict=True)]
        )

        # 3. Pre-allocate job UUIDs + persist in JobStore
        # Bug 2026-06-14 Round 2: PR #115 hatte das Image N-mal mit DERSELBEN
        # job_id eingereiht — der BatchWorker scheitert dann beim zweiten
        # `JobStateMachine.transition(job, PRINTING)` mit
        # InvalidStateTransitionError (Job ist bereits PRINTING) und skippt
        # die Replikate. Live-Log:
        #     "Batch ...: job 711db9bc skipped — state already printing"
        # Resultat: 1 Etikett trotz copies=3.
        #
        # Fix: pro Request UND pro Copy einen eigenen DB-Job-Record mit
        # eindeutiger UUID anlegen, damit der Worker jeden Druck unabhängig
        # transitionen kann. Hangar-Bestellung bleibt 1:1 zur Hangar-Sicht —
        # wir geben nur den ersten ("master") Job pro Request zurück, alle
        # Replikate landen aber in der Hub-DB für Audit/Logging.
        job_ids: list[UUID] = []  # master IDs, 1 pro request — Hangar-API
        all_job_ids: list[UUID] = []  # alle inkl. Copies — für enqueue_batch
        images: list[Image.Image] = []
        for request, opts, (img, ld_dump) in zip(requests, resolved_options, prepared, strict=True):
            n = max(1, int(request.options.copies))
            master_id = uuid4()
            job_ids.append(master_id)
            for copy_idx in range(n):
                this_id = master_id if copy_idx == 0 else uuid4()
                db_job = Job(
                    id=this_id,
                    printer_id=self._printer_id,
                    template_key=None,
                    payload={
                        "tape_mm": tape_mm,
                        "content_type": str(request.content_type),
                        "rendered_tape_mm": tape_mm,
                        "options": opts.model_dump(mode="json"),
                        "label_data": ld_dump,
                        "copy_index": copy_idx,
                        "copy_total": n,
                        "copy_master_id": str(master_id),
                        # #277: a label past the first sub-job prints only after a confirmation;
                        # a restart that finds it still queued fails it instead of printing it.
                        "tape_run": {
                            "run_id": None if run_id is None else str(run_id),
                            "awaits_confirmation": len(all_job_ids) >= MAX_LABELS_PER_TAPE_JOB,
                        },
                    },
                    api_key_id=api_key_id,
                    source_ip=source_ip,
                )
                await self._store.save_queued(db_job)
                images.append(img)
                all_job_ids.append(this_id)

        # 4. Enqueue as BatchJob
        first_options = requests[0].options
        await self._queue.enqueue_batch(
            printer_id=self._printer_id,
            images=images,
            job_ids=all_job_ids,
            tape_mm=tape_mm,
            options={
                "auto_cut": first_options.auto_cut,
                "high_resolution": first_options.high_resolution,
                "half_cut": half_cut,
                "orientation": str(orientation),
            },
            run_id=run_id,
            slot=slot,
        )
        if label_ids is not None:
            label_ids.extend(all_job_ids)

        return job_ids
