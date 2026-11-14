# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Grocy labels onto sheets of a page printer (#281, spec R-281-13 to R-281-17).

One Grocy label takes one cell: the lowest free cell of the type's fullest started sheet, else
cell 1 of a new sheet with the sheet ID in the margin.

The webhook answers within its budget (R-281-11), so the request only stores a ``queued`` row
with ``payload.deferred`` and no reservation (``GrocySheetLabels.accept``). A tracked task then
chooses the sheet and runs the ordinary sheet print with the row's own id
(``print_sheets(job_id=...)``): the reservation under the sheet write lock, the page payload,
and the hand-off of the stored row (``PrintQueue.submit_stored_page_job``). Choosing and
reserving run under one ``asyncio.Lock`` per sheet type, so two labels at once never open two
new sheets (R-281-17; the hub is one process, ADR 0015).

A stop or a re-wire ends a row that was not handed off yet ``failed`` with
``deferred_interrupted`` and frees its cell; after a crash the queue's recovery does.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.job import Job, JobState
from app.models.printer import Printer
from app.repositories import sheet_types as types_repo
from app.repositories import sheets as repo
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.schemas.print_request import RawLabelData
from app.schemas.sheet_print import (
    NewSheetModel,
    PlacementInModel,
    SheetItem,
    SheetPrintRequest,
    SheetRawLabelData,
)
from app.services.job_store import JobStore
from app.services.lookup_service import AppLookupService
from app.services.page_jobs import notify_ended
from app.services.print_queue import DEFERRED_INTERRUPTED, JobNoLongerQueuedError
from app.services.producers.print_queue_producer import publish_job_state_changed
from app.sheets import print_service
from app.sheets.errors import (
    InsufficientCellsError,
    PrinterIdentityMismatchError,
    SheetApiError,
    SheetDiscardedError,
    SheetNotFoundError,
    SheetPrinterDisabledError,
)

_log = logging.getLogger(__name__)

SOURCE = "grocy"
ACTOR = "grocy"
DEFERRED_KIND = "sheet_page"
STOP_BUDGET_S = 2.0
"""How long a stop or a re-wire waits for the tasks and their end writes."""

_FAILED_FALLBACK = "The label could not be printed onto a sheet."
_INTERRUPTED_MESSAGE = "The hub stopped before the label was handed to the printer."

# The chosen sheet had no free cell any more once the lock was held: choose once more.
_SHEET_GONE = (InsufficientCellsError, SheetDiscardedError, SheetNotFoundError)


async def choose_grocy_sheet(session: AsyncSession, type_key: str) -> str | None:
    """The code of the sheet a Grocy label of ``type_key`` goes to; ``None``: a new sheet.

    Among the type's ``active`` sheets with at least one free cell (free: not used, reserved
    or unconfirmed), every version counted, the one with the **fewest** free cells; equal
    counts by ``(len(code), code)``. That is the print page's rule (``fittingFirst``) for one
    label. An unknown type has no sheets.
    """
    sheet_type = await types_repo.get_by_key(session, type_key)
    if sheet_type is None:
        return None
    rows = await repo.list_with_counts(session, type_id=sheet_type.id, sheet_state="active")
    candidates: list[tuple[int, int, str]] = []
    for sheet, _type, version, used, reserved, unconfirmed in rows:
        free = version.cols * version.rows - used - reserved - unconfirmed
        if free > 0:
            candidates.append((free, len(sheet.code), sheet.code))
    return min(candidates)[2] if candidates else None


class _NoLookup:
    """A Grocy item carries its data; the sheet print never asks an integration for it."""

    async def lookup(self, app: str, identifier: str) -> LabelData:  # noqa: ARG002
        raise RuntimeError(f"no lookup for Grocy sheet labels ({app})")


