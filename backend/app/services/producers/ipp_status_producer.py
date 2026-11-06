"""Polls an IPP page printer; writes the status cache and publishes ``printer.status`` on change.

D18: chosen by backend kind (``ipp``); tape printers keep ``StatusProbeProducer``.

The producer talks to a network device it does not control, so it is defensive:

- one probe is bounded by the client's timeouts plus an overall guard (``PROBE_GUARD_S``);
- probes of several printers share an optional semaphore (bounded concurrency);
- after consecutive failures the interval doubles up to ``MAX_BACKOFF_S``;
- nothing a printer sends can end the loop: every exception except cancellation is
  turned into an ``online=false`` record;
- logs carry the printer name and the error class, never the URI and never the attribute
  payload; the offline transition is logged once at warning level, the rest at debug;
- the event is published only when the mapped record (or the online flag) changed.

The in-memory ``IppPrinterState`` is what ``PagePrinter.summary()/status()`` (Task 7) read
without I/O. The queue is handed over in Task 7; until then ``pause_control`` is ``None``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.printer_backends.ipp.attributes import (
    PRINTER_ATTRS,
    IppStatusRecord,
    ProbeSummary,
    map_status,
)
from app.printer_backends.ipp.client import IppClient
from app.services.event_bus import BusEvent, EventBus
from app.services.print_queue import PauseInfo

_log = logging.getLogger(__name__)

MAX_BACKOFF_S = 300.0
PROBE_GUARD_S = 20.0
MAX_BACKOFF_DOUBLINGS = 6


class PauseControl(Protocol):
    """The slice of ``PrintQueue`` the producer needs for auto-resume (OC-22)."""

    def pause_info(self, printer_id: UUID) -> PauseInfo | None: ...

    async def resume_printer(self, printer_id: UUID) -> None: ...


@dataclass
class IppPrinterState:
    """Latest probe result of one IPP printer, read synchronously by the page-job path.

    ``own_job_ids`` holds the printer job ids the hub is tracking itself (written by the
    page job runner in Task 7); they are not counted as jobs ahead.
    """

    summary: ProbeSummary | None = None
    status: IppStatusRecord | None = None
    own_job_ids: set[int] = field(default_factory=set)


def _empty_summary() -> ProbeSummary:
    return ProbeSummary(
        make_and_model=None,
        ipp_versions=[],
        pdf_supported=False,
        pdf_versions=[],
        resolutions_dpi=[],
        media_sizes=[],
        media_types=[],
        media_sources=[],
        color_modes=[],
        margins_hmm=None,
        media_col_supported=False,
        media_col_members=[],
        accepting_jobs=None,
        scaling_none_supported=False,
        monochrome_supported=False,
        one_sided_supported=False,
        state="unknown",
    )


def _offline_record(previous: IppStatusRecord | None) -> IppStatusRecord:
    """The last known snapshot flagged offline, or a stopped placeholder before any answer."""
    if previous is not None:
        return previous.model_copy(update={"online": False})
    return IppStatusRecord(
        online=False,
        printer_state="stopped",
        reasons=[],
        blocking_reason=None,
        warnings=[],
        markers=[],
        trays=[],
        jobs_ahead=None,
        summary=_empty_summary(),
    )


def page_status_event_data(parsed: Mapping[str, Any]) -> dict[str, Any]:
    """The small ``printer.status`` payload of a page printer, from a cache ``parsed`` dict."""
    reasons = parsed.get("reasons") or []
    return {
        "kind": "page",
        "online": bool(parsed.get("online", False)),
        "printer_state": parsed.get("printer_state"),
        "blocking_reason": parsed.get("blocking_reason"),
        "reasons": [r.get("keyword") for r in reasons if isinstance(r, Mapping)][:32],
        "jobs_ahead": parsed.get("jobs_ahead"),
    }


class IppStatusProducer:
    """Background probe loop for one IPP printer. Owns ``client`` and closes it on ``stop()``."""

    def __init__(
        self,
        *,
        bus: EventBus,
        printer_id: UUID,
        client: IppClient,
        session_factory: async_sessionmaker[AsyncSession],
        state: IppPrinterState,
        pause_control: PauseControl | None,
        interval_s: float,
        limiter: asyncio.Semaphore | None = None,
        log_name: str | None = None,
    ) -> None:
        self._bus = bus
        self._printer_id = printer_id
        self._client = client
        self._session_factory = session_factory
        self._state = state
        self._pause = pause_control
        self._interval_s = interval_s
        self._limiter = limiter
        self._log_name = log_name or str(printer_id)
        self._last_key: dict[str, Any] | None = None
        self._failures = 0
        self._task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name=f"ipp-status-{self._printer_id}")

    async def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self._client.aclose()

    def next_delay(self) -> float:
        """Interval, doubled per consecutive failure up to ``MAX_BACKOFF_S``."""
        if self._failures == 0:
            return self._interval_s
        doublings = min(self._failures, MAX_BACKOFF_DOUBLINGS)
        return float(min(MAX_BACKOFF_S, max(self._interval_s, self._interval_s * (2**doublings))))

    async def _loop(self) -> None:
        while True:
            try:
                await self.probe_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - probe_once handles its own errors
                _log.exception("IPP status loop for %s: unexpected error", self._log_name)
            await asyncio.sleep(self.next_delay())

    # ------------------------------------------------------------------ one probe

    async def probe_once(self) -> IppStatusRecord | None:
        """One probe cycle. Returns the record, or ``None`` when the printer did not answer."""
        if self._limiter is not None:
            async with self._limiter:
                return await self._probe()
        return await self._probe()

    async def _probe(self) -> IppStatusRecord | None:
        try:
            record = await asyncio.wait_for(self._query(), timeout=PROBE_GUARD_S)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._on_failure(exc)
            return None
        if self._failures:
            _log.info("IPP printer %s is reachable again", self._log_name)
        self._failures = 0
        self._state.summary = record.summary
        self._state.status = record
        await self._write_cache(record, last_error=None)
        self._publish_if_changed(record)
        await self._maybe_resume(record)
        return record

    async def _query(self) -> IppStatusRecord:
        attrs = await self._client.get_printer_attributes(PRINTER_ATTRS)
        record = map_status(attrs)
        ahead = await self._jobs_ahead()
        if ahead is not None:
            record = record.model_copy(update={"jobs_ahead": ahead})
        return record

    async def _jobs_ahead(self) -> int | None:
        """Not-completed jobs on the printer without the ones the hub tracks itself."""
        try:
            jobs = await self._client.get_jobs("not-completed")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log.debug("IPP job count for %s unavailable (%s)", self._log_name, type(exc).__name__)
            return None
        own = self._state.own_job_ids
        return sum(1 for j in jobs if j.job_id not in own)

    async def _on_failure(self, exc: Exception) -> None:
        first = self._failures == 0
        self._failures += 1
        offline = _offline_record(self._state.status)
        self._state.status = offline
        if self._state.summary is None:
            self._state.summary = offline.summary
        message = type(exc).__name__  # no URI, no printer-supplied text
        (_log.warning if first else _log.debug)(
            "IPP printer %s not usable (%s)", self._log_name, message
        )
        await self._write_cache(offline, last_error=message)
        self._publish_if_changed(offline)

    # ------------------------------------------------------------------ outputs

    async def _write_cache(self, record: IppStatusRecord, *, last_error: str | None) -> None:
        from app.models.printer_status_cache import PrinterStatusCache

        parsed: dict[str, Any] = record.model_dump(mode="json")
        if last_error is not None:
            parsed["last_error"] = last_error
        now = datetime.now(UTC)
        try:
            async with self._session_factory() as s:
                row = await s.get(PrinterStatusCache, self._printer_id)
                if row is not None:
                    row.parsed = parsed
                    row.raw_block = None
                    row.captured_at = now
                else:
                    s.add(
                        PrinterStatusCache(
                            printer_id=self._printer_id, parsed=parsed, captured_at=now
                        )
                    )
                await s.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log.warning(
                "IPP status cache write for %s failed (%s)", self._log_name, type(exc).__name__
            )

    def _publish_if_changed(self, record: IppStatusRecord) -> None:
        data = page_status_event_data(record.model_dump(mode="json"))
        if data == self._last_key:
            return
        self._last_key = data
        channel = f"printer:{self._printer_id}:state"
        self._bus.publish(
            channel,
            BusEvent(
                channel=channel,
                event_id=self._bus.next_event_id(channel),
                event_type="printer.status",
                timestamp=datetime.now(UTC),
                data=data,
            ),
        )

    async def _maybe_resume(self, record: IppStatusRecord) -> None:
        """OC-22: lift a pause the printer's own error caused; never a user pause."""
        if self._pause is None or not record.online or record.blocking_reason is not None:
            return
        try:
            info = self._pause.pause_info(self._printer_id)
            if info is not None and info.source == "printer_error":
                await self._pause.resume_printer(self._printer_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log.warning("IPP auto-resume for %s failed (%s)", self._log_name, type(exc).__name__)
