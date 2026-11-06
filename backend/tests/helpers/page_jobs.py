"""Shared test doubles for page jobs: a recording outcome handler and payload factories."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.services import page_jobs
from app.services.page_jobs import PageKind, PagePayload

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


@dataclass
class RecordingHandler:
    """Remembers every outcome call in order as ``(name, job_id, kwargs)``."""

    calls: list[tuple[str, UUID, dict[str, Any]]] = field(default_factory=list)

    async def on_started(self, job_id: UUID) -> None:
        self.calls.append(("started", job_id, {}))

    async def on_completed(self, job_id: UUID) -> None:
        self.calls.append(("completed", job_id, {}))

    async def on_ended(self, job_id: UUID, *, state: str, started: bool, error_code: str) -> None:
        self.calls.append(
            ("ended", job_id, {"state": state, "started": started, "error_code": error_code})
        )

    async def on_unknown(self, job_id: UUID) -> None:
        self.calls.append(("unknown", job_id, {}))

    def names(self, job_id: UUID | None = None) -> list[str]:
        return [n for n, j, _ in self.calls if job_id is None or j == job_id]

    def ended(self, job_id: UUID) -> dict[str, Any]:
        found = [kw for n, j, kw in self.calls if n == "ended" and j == job_id]
        assert len(found) == 1, self.calls
        return found[0]


def payload(kind: PageKind = "calibration_page", **detail: Any) -> PagePayload:
    return PagePayload(
        kind=kind,
        media="A4",
        tray="auto",
        render_dpi=600,
        job_name="Calibration page · test v1",
        calibration=None,
        detail=dict(detail),
    )


@contextmanager
def registered(handler: RecordingHandler, render: Any = None) -> Iterator[RecordingHandler]:
    """Register ``handler`` (and a renderer) for both kinds; restore the registries after."""
    saved_r = dict(page_jobs._RENDERERS)
    saved_h = dict(page_jobs._HANDLERS)
    fn = render if render is not None else (lambda _p: PDF)
    for kind in ("sheet_page", "calibration_page"):
        page_jobs.register_page_renderer(kind, fn)  # type: ignore[arg-type]
        page_jobs.register_outcome_handler(kind, handler)  # type: ignore[arg-type]
    try:
        yield handler
    finally:
        page_jobs._RENDERERS.clear()
        page_jobs._RENDERERS.update(saved_r)
        page_jobs._HANDLERS.clear()
        page_jobs._HANDLERS.update(saved_h)