class GrocySheetLabels:
    """Deferred Grocy labels onto the sheets of page printers (R-281-16).

    ``queue`` is the ``PrintQueue`` (the hand-off and the hold check), ``store`` the job store
    of the app, ``settings_store`` the runtime settings (the hub's language for the margin ID).
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        queue: Any,
        store: JobStore,
        bus: Any,
        settings_store: Any,
    ) -> None:
        self._factory = session_factory
        self._queue = queue
        self._store = store
        self._bus = bus
        self._settings = settings_store
        self._locks: dict[str, asyncio.Lock] = {}
        self._tasks: dict[asyncio.Task[None], tuple[UUID, UUID]] = {}  # task -> (job, printer)

    # ------------------------------------------------------------------ the request

    async def accept(
        self,
        printer: Printer,
        *,
        sheet_type: str,
        raw: RawLabelData,
        content_type: ContentType,
        ref: str,
        api_key_id: UUID | None,
        source_ip: str | None,
    ) -> UUID:
        """Store the ``queued`` row and print it after the caller answered: one insert, no
        reservation. ``ref`` is the Grocycode cut to entity and id (``grcy:p:12``)."""
        label = LabelData(
            source_app=SOURCE,
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
                printer_id=printer.id,
                template_key=None,
                payload={
                    "deferred": True,
                    "deferred_kind": DEFERRED_KIND,
                    "label_data": label.model_dump(),
                    "content_type": str(content_type),
                    "sheet_type": sheet_type,
                },
                api_key_id=api_key_id,
                source_ip=source_ip,
            )
        )
        task = asyncio.create_task(
            self._complete(
                job_id,
                printer.id,
                sheet_type=sheet_type,
                raw=raw,
                content_type=content_type,
                ref=ref,
                api_key_id=api_key_id,
                source_ip=source_ip,
            ),
            name=f"grocy-sheet-{job_id}",
        )
        self._tasks[task] = (job_id, printer.id)
        task.add_done_callback(lambda done: self._tasks.pop(done, None))
        return job_id

    async def record_failed(
        self,
        printer_id: UUID,
        error_code: str,
        *,
        message: str,
        api_key_id: UUID | None,
        source_ip: str | None,
    ) -> UUID:
        """Store a ``failed`` job on the page printer for a label that could not be built
        (``grocy_label_invalid``, ``grocy_label_mismatch``). ``message`` is a fixed sentence."""
        job_id = uuid4()
        await self._store.save_queued(
            Job(
                id=job_id,
                printer_id=printer_id,
                template_key=None,
                state=JobState.FAILED.value,
                # ``content_error`` tells a retry there is no label to print again.
                payload={"label_data": {"source_app": SOURCE}, "content_error": error_code},
                error=f"{error_code}: {message}",
                api_key_id=api_key_id,
                source_ip=source_ip,
                finished_at=datetime.now(UTC),
            )
        )
        self._publish_failed(printer_id, job_id, error_code)
        return job_id

    # ------------------------------------------------------------------ the task

    async def _after_choice(self, code: str | None) -> None:
        """A seam between the choice and the print, inside the per-type lock. A no-op by
        default; only tests replace it."""
        del code

    def _lock(self, type_key: str) -> asyncio.Lock:
        return self._locks.setdefault(type_key, asyncio.Lock())

    async def _complete(
        self,
        job_id: UUID,
        printer_id: UUID,
        *,
        sheet_type: str,
        raw: RawLabelData,
        content_type: ContentType,
        ref: str,
        api_key_id: UUID | None,
        source_ip: str | None,
    ) -> None:
        try:
            async with self._factory() as session:
                printer = await session.get(Printer, printer_id)
                await session.commit()
            if printer is None or not printer.enabled:
                raise SheetPrinterDisabledError()
            if self._queue.is_identity_held(printer_id) is True:  # #231
                raise PrinterIdentityMismatchError(printer_id)
            if content_type is ContentType.QR_THREE_LINES and not raw.secondary:
                content_type = ContentType.QR_TWO_LINES  # R-281-7: no third line to show
            item = SheetItem(
                content_type=content_type,
                data=SheetRawLabelData(**raw.model_dump()),
                source=SOURCE,
                ref=ref,
            )
            language = self._settings.get("general.language")
            async with self._lock(sheet_type):
                for attempt in (1, 2):
                    async with self._factory() as session:
                        code = await choose_grocy_sheet(session, sheet_type)
                        await session.commit()
                    await self._after_choice(code)
                    placement = (
                        PlacementInModel(new_sheet=NewSheetModel(type=sheet_type))
                        if code is None
                        else PlacementInModel(sheet=code)
                    )
                    try:
                        await print_service.print_sheets(
                            self._factory,
                            printer=printer,
                            request=SheetPrintRequest(items=[item], placements=[placement]),
                            lookup=cast(AppLookupService, _NoLookup()),
                            queue=self._queue,
                            actor=ACTOR,
                            api_key_id=api_key_id,
                            source_ip=source_ip,
                            language=None if language is None else str(language),
                            bus=self._bus,
                            job_id=job_id,
                            source_app=SOURCE,
                        )
                        return
                    except _SHEET_GONE:
                        # Filled or discarded between the choice and the lock (R-281-16).
                        if code is None or attempt == 2:
                            raise
        except asyncio.CancelledError:
            raise
        except JobNoLongerQueuedError:
            return  # cancelled meanwhile: not a failure, nothing to announce
        except Exception as exc:
            await self._fail(job_id, printer_id, exc)

    async def _fail(self, job_id: UUID, printer_id: UUID, exc: Exception) -> None:
        if isinstance(exc, SheetApiError):
            code, message, detail = exc.error_code, exc.message, exc.detail
        else:
            code, message, detail = "internal_error", _FAILED_FALLBACK, None
            # The type only: a database error quotes its parameters, the label data (266-13).
            _log.error("Grocy sheet label %s failed (%s)", job_id, type(exc).__name__)
        # Only a row that changed is announced: a job the user cancelled stays cancelled.
        if await self._store.mark_failed_code(job_id, code, message, _plain(detail)):
            self._publish_failed(printer_id, job_id, code)

    def _publish_failed(self, printer_id: UUID, job_id: UUID, error_code: str) -> None:
        publish_job_state_changed(
            self._bus,
            printer_id=printer_id,
            job_id=job_id,
            from_state=JobState.QUEUED.value,
            to_state=JobState.FAILED.value,
            error_code=error_code,
        )

    # ------------------------------------------------------------------ stop and re-wire

    async def cancel_for(self, printer_id: UUID) -> None:
        """Cancel the running tasks of ``printer_id`` and end their rows (a detach, a re-wire).

        Runs before the printer's recovery, so recovery never ends a row whose task still
        reserves (R-281-16)."""
        await self._cancel(lambda pid: pid == printer_id)

    async def cancel_pending(self) -> None:
        """Cancel every running task and end its row (the app stops). A row this does not end
        in time is ended by the next start's recovery."""
        await self._cancel(lambda _pid: True)

    async def _cancel(self, wanted: Callable[[UUID], bool]) -> None:
        tasks = {t: ids for t, ids in self._tasks.items() if wanted(ids[1])}
        if not tasks:
            return
        for task in tasks:
            task.cancel()
        try:
            async with asyncio.timeout(STOP_BUDGET_S):
                await asyncio.gather(*tasks, return_exceptions=True)
                for job_id, printer_id in tasks.values():
                    await self._end_interrupted(job_id, printer_id)
        except Exception as exc:  # TimeoutError, a locked database: the stop goes on
            _log.warning(
                "Grocy sheet label(s) left for the start-up recovery (%s)", type(exc).__name__
            )

    async def _end_interrupted(self, job_id: UUID, printer_id: UUID) -> None:
        """A row that was not handed off yet ends ``failed`` ``deferred_interrupted`` and frees
        what it still reserves; a handed-off row belongs to the queue and is left alone."""
        row = await self._store.get(job_id)
        if row is None or row.state != JobState.QUEUED.value or not is_deferred_sheet(row.payload):
            return
        if await self._store.mark_failed_code(
            job_id, DEFERRED_INTERRUPTED, _INTERRUPTED_MESSAGE, None
        ):
            await notify_ended(
                DEFERRED_KIND,
                job_id,
                state="failed",
                started=False,
                error_code=DEFERRED_INTERRUPTED,
            )
            self._publish_failed(printer_id, job_id, DEFERRED_INTERRUPTED)


def is_deferred_sheet(payload: Any) -> bool:
    """Whether a job payload is a Grocy sheet label that was not handed off yet."""
    return (
        isinstance(payload, Mapping)
        and payload.get("deferred") is True
        and payload.get("deferred_kind") == DEFERRED_KIND
    )


def _plain(detail: dict[str, Any] | None) -> dict[str, Any] | None:
    """The error detail kept on the job: plain values only, never label content."""
    if not detail:
        return None
    return {k: v for k, v in detail.items() if isinstance(v, (int, str, bool, list))}
