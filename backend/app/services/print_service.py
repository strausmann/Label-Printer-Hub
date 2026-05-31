"""PrintService — orchestrates template, label data, render, queue.submit."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from PIL import Image

from app.models.job import Job
from app.printer_backends.exceptions import TapeMismatchError
from app.printer_backends.snmp_helper import PreflightStatus
from app.schemas.label_data import LabelData
from app.schemas.print_request import PrintRequest
from app.schemas.template import TemplateSchema
from app.services.job_store import JobStore, MemoryJobStore
from app.services.print_queue import PrintQueue


class _TemplateLoaderProto(Protocol):
    def get(self, template_id: str) -> TemplateSchema: ...


class _RendererProto(Protocol):
    def render(self, template: TemplateSchema, label_data: LabelData) -> Image.Image: ...


class _LookupServiceProto(Protocol):
    async def lookup(self, app: str, identifier: str) -> LabelData: ...


class _BackendProto(Protocol):
    async def preflight_check(self) -> PreflightStatus: ...


class PrintService:
    """Use-case orchestrator for POST /print."""

    def __init__(
        self,
        *,
        template_loader: _TemplateLoaderProto,
        renderer: _RendererProto,
        print_queue: PrintQueue,
        lookup_service: _LookupServiceProto,
        printer_id: UUID,
        backend: _BackendProto,
        store: JobStore | None = None,
    ) -> None:
        self._loader = template_loader
        self._renderer = renderer
        self._queue = print_queue
        self._lookup = lookup_service
        self._printer_id = printer_id
        self._backend = backend
        # Phase 2: JobStore für Persistierung vor queue.submit.
        # Default MemoryJobStore für Backward-Compat mit Pre-Phase-2-Tests —
        # Production-Code wired in Lifespan explizit SQLiteJobStore ein (Task 9).
        self._store: JobStore = store if store is not None else MemoryJobStore()

    async def _resolve_label_data(self, request: PrintRequest) -> LabelData:
        """Resolve label data from lookup or raw request data."""
        if request.lookup is not None:
            return await self._lookup.lookup(request.lookup.app, request.lookup.identifier)
        assert request.data is not None
        return LabelData(
            title=request.data.title,
            primary_id=request.data.primary_id,
            qr_payload=request.data.qr_payload,
            secondary=tuple(request.data.secondary),
            source_app="manual",
        )

    async def submit_print_job(self, request: PrintRequest) -> UUID:
        """Orchestrate template-load → preflight → render → persist → queue.submit.

        Phase-2-Limitationen:
        - on_tape_mismatch=queue: PAUSED-Jobs bleiben in-memory-only bis resume.
          Hub-Restart während PAUSED löscht den Job — Phase-2-Trade-off.
          Phase 3 (Issue #95 wenn erstellt) wird PAUSED in JobState enum aufnehmen
          + DB-Migration für persistenten paused-state.
        - tape_mismatch Metadaten (error_code, error_message, error_detail) werden
          nur in-memory gehalten; keine DB-Row im PAUSED-Pfad.
        """
        # 1. Load template — fail fast before any I/O if template is unknown.
        template = self._loader.get(request.template_id)

        # 2. SNMP preflight — raises PrinterOfflineError, TapeEmptyError,
        #    PrinterCoverOpenError synchronously if the printer is not ready.
        preflight = await self._backend.preflight_check()

        # 3. Tape-mismatch check — two outcomes depending on on_tape_mismatch.
        if preflight.loaded_tape_mm != template.tape_mm:
            mismatch = TapeMismatchError(
                expected_mm=template.tape_mm,
                loaded_mm=preflight.loaded_tape_mm,
            )
            if request.on_tape_mismatch == "fail":
                raise mismatch

            # "queue" path: PAUSED-Jobs NICHT in DB persistieren.
            # C-1-Fix: save_queued würde den Job als QUEUED in DB ablegen, aber
            # PAUSED ist kein gültiger JobState-Wert. Nach Hub-Restart würde
            # list_pending() den Job als QUEUED finden und sofort drucken —
            # obwohl der User noch den Tape wechseln muss (Doppel-Druck-Risiko).
            # Trade-off: Job geht bei Hub-Restart verloren, nichts wurde gedruckt.
            # R2-M3: PrintRequest hat KEINE api_key_id/source_ip Felder.
            # AuthContext-Integration folgt in einem späteren Task.
            label_data = await self._resolve_label_data(request)
            image = self._renderer.render(template, label_data)
            paused_job_id = Job(  # noqa: F841  — id wird aus submit_paused_with_id geholt
                printer_id=self._printer_id,
                template_key=request.template_id,
                payload={
                    "label_data": label_data.model_dump(),
                    "tape_mm": template.tape_mm,
                    "options": {
                        "auto_cut": request.options.auto_cut,
                        "high_resolution": request.options.high_resolution,
                    },
                },
                api_key_id=None,   # TODO: aus AuthContext wenn Endpoint-Layer angepasst
                source_ip=None,    # TODO: aus AuthContext wenn Endpoint-Layer angepasst
            )
            # Keine save_queued() — Job bleibt in-memory-only bis resume.
            await self._queue.submit_paused_with_id(
                paused_job_id.id,
                self._printer_id,
                image,
                tape_mm=template.tape_mm,
                auto_cut=request.options.auto_cut,
                high_resolution=request.options.high_resolution,
            )
            # Tape-mismatch Metadaten an den in-memory Job anhängen
            in_memory_job = await self._queue.get(str(paused_job_id.id))
            in_memory_job.error_code = "tape_mismatch"
            in_memory_job.error_message = str(mismatch)
            in_memory_job.error_detail = {
                "expected_mm": template.tape_mm,
                "loaded_mm": preflight.loaded_tape_mm,
            }
            return paused_job_id.id

        # 4. Happy path: resolve label data, render, submit.
        # Phase 2: DB-Row anlegen BEVOR an Queue übergeben (Durability-Garantie).
        # R2-M3: PrintRequest hat KEINE api_key_id/source_ip Felder.
        label_data = await self._resolve_label_data(request)
        image = self._renderer.render(template, label_data)
        db_job = Job(
            printer_id=self._printer_id,
            template_key=request.template_id,
            payload={
                "label_data": label_data.model_dump(),
                "tape_mm": template.tape_mm,
                "options": {
                    # `copies` wird nicht weitergeleitet — Phase-5 Follow-up.
                    "auto_cut": request.options.auto_cut,
                    "high_resolution": request.options.high_resolution,
                },
            },
            api_key_id=None,   # TODO: aus AuthContext wenn Endpoint-Layer angepasst
            source_ip=None,    # TODO: aus AuthContext wenn Endpoint-Layer angepasst
        )
        await self._store.save_queued(db_job)
        try:
            await self._queue.submit_with_id(
                db_job.id,
                self._printer_id,
                image,
                tape_mm=template.tape_mm,
                auto_cut=request.options.auto_cut,
                high_resolution=request.options.high_resolution,
            )
        except Exception as exc:
            # I-1-Fix: in-memory Submit fehlgeschlagen nach DB-Persist — Rollback.
            # Ohne diesen Rollback bliebe eine stale QUEUED-Row in der DB ohne
            # Worker-Gegenstück, die nach Hub-Restart fälschlicherweise re-enqueued
            # würde. mark_failed markiert die Row als FAILED und verhindert das.
            await self._store.mark_failed(
                db_job.id,
                f"submit_failed: {exc.__class__.__name__}: {exc}",
            )
            raise
        return db_job.id
