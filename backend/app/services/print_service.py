"""PrintService — orchestrates template, label data, render, queue.submit."""

from __future__ import annotations

from typing import Protocol

from PIL import Image

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
    ) -> None:
        self._loader = template_loader
        self._renderer = renderer
        self._queue = print_queue
        self._lookup = lookup_service
        self._printer_id = printer_id

    async def submit_print_job(self, request: PrintRequest) -> str:
        template = self._loader.get(request.template_id)

        if request.lookup is not None:
            label_data = await self._lookup.lookup(request.lookup.app, request.lookup.identifier)
        else:
            assert request.data is not None
            label_data = LabelData(
                title=request.data.title,
                primary_id=request.data.primary_id,
                qr_payload=request.data.qr_payload,
                secondary=tuple(request.data.secondary),
                source_app="manual",
            )

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
