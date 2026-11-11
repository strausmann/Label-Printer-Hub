"""Batch-Dispatcher: orchestriert POST /api/v1/print/{slug}/batch.

Phase 1k.1a Task 17: tape-consistency-Check entfernt, weil tape-unabhängige
ContentTypes gemischte ContentTypes pro Batch erlauben — alle Items rendern
auf der gleichen loaded_tape_mm (wird 1x via Preflight von PrintService gelesen).
MixedTapeSizesError + _validate_item_get_tape_mm vollständig entfernt.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from app.config import get_settings
from app.schemas.print_request import PrintRequest
from app.services.print_queue import MAX_LABELS_PER_TAPE_JOB

if TYPE_CHECKING:
    from app.services.print_queue import PrintQueue
    from app.services.print_service import PrintService


async def dispatch_batch(
    *,
    service: PrintService,
    items: list[PrintRequest],
    half_cut: bool = False,
    run_id: UUID | None = None,
    label_ids: list[UUID] | None = None,
    queue: PrintQueue | None = None,
    printer_id: UUID | None = None,
    api_key_id: UUID | None = None,
    source_ip: str | None = None,
) -> list[UUID]:
    """Submit a batch of mixed-ContentType print requests.

    Phase 1k.1a: tape consistency check entfernt — alle Items rendern auf der
    gleichen loaded_tape_mm. PrintService.submit_batch_job erledigt Preflight,
    Render und Job-Persistenz.

    Args:
        service: PrintService-Instanz für den Ziel-Drucker.
        items: Liste von PrintRequest-Objekten (mindestens einer).
        half_cut: Half-Cut zwischen Labels aktivieren (Standard: False).
        queue, printer_id, api_key_id: with a queue, the batch first claims a place under the
            queued-run caps (263-76, ``PRINTER_HUB_MAX_QUEUED_RUNS_PER_PRINTER`` / ``…_PER_KEY``)
            before anything is looked up, drawn or stored; a submit that fails gives it back.
            ``api_key_id`` and ``source_ip`` are stored on every job row (#294).

    Returns:
        list[UUID]: Job-IDs aller eingereihten Print-Jobs.

    Raises:
        ValueError: items ist leer.
        TooManyQueuedRunsError: the printer or the key has no queued-run place left.
    """
    if not items:
        msg = "Batch must contain at least one item."
        raise ValueError(msg)
    if queue is None or printer_id is None:
        return await service.submit_batch_job(
            items,
            half_cut=half_cut,
            run_id=run_id,
            label_ids=label_ids,
            api_key_id=api_key_id,
            source_ip=source_ip,
        )
    settings = get_settings()
    labels = sum(max(1, int(item.options.copies)) for item in items)
    slot = queue.claim_run_slot(
        printer_id,
        api_key_id,
        per_printer=settings.max_queued_runs_per_printer,
        per_key=settings.max_queued_runs_per_key,
        # Only a run of more than one sub-job waits for a confirmation (#277).
        may_hold=labels > MAX_LABELS_PER_TAPE_JOB,
    )
    try:
        return await service.submit_batch_job(
            items,
            half_cut=half_cut,
            run_id=run_id,
            label_ids=label_ids,
            slot=slot,
            api_key_id=api_key_id,
            source_ip=source_ip,
        )
    finally:
        queue.release_run_slot(slot)  # a no-op once the run took the claim over
