# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Aggregator that routes lookup requests to the right integration plugin.

The service uses IntegrationRegistry as its source of truth. New apps
register themselves via entry_points (group 'label_hub.integrations') and
become available without touching this module.

Exception hierarchy
-------------------
- LookupFailedError  — umbrella; the REST layer catches this for HTTP 502
  - UnknownAppError  — config mismatch ("you asked for an unknown app")
- AppLookupNotFoundError (from any plugin) — entity-not-found; propagates
  unchanged so callers can handle it separately (e.g., HTTP 404).
  It is NOT a subclass of LookupFailedError — operationally distinct.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from typing import Final

# Trigger plugin discovery — importing this module guarantees the
# registry is populated regardless of whether main.py has imported
# app.integrations yet. The discovery is idempotent (registry
# rejects duplicates), so multiple imports are safe.
import app.integrations  # noqa: F401
from app.integrations.grocy.plugin import GrocyObjectReader
from app.integrations.registry import (
    IntegrationNotFoundError,
    IntegrationRegistry,
)
from app.schemas.grocy_object import GrocyBatteryResult, GrocyChoreResult
from app.schemas.label_data import LabelData
from app.schemas.print_request import (
    QR_PAYLOAD_MAX,
    RAW_LISTING_MAX,
    RAW_SECONDARY_MAX,
    RAW_TEXT_MAX,
)
from app.services.errors import (
    AppLookupNotFoundError,
    IntegrationNotConfiguredError,
    LookupFailedError,
)

__all__ = [
    "LOOKUP_DEADLINE_S",
    "AppLookupService",
    "LookupFailedError",
    "UnknownAppError",
    "cap_label_text",
    "refuse_oversized_qr",
]

#: Upper bound for one whole lookup, covering every upstream call the plugin makes
#: (a product lookup may fall back to a barcode request, an asset tag to an id request).
#: The per-request ``timeout`` setting only bounds a single call.
LOOKUP_DEADLINE_S: Final = 15.0

_log = logging.getLogger(__name__)


def _shortened(text: str) -> str:
    """``text`` cut to :data:`RAW_TEXT_MAX` characters, the last one an ellipsis."""
    if len(text) <= RAW_TEXT_MAX:
        return text
    return text[: RAW_TEXT_MAX - 1] + "\N{HORIZONTAL ELLIPSIS}"


def refuse_oversized_qr(label: LabelData) -> None:
    """Refuse a label whose QR payload, or a listing row's, is above :data:`QR_PAYLOAD_MAX`.

    Raises:
        LookupFailedError: an upstream answer made the payload too long to encode. The message
            names no upstream text.
    """
    rows = label.items[:RAW_LISTING_MAX]
    if len(label.qr_payload or "") > QR_PAYLOAD_MAX or any(
        len(row.qr_payload or "") > QR_PAYLOAD_MAX for row in rows
    ):
        raise LookupFailedError("the integration answered with a QR payload that is too long")


def cap_label_text(label: LabelData) -> LabelData:
    """A lookup's answer held to the text caps of a raw label (``RawLabelData``).

    The integration is not trusted to stay small: a hostile or broken one can answer a name of
    close to a megabyte, and every renderer, job row and preview would carry it whole. Text is
    cut with an ellipsis, the secondary lines and listing rows keep their first
    ``RAW_SECONDARY_MAX`` and ``RAW_LISTING_MAX`` entries. The QR payload is not cut here (a cut
    payload is another code); :func:`refuse_oversized_qr` refuses the lookup instead. Plugins
    build the payload from the base URL and an id that Grocy and Snipe-IT take from the
    upstream's answer, so its length is not under our control.
    """
    return label.model_copy(
        update={
            "title": None if label.title is None else _shortened(label.title),
            "primary_id": None if label.primary_id is None else _shortened(label.primary_id),
            "secondary": tuple(_shortened(line) for line in label.secondary[:RAW_SECONDARY_MAX]),
            "items": tuple(
                row.model_copy(update={"item": _shortened(row.item)})
                for row in label.items[:RAW_LISTING_MAX]
            ),
        }
    )


class UnknownAppError(LookupFailedError):
    """Raised when `source_app` does not match any registered plugin."""


class AppLookupService:
    """Route `lookup(source_app, id)` through IntegrationRegistry."""

    async def lookup(self, source_app: str, identifier: str) -> LabelData:
        """Dispatch to the registered plugin for `source_app`.

        Raises:
            UnknownAppError: if no plugin is registered for `source_app`.
            AppLookupNotFoundError: if the plugin signals entity-not-found
                (propagates unchanged so callers can handle it separately).
            LookupFailedError: wraps any unexpected runtime exception from
                the plugin so the REST layer has one type to catch for 502.
        """
        try:
            plugin = IntegrationRegistry.get(source_app)
        except IntegrationNotFoundError as e:
            raise UnknownAppError(str(e)) from e
        label = await self._run(plugin.lookup(identifier), f"{source_app} lookup")
        refuse_oversized_qr(label)
        return cap_label_text(label)

    async def grocy_battery(self, battery_id: str) -> GrocyBatteryResult:
        """Read-only details of one Grocy battery; errors map exactly like :meth:`lookup`."""
        plugin = self._grocy()
        return await self._run(plugin.battery(battery_id), "grocy battery lookup")

    async def grocy_chore(self, chore_id: str) -> GrocyChoreResult:
        """Read-only details of one Grocy chore; errors map exactly like :meth:`lookup`."""
        plugin = self._grocy()
        return await self._run(plugin.chore(chore_id), "grocy chore lookup")

    @staticmethod
    async def _run[T](call: Awaitable[T], what: str) -> T:
        """Await ``call`` under :data:`LOOKUP_DEADLINE_S`; plugin errors map to LookupFailedError.

        The deadline covers all upstream calls the plugin makes, so follow-up requests cannot
        stack their timeouts. The log carries the exception class name only: a message can hold
        the upstream address or its answer.
        """
        try:
            async with asyncio.timeout(LOOKUP_DEADLINE_S) as deadline:
                return await call
        except (LookupFailedError, AppLookupNotFoundError, IntegrationNotConfiguredError):
            raise
        except Exception as e:
            if deadline.expired():
                _log.warning("%s exceeded its deadline", what)
                raise LookupFailedError(f"{what} exceeded its deadline") from None
            raise LookupFailedError(f"{what} failed: {e}") from e

    @staticmethod
    def _grocy() -> GrocyObjectReader:
        try:
            plugin = IntegrationRegistry.get("grocy")
        except IntegrationNotFoundError as e:
            raise UnknownAppError(str(e)) from e
        if not isinstance(plugin, GrocyObjectReader):
            raise UnknownAppError(
                "the registered grocy integration cannot read batteries or chores"
            )
        return plugin

    @property
    def available_apps(self) -> list[str]:
        """Names of currently registered plugins, sorted alphabetically."""
        return IntegrationRegistry.names()
