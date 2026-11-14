# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Cart pre-check (#285): would these items print on this tape and layout?

Each distinct item (app, identifier, content type) is looked up and drawn once; a failure
belongs to the item and never fails the request. Error messages are fixed: the exception text
of a lookup can carry the integration's address or its upstream's answer (CWE-209).
"""

from __future__ import annotations

import asyncio
import weakref
from collections.abc import Awaitable
from typing import Protocol

from app.printer_backends.exceptions import (
    ContentTypeDataMismatchError,
    QrPayloadTooLongError,
    UnsupportedTapeError,
)
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.schemas.render_check import (
    RenderCheckItem,
    RenderCheckRequest,
    RenderCheckResponse,
    RenderCheckResult,
)
from app.schemas.tape_geometry import TAPE_GEOMETRY
from app.services.errors import AppLookupNotFoundError, IntegrationNotConfiguredError
from app.services.layout_engine import LayoutEngine
from app.services.lookup_service import LookupFailedError, UnknownAppError
from app.services.print_service import MAX_BATCH_LOOKUPS
from app.services.ql_layout import resolve_layout

_Key = tuple[str, str, ContentType]
# (code, message, detail) of a failed item; None for an item that fits.
_Verdict = tuple[str, str, dict[str, object] | None] | None


class _Lookups(Protocol):
    def lookup(self, source_app: str, identifier: str) -> Awaitable[LabelData]: ...


def _key(item: RenderCheckItem) -> _Key:
    return (item.lookup.app, item.lookup.identifier, item.content_type)


_gates: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)


def _lookup_gate() -> asyncio.Semaphore:
    """The one lookup bound of this process: all checks together run ``MAX_BATCH_LOOKUPS`` at most.

    A semaphore belongs to one event loop, so there is one per running loop (one in production).
    """
    loop = asyncio.get_running_loop()
    gate = _gates.get(loop)
    if gate is None:
        gate = _gates[loop] = asyncio.Semaphore(MAX_BATCH_LOOKUPS)
    return gate


def distinct_lookup_count(request: RenderCheckRequest) -> int:
    """How many integration lookups the request costs: one per distinct item."""
    return len({_key(item) for item in request.items})


def validate_layout(request: RenderCheckRequest) -> None:
    """Raise ``UnsupportedTapeError`` when the tape width or orientation is not available."""
    if request.tape_mm not in TAPE_GEOMETRY:
        raise UnsupportedTapeError(tape_mm=request.tape_mm)
    resolve_layout(request.tape_mm, request.orientation, request.layout_preset, None)


async def check_items(request: RenderCheckRequest, lookups: _Lookups) -> RenderCheckResponse:
    """One verdict per request item, in request order.

    Raises:
        UnsupportedTapeError: the tape width or the orientation is not available. Checked
            before the first lookup, so a request that cannot succeed costs the integrations
            nothing.
    """
    validate_layout(request)

    engine = LayoutEngine()
    gate = _lookup_gate()

    async def _verdict(key: _Key) -> _Verdict:
        app, identifier, content_type = key
        try:
            async with gate:
                data = await lookups.lookup(app, identifier)
        except UnknownAppError:  # before LookupFailedError: it is the subclass
            return ("integration_unknown_app", "The requested integration is not available.", None)
        except LookupFailedError:
            return (
                "integration_lookup_failed",
                "The integration failed or could not be reached.",
                None,
            )
        except AppLookupNotFoundError:
            return (
                "integration_item_not_found",
                "The integration has no item with this identifier.",
                None,
            )
        except IntegrationNotConfiguredError:
            return (
                "integration_not_configured",
                "The requested integration is not configured.",
                None,
            )
        try:
            await asyncio.to_thread(
                engine.render,
                request.tape_mm,
                content_type,
                data,
                orientation=request.orientation,
                preset=request.layout_preset,
            )
        except ContentTypeDataMismatchError as exc:
            return (
                "content_type_data_mismatch",
                "The label data is missing fields required for the selected content type.",
                {"missing_fields": list(exc.missing_fields)},
            )
        except QrPayloadTooLongError as exc:
            return (
                "qr_payload_too_long",
                "The QR payload does not fit the fixed QR code of this tape.",
                {"length": exc.length, "max_bytes": exc.max_bytes},
            )
        return None

    distinct = list(dict.fromkeys(_key(item) for item in request.items))
    verdicts = dict(
        zip(distinct, await asyncio.gather(*[_verdict(k) for k in distinct]), strict=True)
    )

    results: list[RenderCheckResult] = []
    for index, item in enumerate(request.items):
        verdict = verdicts[_key(item)]
        if verdict is None:
            results.append(RenderCheckResult(index=index, ok=True))
        else:
            code, message, detail = verdict
            results.append(
                RenderCheckResult(
                    index=index,
                    ok=False,
                    error_code=code,
                    error_message=message,
                    error_detail=detail,
                )
            )
    return RenderCheckResponse(results=results)
