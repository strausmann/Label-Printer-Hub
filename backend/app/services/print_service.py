"""PrintService — orchestrates template, label data, render, queue.submit."""

from __future__ import annotations

from typing import Protocol

from PIL import Image

from app.printer_backends.exceptions import TapeMismatchError
from app.printer_backends.snmp_helper import PreflightStatus
from app.schemas.label_data import LabelData
from app.schemas.print_request import PrintRequest
from app.schemas.template import TemplateSchema
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
        printer_id: str,
        backend: _BackendProto,
    ) -> None:
        self._loader = template_loader
        self._renderer = renderer
        self._queue = print_queue
        self._lookup = lookup_service
        self._printer_id = printer_id
        self._backend = backend

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

    async def submit_print_job(self, request: PrintRequest) -> str:
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

            # "queue" path: create the job already in PAUSED state so the worker
            # can never dequeue it between submit and pause (submit_paused() does
            # NOT place the job in the asyncio.Queue — atomic, no race window).
            label_data = await self._resolve_label_data(request)
            image = self._renderer.render(template, label_data)
            job_id = await self._queue.submit_paused(
                self._printer_id,
                image,
                tape_mm=template.tape_mm,
                auto_cut=request.options.auto_cut,
                high_resolution=request.options.high_resolution,
            )
            job = await self._queue.get(job_id)
            job.error_code = "tape_mismatch"
            job.error_message = str(mismatch)
            job.error_detail = {
                "expected_mm": template.tape_mm,
                "loaded_mm": preflight.loaded_tape_mm,
            }
            return job_id

        # 4. Happy path: resolve label data, render, submit.
        label_data = await self._resolve_label_data(request)
        image = self._renderer.render(template, label_data)

        # `copies` is intentionally not forwarded — multi-copy delivery is
        # a Phase-5 follow-up. Clients can post N times today.
        return await self._queue.submit(
            self._printer_id,
            image,
            tape_mm=template.tape_mm,
            auto_cut=request.options.auto_cut,
            high_resolution=request.options.high_resolution,
        )
