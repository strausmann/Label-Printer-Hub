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
    MediaTypeMismatchError,
    NoTapeLoadedError,
    PrinterDisabledError,
    PrinterReportedError,
    QrPayloadTooLongError,
    SpoolLabelOnlyTapeError,
    TapeMismatchError,
)
from app.printer_backends.snmp_helper import parse_media_kind
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.schemas.label_layout import LabelOrientation, LayoutDefault, QlLayoutPreset
from app.schemas.print_request import PrintOptions, PrintRequest, RawLabelData
from app.schemas.tape_geometry import TAPE_GEOMETRY
from app.services.layout_engine import LayoutEngine
from app.services.lookup_gate import lookup_gate
from app.services.print_error_codes import print_error_code
from app.services.print_queue import DEFERRED_INTERRUPTED, MAX_LABELS_PER_TAPE_JOB
from app.services.producers.print_queue_producer import publish_job_state_changed
from app.services.ql_layout import resolve_layout
from app.services.spool_swatch import SWATCH_TAPES, swatch_for_batch, swatch_orientation
from app.services.test_label import TapeBand, TapeTestText, render_test_label

_log = logging.getLogger(__name__)


# #281 R-281-11: the job error of a deferred job whose completion failed. A fixed sentence per
# code, never the exception text: a backend error can carry the printer's address.
_DEFERRED_FAILURE_MESSAGES: dict[str, str] = {
    "printer_disabled": "The printer is disabled.",
    "printer_offline": "The printer could not be reached.",
    "printer_cover_open": "The printer cover is open.",
    "no_tape_loaded": "No tape is loaded in the printer.",
    "tape_empty": "The tape is empty.",
    "tape_mismatch": "The loaded tape does not fit the label.",
    "media_type_mismatch": "The loaded roll is die-cut labels; only continuous tape prints.",
    "printer_error": "The printer reports an error state.",
    "unsupported_tape": "The loaded tape is not supported.",
    "content_type_data_mismatch": "The label data does not fit the content type.",
    "qr_payload_too_long": "The QR code content is too long for the loaded tape.",
    "snmp_query_failed": "The printer did not answer the status query.",
}
_DEFERRED_FAILURE_FALLBACK = "The label could not be printed."

