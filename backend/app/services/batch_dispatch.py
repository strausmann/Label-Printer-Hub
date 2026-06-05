"""Batch-Dispatcher: orchestriert POST /api/print/{slug}/batch.

Phase 1k.1a Task 17: tape-consistency-Check entfernt, weil tape-unabhängige
ContentTypes gemischte ContentTypes pro Batch erlauben — alle Items rendern
auf der gleichen loaded_tape_mm (wird 1x via Preflight von PrintService gelesen).
MixedTapeSizesError + _validate_item_get_tape_mm vollständig entfernt.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from app.schemas.print_request import PrintRequest

if TYPE_CHECKING:
    from app.services.print_service import PrintService


async def dispatch_batch(
    *,
    service: PrintService,
    items: list[PrintRequest],
    half_cut: bool = False,
) -> list[UUID]:
    """Submit a batch of mixed-ContentType print requests.

    Phase 1k.1a: tape consistency check entfernt — alle Items rendern auf der
    gleichen loaded_tape_mm. PrintService.submit_batch_job erledigt Preflight,
    Render und Job-Persistenz.

    Args:
        service: PrintService-Instanz für den Ziel-Drucker.
        items: Liste von PrintRequest-Objekten (mindestens einer).
        half_cut: Half-Cut zwischen Labels aktivieren (Standard: False).

    Returns:
        list[UUID]: Job-IDs aller eingereihten Print-Jobs.

    Raises:
        ValueError: items ist leer.
    """
    if not items:
        msg = "Batch must contain at least one item."
        raise ValueError(msg)
    return await service.submit_batch_job(items, half_cut=half_cut)
