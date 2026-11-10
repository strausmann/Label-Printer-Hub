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
from typing import Any, cast
from uuid import UUID, uuid4

from PIL import Image

from app.models.job import Job
from app.printer_backends.exceptions import NoTapeLoadedError, PrinterDisabledError
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.schemas.label_layout import LabelOrientation, LayoutDefault, QlLayoutPreset
from app.schemas.print_request import PrintOptions, PrintRequest, RawLabelData
from app.services.layout_engine import LayoutEngine
from app.services.ql_layout import resolve_layout

_log = logging.getLogger(__name__)


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

    async def submit_print_job(self, request: PrintRequest) -> UUID:
        """Submit a print job: preflight → render → persist → queue.

        Raises:
            PrinterDisabledError (409): Drucker ist deaktiviert (enabled=False).
            NoTapeLoadedError (409): preflight returned loaded_tape_mm=None.
            UnsupportedTapeError (409): tape_mm not in TAPE_GEOMETRY.
            ContentTypeDataMismatchError (422): data missing required fields.
        """

        async def resolve(_tape_mm: int) -> LabelData:
            return await self._resolve_label_data(request)

        return await self._submit_label(
            resolve,
            content_type=request.content_type,
            options=request.options,
            template_key=None,
        )

    async def submit_test_label(self, build: Callable[[int], RawLabelData]) -> UUID:
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
        )

    async def _submit_label(
        self,
        resolve: Callable[[int], Awaitable[LabelData]],
        *,
        content_type: ContentType,
        options: PrintOptions,
        template_key: str | None,
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
            api_key_id=None,
            source_ip=None,
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

    async def _resolve_label_data(self, request: PrintRequest) -> LabelData:
        """Resolve label data from raw request data or lookup service."""
        if request.data is not None:
            raw = request.data
            return LabelData(
                source_app="manual",
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
    ) -> list[UUID]:
        """Phase 1k.2: Render N items, submit ONE BatchJob to PrintQueue.

        Atomic: alle job_ids werden gemeinsam als completed/failed markiert.
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
        # #258: one orientation for the whole batch (like the other collective options it
        # comes from the first request); the backend rotates every image on that one flag.
        orientation, _ = self._resolve_layout(tape_mm, requests[0].options)
        resolved_options = [
            req.options.model_copy(
                update={
                    "orientation": orientation,
                    "layout_preset": self._resolve_layout(
                        tape_mm,
                        req.options.model_copy(update={"orientation": orientation}),
                    )[1],
                }
            )
            for req in requests
        ]

        # 2. Resolve LabelData ONCE per item, then render via LayoutEngine
        async def _prepare_one(
            req: PrintRequest, opts: PrintOptions
        ) -> tuple[Image.Image, dict[str, Any]]:
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
                    },
                    api_key_id=None,
                    source_ip=None,
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
        )

        return job_ids
