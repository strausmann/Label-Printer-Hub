# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Helpers shared by the sheet type and the sheet routers (spec 15)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import AuthContext, check_printer_access
from app.auth.ownership import key_actor, looks_like_key
from app.models.printer import Printer
from app.repositories import printers as printers_repo
from app.sheets.errors import PrinterNotFoundError, SheetApiError, SheetPrinterDisabledError

SYSTEM_PREFIX = "system:"


@contextmanager
def mapped() -> Iterator[None]:
    """Turn a domain error into the API error shape."""
    try:
        yield
    except SheetApiError as exc:
        raise exc.to_http() from None


def actor(auth: AuthContext) -> str:
    """Who is recorded as the author of a write: the user, else the key, else the source."""
    if auth.user:
        # "system:" is reserved for the hub itself (the seeder) and "key:<uuid>" / a bare id
        # for a key (#294: a batch's owner key is read back from it); a person with such a
        # name must not be mistaken for either.
        reserved = auth.user.startswith(SYSTEM_PREFIX) or looks_like_key(auth.user)
        return f"user:{auth.user}" if reserved else auth.user
    return key_actor(auth.api_key_id) if auth.api_key_id else auth.source


async def usable_printer(session: AsyncSession, auth: AuthContext, printer_key: str) -> Printer:
    """The printer a request names: it exists, the caller may use it and it is switched on
    (pre-flight C18)."""
    printer = await printers_repo.resolve_by_slug_or_uuid(session, printer_key)
    if printer is None:
        raise PrinterNotFoundError().to_http()
    check_printer_access(auth, printer.id)
    if not printer.enabled:
        raise SheetPrinterDisabledError().to_http()
    return printer