RollColour = Callable[[UUID, int | None, str | None], Awaitable[str | None]]
"""The colour the operator gave the roll ``(printer_id, width_mm, media_raw)``, if any (#229)."""

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
        roll_colour: RollColour | None = None,
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
        self._roll_colour = roll_colour
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

    def _resolve_layout_for(
        self, tape_mm: int, content_type: ContentType, options: PrintOptions
    ) -> tuple[LabelOrientation, QlLayoutPreset | None]:
        """As ``_resolve_layout``; the swatch label takes its tape's own direction without a
        preset (#346, ``SWATCH_TAPES``): an orientation it is asked for, sent or stored, is
        ignored, never refused."""
        if content_type is ContentType.SPOOL_SWATCH:
            return swatch_orientation(tape_mm) or LabelOrientation.ACROSS, None
        return self._resolve_layout(tape_mm, options)

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
        text: Callable[[int], TapeTestText],
        band: Callable[[int], TapeBand],
        *,
        api_key_id: UUID | None = None,
        source_ip: str | None = None,
    ) -> UUID:
        """Submit the test label (#228, #377): drawn by its own renderer, never the layout engine.

        One preflight decides the tape; ``band`` gives the printable band of the printer model on
        that tape (its ``UnsupportedTapeError`` refuses before anything is rendered) and ``text``
        what the label says. The label always runs along the tape. The job is stored with
        ``template_key="test_label"`` and the text, band and DPI under ``test_label``, so a
        restart or a retry draws the same label again.

        Raises: ``PrinterDisabledError``, the preflight's errors (``PrinterOfflineError``, …),
        ``NoTapeLoadedError``, ``UnsupportedTapeError``.
        """
        tape_mm, roll = await self._loaded_tape_mm()
        tape_band = band(tape_mm)
        label_text = text(tape_mm)
        image = await asyncio.to_thread(render_test_label, tape_mm, label_text, tape_band)
        options = PrintOptions(orientation=LabelOrientation.ALONG)
        label_data = LabelData(
            source_app="manual",
            primary_id=label_text.printer,
            title=f"{label_text.width_mm} mm · {label_text.printed_at}",
        )
        payload = {
            "label_data": label_data.model_dump(),
            "content_type": str(ContentType.TEXT_TWO_LINES),
            "rendered_tape_mm": tape_mm,
            "tape_mm": tape_mm,
            "options": options.model_dump(mode="json"),
            "test_label": {**label_text.to_payload(), "px": tape_band.px, "dpi": tape_band.dpi},
            "loaded_roll": roll,
        }
        return await self._enqueue(
            image,
            payload,
            tape_mm=tape_mm,
            options=options,
            orientation=LabelOrientation.ALONG,
            template_key="test_label",
            api_key_id=api_key_id,
            source_ip=source_ip,
        )

    async def _loaded_tape_mm(self) -> tuple[int, dict[str, Any]]:
        """enabled check → one preflight → the loaded tape width and its roll record."""
        if not self._printer_enabled:
            raise PrinterDisabledError(self._printer_id, self._printer_slug)
        return await self._read_roll()

    async def _read_roll(self) -> tuple[int, dict[str, Any]]:
        """One fresh preflight (never a cached status): the loaded width and ``loaded_roll``.

        #389: every tape job records the roll that was loaded when it was drawn: width, the
        printer's media text, its kind and the colour the operator gave the roll, so a failed
        print can be traced. A die-cut roll is refused (``MediaTypeMismatchError``): the hub
        draws and sends continuous tape only. A status that cannot be read raises the
        preflight's error (``PrinterOfflineError``): nothing is guessed.
        """
        preflight = await self._backend.preflight_check()
        if preflight.loaded_tape_mm is None:
            raise NoTapeLoadedError()
        raw = getattr(preflight, "media_raw", None)
        media_raw = raw if isinstance(raw, str) else None
        media_kind = parse_media_kind(media_raw)
        if media_kind == "die_cut":
            raise MediaTypeMismatchError(loaded_kind=media_kind, media_raw=media_raw)
        tape_mm: int = preflight.loaded_tape_mm
        colour: str | None = None
        if self._roll_colour is not None:
            try:
                colour = await self._roll_colour(self._printer_id, tape_mm, media_raw)
            except Exception:
                # The colour is for the record only: a failed read never stops the print.
                _log.warning("Roll colour of printer %s could not be read", self._printer_id)
        return tape_mm, {
            "width_mm": tape_mm,
            "media_raw": media_raw,
            "media_kind": media_kind,
            "colour": colour,
        }  # the same keys as ``snmp_helper.roll_record`` plus the colour

    async def _enqueue(
        self,
        image: Image.Image,
        payload: dict[str, Any],
        *,
        tape_mm: int,
        options: PrintOptions,
        orientation: LabelOrientation,
        template_key: str | None,
        api_key_id: UUID | None,
        source_ip: str | None,
    ) -> UUID:
        """Persist the job, then hand its image to the queue."""
        job_id = uuid4()
        job = Job(
            id=job_id,
            printer_id=self._printer_id,
            template_key=template_key,
            payload=payload,
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
        tape_mm, roll = await self._loaded_tape_mm()
        orientation, preset = self._resolve_layout_for(tape_mm, content_type, options)
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

        payload = {
            "label_data": label_data.model_dump(),
            "content_type": str(content_type),
            "rendered_tape_mm": tape_mm,
            "tape_mm": tape_mm,
            "options": options.model_dump(mode="json"),
            "loaded_roll": roll,
        }
        return await self._enqueue(
            image,
            payload,
            tape_mm=tape_mm,
            options=options,
            orientation=orientation,
            template_key=template_key,
            api_key_id=api_key_id,
            source_ip=source_ip,
        )

    # ------------------------------------------------------------------ deferred jobs (#281)

    async def accept_deferred_job(
        self,
        raw: RawLabelData,
        *,
        content_type: ContentType,
        source_app: str,
        api_key_id: UUID | None,
        source_ip: str | None,
        retry_of: UUID | None = None,
    ) -> UUID:
        """Store a ``queued`` job and complete it after the caller has answered (R-281-11).

        The row holds the label data, the requested content type and ``deferred: true``, but
        no tape fields yet. A tracked task then runs preflight -> tape -> render (a
        ``qr_three_lines`` label without a secondary line prints as ``qr_two_lines``) ->
        completes the payload -> hands it to the queue. Any failure there sets the job
        ``failed`` with the code ``POST /api/v1/print`` would answer and publishes
        ``job.state_changed``. A restart before the hand-off ends the job ``failed_restart``
        (the queue's recovery); it is never printed twice. ``retry_of`` names the job this one
        repeats (a retry) and is kept in the payload through the completion.
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
                    **({"retry_of": str(retry_of)} if retry_of is not None else {}),
                },
                api_key_id=api_key_id,
                source_ip=source_ip,
            )
        )
        task = asyncio.create_task(
            self._complete_deferred(job_id, label, content_type, retry_of),
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
        self,
        job_id: UUID,
        label: LabelData,
        requested: ContentType,
        retry_of: UUID | None = None,
    ) -> None:
        try:
            if not self._printer_enabled:
                raise PrinterDisabledError(self._printer_id, self._printer_slug)
            tape_mm, roll = await self._read_roll()
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
                    "loaded_roll": roll,
                    **({"retry_of": str(retry_of)} if retry_of is not None else {}),
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
            elif isinstance(exc, MediaTypeMismatchError):
                detail = {"loaded_kind": exc.loaded_kind, "media_raw": exc.media_raw}
            elif isinstance(exc, PrinterReportedError):
                detail = {"flags": list(exc.flags)}
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
                swatch=raw.swatch,
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
        ``MAX_BATCH_LOOKUPS`` integration lookups run at once across all batches (263-78).

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

        # 1. Preflight (1x für alle): one fresh status read for the whole run (#389).
        tape_mm, roll = await self._read_roll()
        others = sorted(
            {
                str(r.content_type)
                for r in requests
                if r.content_type is not ContentType.SPOOL_SWATCH
            }
        )
        if others and tape_mm in SWATCH_TAPES and tape_mm not in TAPE_GEOMETRY:
            # #346: refused before any lookup, naming the layouts that cannot print here.
            raise SpoolLabelOnlyTapeError(tape_mm=tape_mm, content_types=tuple(others))
        # #258: one orientation for the whole batch; the backend rotates every image on that
        # one flag. Items without an orientation follow the one an item names explicitly;
        # different explicit orientations are refused instead of silently overridden.
        # #346: a swatch item takes no part in choosing the flag; an all-swatch batch takes the
        # tape's spool label direction.
        deciding = [r for r in requests if r.content_type is not ContentType.SPOOL_SWATCH]
        explicit = sorted({str(r.options.orientation) for r in deciding if r.options.orientation})
        if len(explicit) > 1:
            raise ConflictingOrientationError(tuple(explicit))
        if deciding:
            named = next(
                (r.options for r in deciding if r.options.orientation), deciding[0].options
            )
            orientation, _ = self._resolve_layout(tape_mm, named)
        else:
            orientation = swatch_orientation(tape_mm) or LabelOrientation.ACROSS
        resolved_options = [
            req.options.model_copy(
                update={
                    "orientation": orientation,
                    # The batch-level cut mode goes into every stored row, so a recovery after a
                    # restart prints the run with the same cut as the live batch.
                    "half_cut": half_cut,
                    "layout_preset": self._resolve_layout_for(
                        tape_mm,
                        req.content_type,
                        req.options.model_copy(update={"orientation": orientation}),
                    )[1],
                }
            )
            for req in requests
        ]

        # 2. Resolve LabelData ONCE per item, then render via LayoutEngine
        lookups = lookup_gate()  # shared with every other batch and render check

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
            if req.content_type is ContentType.SPOOL_SWATCH:
                # The backend turns every image of an along batch and none of an across one; the
                # swatch is turned so it prints in its own direction either way (#346).
                image = swatch_for_batch(image, tape_mm, opts.orientation)
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
                        "loaded_roll": roll,
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
