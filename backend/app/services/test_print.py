"""Decisions and data of the test print (#228).

Pure helpers plus one async planner that reads the page printer's cached status. The route
turns a ``TestPrintRefusal`` into a ``ProblemDetail``; nothing here talks to a printer.

Taint boundary: the only printer-derived strings that reach a label or a page are the printer's
display name and tray key. The hub URL is rebuilt from scheme, host, port and path of
``public_url``, so credentials in that setting never reach the paper.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.printer import Printer
from app.models.printer_status_cache import PrinterStatusCache
from app.models.printer_tray import PrinterTray
from app.schemas.capabilities import HardwareMargins
from app.schemas.print_request import RawLabelData
from app.services.status_freshness import backoff_of, is_stale
from app.sheets.printer_facts import facts_of, read_status

_DEFAULT_PORTS: Final = {"http": 80, "https": 443}
_A4: Final = re.compile(r"(?<![a-z0-9])(?:a4|210x297(?:mm)?|2100x2970)(?![a-z0-9])", re.IGNORECASE)
_LETTER: Final = re.compile(
    r"(?<![a-z0-9])(?:letter|8\.5x11(?:in)?|21590x27940)(?![a-z0-9])", re.IGNORECASE
)


class TestPrintRefusal(Exception):  # noqa: N818 - a refusal, not an error of the hub
    """The test print is refused; ``code`` is the problem type the API answers with."""

    __test__ = False  # not a test class, whatever pytest thinks of the name

    def __init__(self, status: int, code: str, title: str, detail: str | None = None) -> None:
        super().__init__(code)
        self.status, self.code, self.title, self.detail = status, code, title, detail


def printer_url(public_url: object, printer_id: UUID) -> str:
    """The hub's page of the printer: ``{public_url}/printers/{id}``, one slash, no credentials.

    ``public_url`` is the pydantic URL of the setting. Only scheme, host, port and path are
    used; user info, query and fragment are dropped.
    """
    scheme = str(getattr(public_url, "scheme", "https"))
    host = str(getattr(public_url, "host", ""))
    port = getattr(public_url, "port", None)
    path = str(getattr(public_url, "path", "") or "").rstrip("/")
    netloc = f"[{host}]" if ":" in host else host
    if port is not None and port != _DEFAULT_PORTS.get(scheme):
        netloc = f"{netloc}:{port}"
    return f"{scheme}://{netloc}{path}/printers/{printer_id}"


def tape_test_label(
    printer: Printer, width_mm: int, now: datetime, version: str, printer_url: str
) -> RawLabelData:
    """The test label: the printer's name, the tape width, the time and a QR to the printer."""
    return RawLabelData(
        qr_payload=printer_url,
        primary_id=printer.name,
        title=f"{width_mm} mm · {now:%Y-%m-%d %H:%M}",
        secondary=(f"Printer Hub {version}",),
    )


def media_name(text: str | None) -> Literal["A4", "Letter"] | None:
    """The page size a media description stands for; ``None`` for anything else."""
    if not text:
        return None
    if _A4.search(text):
        return "A4"
    if _LETTER.search(text):
        return "Letter"
    return None


@dataclass(frozen=True)
class PageTestPlan:
    tray: str
    media: Literal["A4", "Letter"]
    margins_mm: HardwareMargins | None


async def resolve_tray(session: AsyncSession, printer_id: UUID, requested: str | None) -> str:
    """The tray to print from: the requested enabled one, else the enabled default."""
    rows = (
        (
            await session.execute(
                select(PrinterTray)
                .where(col(PrinterTray.printer_id) == printer_id)
                .order_by(col(PrinterTray.tray_key))
            )
        )
        .scalars()
        .all()
    )
    enabled = [t for t in rows if t.enabled]
    if requested is not None:
        if requested not in {t.tray_key for t in enabled}:
            raise TestPrintRefusal(
                422,
                "tray-invalid",
                "Unknown or disabled tray",
                f"Tray {requested!r} cannot be used",
            )
        return requested
    default = next((t for t in enabled if t.is_default), None) or (enabled[0] if enabled else None)
    if default is None:
        raise TestPrintRefusal(
            422, "tray-invalid", "The printer has no enabled tray", "Enable a tray first"
        )
    return default.tray_key


async def plan_page_test_print(
    session: AsyncSession,
    printer_id: UUID,
    tray: str,
    *,
    polled: bool,
    probe_interval_s: float,
    now: datetime | None = None,
) -> PageTestPlan:
    """Check the page printer's cached status and decide media and margins.

    Raises ``TestPrintRefusal``: ``printer-status-unknown`` (no producer, so nothing is
    known), ``printer-offline`` (no row, stale, not online) and ``media-unknown``.
    """
    if not polled:
        raise TestPrintRefusal(
            409,
            "printer-status-unknown",
            "The printer's status is unknown",
            "The hub does not poll this printer, so it cannot tell whether it is ready",
        )
    row = await session.get(PrinterStatusCache, printer_id)
    offline = TestPrintRefusal(409, "printer-offline", "The printer is offline")
    if row is None or row.captured_at is None:
        raise offline
    parsed = row.parsed or {}
    if is_stale(row.updated_at, now or datetime.now(UTC), probe_interval_s, backoff_of(parsed)):
        raise TestPrintRefusal(
            409, "printer-offline", "The printer's status is out of date", "No recent probe"
        )
    status = read_status(parsed)
    record = status.record
    if record is None or record.online is not True:
        raise offline
    loaded = {t.key: t.media for t in record.trays}
    media = media_name(loaded.get(tray)) or media_name(record.summary.media_default)
    if media is None:
        raise TestPrintRefusal(
            409,
            "media-unknown",
            "The paper size is unknown",
            "The printer reports neither the media in this tray nor a default media",
        )
    margins = facts_of(status).margins_hmm
    return PageTestPlan(
        tray=tray,
        media=media,
        margins_mm=None
        if margins is None
        else HardwareMargins(
            top=margins.top / 100,
            left=margins.left / 100,
            bottom=margins.bottom / 100,
            right=margins.right / 100,
        ),
    )
