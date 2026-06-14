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
import logging
from typing import Any, cast
from uuid import UUID, uuid4

from PIL import Image

from app.models.job import Job
from app.printer_backends.exceptions import NoTapeLoadedError
from app.schemas.label_data import LabelData
from app.schemas.print_request import PrintRequest
from app.services.layout_engine import LayoutEngine

_log = logging.getLogger(__name__)


class PrintService:
    """Orchestrate preflight → render → persist → queue.submit."""

    def __init__(
        self,
        *,
        printer_id: UUID,
        backend: Any,  # PrinterBackend protocol
        queue: Any,  # PrintQueue protocol
        store: Any,  # JobStore protocol
        engine: LayoutEngine,
        lookup_service: Any = None,  # optional LookupService protocol
    ) -> None:
        self._printer_id = printer_id
        self._backend = backend
        self._queue = queue
        self._store = store
        self._engine = engine
        self._lookup_service = lookup_service

    async def submit_print_job(self, request: PrintRequest) -> UUID:
        """Submit a print job: preflight → render → persist → queue.

        Raises:
            NoTapeLoadedError (409): preflight returned loaded_tape_mm=None.
            UnsupportedTapeError (409): tape_mm not in TAPE_GEOMETRY.
            ContentTypeDataMismatchError (422): data missing required fields.
        """
        preflight = await self._backend.preflight_check()
        if preflight.loaded_tape_mm is None:
            raise NoTapeLoadedError()

        label_data = await self._resolve_label_data(request)
        # asyncio.to_thread: render() is CPU-bound (QR generation + font rendering).
        # Offloading keeps the event loop responsive for concurrent requests.
        # Matches the pattern already used in submit_batch_job._prepare_one.
        image = await asyncio.to_thread(
            self._engine.render,
            preflight.loaded_tape_mm,
            request.content_type,
            label_data,
        )

        job_id = uuid4()
        job = Job(
            id=job_id,
            printer_id=self._printer_id,
            template_key=None,
            payload={
                "label_data": label_data.model_dump(),
                "content_type": str(request.content_type),
                "rendered_tape_mm": preflight.loaded_tape_mm,
                "tape_mm": preflight.loaded_tape_mm,
                "options": request.options.model_dump(),
            },
            api_key_id=None,
            source_ip=None,
        )
        await self._store.save_queued(job)
        await self._queue.submit_with_id(
            job_id,
            self._printer_id,
            image,
            tape_mm=preflight.loaded_tape_mm,
            auto_cut=request.options.auto_cut,
            high_resolution=request.options.high_resolution,
            half_cut=request.options.half_cut,
            last_page=request.options.last_page,
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
            await self._lookup_service.resolve(
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

        # 2. Resolve LabelData ONCE per item, then render via LayoutEngine
        async def _prepare_one(
            req: PrintRequest,
        ) -> tuple[Image.Image, dict[str, Any]]:
            label_data = await self._resolve_label_data(req)
            image = await asyncio.to_thread(
                self._engine.render,
                tape_mm,
                req.content_type,
                label_data,
            )
            return image, label_data.model_dump()

        prepared = await asyncio.gather(*[_prepare_one(r) for r in requests])

        # 3. Pre-allocate job UUIDs + persist in JobStore
        # Pro Request 1 Job persistieren (DB-Tracking bleibt 1:1 zur Hangar-Bestellung).
        # Image-Replication für copies > 1 kommt in Schritt 4 (Batch-Enqueue).
        job_ids: list[UUID] = []
        for request, (_img, ld_dump) in zip(requests, prepared, strict=True):
            job_id = uuid4()
            db_job = Job(
                id=job_id,
                printer_id=self._printer_id,
                template_key=None,
                payload={
                    "tape_mm": tape_mm,
                    "content_type": str(request.content_type),
                    "rendered_tape_mm": tape_mm,
                    "options": request.options.model_dump(),
                    "label_data": ld_dump,
                },
                api_key_id=None,
                source_ip=None,
            )
            await self._store.save_queued(db_job)
            job_ids.append(job_id)

        # 3b. Image-Liste für die Hardware aufbauen — Bug 2026-06-14:
        # `PrintOptions.copies > 1` ist im DB-Schema vorgesehen, wurde aber
        # bisher nicht in die Hardware-Druck-Liste übersetzt. Effekt: ein Request
        # mit copies=3 schickte nur 1 Image an print_multi() → 1 Etikett statt 3.
        # Fix: pro Request das Image so oft replizieren wie options.copies sagt.
        # job_ids werden parallel repliziert damit die Längen-Validierung in
        # enqueue_batch passt; duplizierte UUIDs landen einmal im self._jobs-Dict
        # (Dict-Set überschreibt). Der Batch-Worker markiert je Job-ID einmal
        # done — Hangar-Bestellung bleibt 1:N mit den replizierten Etiketten.
        images: list[Image.Image] = []
        expanded_job_ids: list[UUID] = []
        for req, (img, _ld), jid in zip(requests, prepared, job_ids, strict=True):
            n = max(1, int(req.options.copies))
            for _ in range(n):
                images.append(img)
                expanded_job_ids.append(jid)

        # 4. Enqueue as BatchJob
        first_options = requests[0].options
        await self._queue.enqueue_batch(
            printer_id=self._printer_id,
            images=images,
            job_ids=expanded_job_ids,
            tape_mm=tape_mm,
            options={
                "auto_cut": first_options.auto_cut,
                "high_resolution": first_options.high_resolution,
                "half_cut": half_cut,
            },
        )

        return job_ids
