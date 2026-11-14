# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Grocy's label printer webhook: ``POST /api/v1/webhook/grocy/label`` (#281, spec section 6).

Grocy calls one fixed URL from its ``config.php`` (``LABEL_PRINTER_WEBHOOK``) with a 2.0 s
timeout and sends no headers of its own, so the key travels as the URL ``token`` (D24, ADR
0027). On an error answer or a timeout Grocy shows that URL — token included — to its user.
The route therefore answers within ``GROCY_LABEL_BUDGET_S`` and turns everything that is the
label's fault into a ``failed`` job instead of an error status.

Order (R-281-8):

1. ``require_print_token``: the token (401 ``invalid_token``, 403 for a read or an admin key)
   and the key's rate limit (429) -> ``integrations.grocy.label.enabled`` (503
   ``grocy_label_disabled``) -> the media type (415 ``json_required``) -> the bounded read
   (413 ``body_too_large``).
2. The target printer of the code's label type (the product mapping when the code is
   unreadable; ``resolve_grocy_target``: the type's printer, else the default target, else the
   first enabled tape printer): an unknown slug answers 503
   ``grocy_label_printer_unavailable`` before the access check, so the answer says nothing
   about printers the key may not use; then
   ``check_printer_access`` (403 with the fixed message, mapped or not); then a disabled
   printer answers 503 ``grocy_label_printer_unavailable``, and an enabled page printer whose
   target names no sheet type, an unknown or an archived one 503
   ``grocy_label_sheet_type_unavailable`` (R-281-14).
3. A content error (unparseable JSON, a schema failure, a code outside ``GROCYCODE_PATTERN``,
   a text over 512 characters: ``grocy_label_invalid``; a name field that does not match the
   type: ``grocy_label_mismatch``) answers 202 with a ``failed`` job on the target printer.
4. Otherwise a deferred job is accepted and the route answers 202: on a tape printer
   ``PrintService.accept_deferred_job`` (preflight, render and the queue hand-off run after
   the answer, R-281-11), on a page printer ``GrocySheetLabels.accept`` (the sheet choice, the
   reservation and the hand-off run after the answer, R-281-16).

No answer names a printer, and none repeats the body or the token.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.bounded_body import read_bounded
from app.api.dependencies.token_auth import require_print_token
from app.api.routes.webhooks import _resolve_default_printer_id
from app.auth.dependencies import AuthContext, check_printer_access
from app.db.session import get_session
from app.models.printer import Printer
from app.repositories import printers as printers_repo
from app.repositories import sheet_types as types_repo
from app.schemas.content_type import ContentType
from app.schemas.grocy_label import (
    MAX_GROCY_LABEL_BODY,
    GrocyLabelMismatchError,
    GrocyLabelPayload,
    GrocyLabelType,
    grocy_label_type,
    is_grocycode,
)
from app.schemas.webhook import WebhookAcceptedResponse
from app.settings_store.registry import (
    GROCY_LABEL_DEFAULT_PRINTER_KEY,
    GROCY_LABEL_DEFAULT_SHEET_TYPE_KEY,
    grocy_label_content_type_key,
    grocy_label_printer_key,
    grocy_label_sheet_type_key,
)

router = APIRouter(prefix="/api/v1/webhook", tags=["webhooks"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
TokenAuth = Annotated[AuthContext, Depends(require_print_token)]

SOURCE_APP = "grocy"
ENABLED_KEY = "integrations.grocy.label.enabled"

_CONTENT_ERROR_MESSAGES = {
    "grocy_label_invalid": "Grocy sent a label request the hub cannot read.",
    "grocy_label_mismatch": "The name field does not match the label type of the Grocycode.",
}


def _error(http_status: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=http_status, detail={"error_code": code, "error_message": message}
    )


def _too_large() -> HTTPException:
    return _error(
        status.HTTP_413_CONTENT_TOO_LARGE,
        "body_too_large",
        "The request body is larger than 1 MiB.",
    )


def _unavailable() -> HTTPException:
    # Never names the printer: Grocy forwards the message to its user.
    return _error(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "grocy_label_printer_unavailable",
        "The printer for this Grocy label is not available.",
    )


def _is_json(content_type: str) -> bool:
    """``application/json``, with or without parameters; nothing that only looks like it."""
    return content_type.split(";", 1)[0].strip().lower() == "application/json"


def _decode(raw: bytes) -> object:
    """The JSON value of the body, or ``None`` when it is not JSON."""
    try:
        return json.loads(raw)
    except (ValueError, RecursionError):  # JSONDecodeError and UnicodeDecodeError are ValueErrors
        return None


def _target_type(document: object) -> GrocyLabelType:
    """The label type that picks the printer: the code's, else the product's (R-281-8, 2)."""
    code = document.get("grocycode") if isinstance(document, dict) else None
    if isinstance(code, str) and is_grocycode(code):
        return grocy_label_type(code)
    return "product"


def resolve_grocy_target(settings: Any, label_type: GrocyLabelType) -> str | None:
    """The printer slug a label of ``label_type`` goes to; ``None`` is the first tape printer.

    The type's own printer when set, else the default target, else ``None`` (maintainer
    ruling on #281, 2026-11-14). ``settings`` is the runtime settings store.
    """
    for key in (grocy_label_printer_key(label_type), GROCY_LABEL_DEFAULT_PRINTER_KEY):
        slug = str(settings.get(key) or "").strip()
        if slug:
            return slug
    return None


def resolve_grocy_sheet_type(settings: Any, label_type: GrocyLabelType) -> str | None:
    """The sheet type key of the target a label of ``label_type`` goes to; ``None``: unset.

    A target is a unit (R-281-13): a type with its own printer uses its own sheet type, a type
    without one uses the default target's printer **and** sheet type. The two keys are never
    mixed. Only meaningful when that target's printer is a page printer.
    """
    own = str(settings.get(grocy_label_printer_key(label_type)) or "").strip()
    key = grocy_label_sheet_type_key(label_type) if own else GROCY_LABEL_DEFAULT_SHEET_TYPE_KEY
    return str(settings.get(key) or "").strip() or None


@dataclass(frozen=True)
class TapeTarget:
    """A tape printer: its ``PrintService`` prints the label (R-281-11)."""

    service: Any


@dataclass(frozen=True)
class PageTarget:
    """A page printer and the sheet type its labels go onto (R-281-13)."""

    printer: Printer
    sheet_type: str


def _sheet_type_unavailable() -> HTTPException:
    # No key in the message: Grocy forwards it to its user.
    return _error(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "grocy_label_sheet_type_unavailable",
        "The sheet type for Grocy labels is not set, unknown or archived in Labelyard.",
    )


async def _target_printer(
    request: Request, session: AsyncSession, auth: AuthContext, label_type: GrocyLabelType
) -> TapeTarget | PageTarget:
    """The label type's target, after the access check (R-281-8, 2; R-281-14)."""
    store = request.app.state.settings_store
    slug = resolve_grocy_target(store, label_type)
    printer: Printer | None = None
    if slug is not None:
        printer = await printers_repo.get_by_slug(session, slug)
        if printer is None:
            raise _unavailable()  # before the access check: reveals nothing about printers
        printer_id: UUID = printer.id
    else:
        printer_id = UUID(await _resolve_default_printer_id(session))
    check_printer_access(auth, printer_id, default_printer=True)
    if printer is not None and not printer.enabled:
        raise _unavailable()
    if printer is not None and printer.backend == "ipp":
        # Checked at request time: the settings store knows no other entities (R-281-14).
        sheet_type = resolve_grocy_sheet_type(store, label_type)
        known = None if sheet_type is None else await types_repo.get_by_key(session, sheet_type)
        if sheet_type is None or known is None or known.archived_at is not None:
            raise _sheet_type_unavailable()
        return PageTarget(printer=printer, sheet_type=sheet_type)
    service = request.app.state.printer_runtime.print_service_for(printer_id)
    if service is None:
        raise _unavailable()
    return TapeTarget(service=service)


def _grocycode_ref(code: str) -> str:
    """The Grocycode cut to entity and id (``grcy:p:12``): the cell's ``ref`` (R-281-15)."""
    return ":".join(code.split(":")[:3])


_OPENAPI_EXTRA: dict[str, Any] = {
    "parameters": [
        {
            "name": "token",
            "in": "query",
            "required": False,
            "description": (
                "A Labelyard API key with the print scope (D24, ADR 0027). Read from a literal "
                "'token=' parameter only; the X-Label-Hub-Key header wins when both are sent. "
                "The hub hides the value in its own logs"
            ),
            "schema": {"type": "string", "maxLength": 128},
        },
        {
            "name": "X-Label-Hub-Key",
            "in": "header",
            "required": False,
            "description": "The same key as a header, for callers that can send headers",
            "schema": {"type": "string", "maxLength": 128},
        },
    ],
    "requestBody": {
        "required": True,
        "description": (
            "The JSON object Grocy sends with LABEL_PRINTER_HOOK_JSON=true, at most 1 MiB. "
            "Fields not listed are ignored"
        ),
        "content": {"application/json": {"schema": GrocyLabelPayload.model_json_schema()}},
    },
}

_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "``invalid_token``: the token is missing, unknown, disabled or expired."},
    403: {
        "description": (
            "``insufficient_scope`` (a read key), ``token_scope_too_wide`` (an admin key) or "
            "``printer_not_allowed`` (the key may not use the label's printer; the message "
            "does not name it)."
        )
    },
    413: {"description": "``body_too_large``: the body is larger than 1 MiB."},
    415: {"description": "``json_required``: set LABEL_PRINTER_HOOK_JSON=true in Grocy."},
    429: {"description": "``rate_limit_exceeded``: the key's per-minute limit, with Retry-After."},
    503: {
        "description": (
            "``grocy_label_disabled`` (the webhook is switched off), "
            "``grocy_label_printer_unavailable`` (the mapped printer is unknown or disabled), "
            "``grocy_label_sheet_type_unavailable`` (a page printer whose sheet type is not "
            "set, unknown or archived) or no enabled tape printer."
        )
    },
}


@router.post(
    "/grocy/label",
    response_model=WebhookAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Accept a label request of Grocy's label printer webhook",
    description=(
        "Grocy's label printer webhook (``LABEL_PRINTER_WEBHOOK``) for products, stock "
        "entries, chores, batteries and recipes.  **Authentication:** an API key with the "
        "``print`` scope as the ``token`` query parameter (Grocy sends no headers) or the "
        "``X-Label-Hub-Key`` header; a read key answers 403 ``insufficient_scope``, an admin "
        "key 403 ``token_scope_too_wide``, every other failure of the token 401 "
        "``invalid_token``.  The key's printer restriction and rate limit apply.  "
        "The webhook is off until ``integrations.grocy.label.enabled`` is set.  The label "
        "type comes from the Grocycode; content type and printer come from the mapping of "
        "that type in Settings > Integrations > Grocy (a type without a printer uses the "
        "default target, and without one the first enabled tape printer).  A page printer "
        "prints the label onto one cell of its sheet type: the lowest free cell of the "
        "started sheet with the fewest free cells, else a new sheet with its ID in the "
        "margin.  The route "
        "answers 202 within 1.5 s with the job's UUID: printing runs afterwards, and a "
        "printer failure (offline, no tape) sets the job ``failed`` with the code "
        "``POST /api/v1/print`` would answer; on a page printer a sheet failure sets the code "
        "of the sheet print (for example ``content_type_data_mismatch``).  A "
        "label that cannot be built (unreadable body, invalid Grocycode, name field of "
        "another type) also answers 202, with a ``failed`` job (``grocy_label_invalid``, "
        "``grocy_label_mismatch``)."
    ),
    openapi_extra=_OPENAPI_EXTRA,
    responses=_RESPONSES,
)
async def grocy_label_webhook(
    request: Request, session: SessionDep, auth: TokenAuth
) -> WebhookAcceptedResponse:
    """Accept one Grocy label for deferred printing (R-281-8, R-281-11)."""
    store = request.app.state.settings_store
    if not store.get(ENABLED_KEY):
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "grocy_label_disabled",
            "The Grocy label printer webhook is switched off in Labelyard.",
        )
    if not _is_json(request.headers.get("content-type", "")):
        raise _error(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "json_required",
            "Send the label as JSON: set LABEL_PRINTER_HOOK_JSON to true in Grocy's config.php.",
        )
    raw = await read_bounded(request, MAX_GROCY_LABEL_BODY, _too_large)
    document = _decode(raw)
    label_type = _target_type(document)
    target = await _target_printer(request, session, auth, label_type)
    source_ip = request.client.host if request.client else None
    await session.commit()  # no read transaction stays open behind the job insert

    error_code: str | None = None
    try:
        payload = GrocyLabelPayload.model_validate(document)
        label = payload.to_raw_label()
    except GrocyLabelMismatchError:
        error_code = "grocy_label_mismatch"
    except ValidationError:
        error_code = "grocy_label_invalid"
    if error_code is not None:
        if isinstance(target, PageTarget):
            job_id = await request.app.state.grocy_sheet_labels.record_failed(
                target.printer.id,
                error_code,
                message=_CONTENT_ERROR_MESSAGES[error_code],
                api_key_id=auth.api_key_id,
                source_ip=source_ip,
            )
        else:
            job_id = await target.service.record_failed_job(
                error_code,
                api_key_id=auth.api_key_id,
                source_ip=source_ip,
                source_app=SOURCE_APP,
                message=_CONTENT_ERROR_MESSAGES[error_code],
            )
        return WebhookAcceptedResponse(job_id=job_id)

    content_type = ContentType(store.get(grocy_label_content_type_key(label_type)))
    if isinstance(target, PageTarget):
        job_id = await request.app.state.grocy_sheet_labels.accept(
            target.printer,
            sheet_type=target.sheet_type,
            raw=label,
            content_type=content_type,
            ref=_grocycode_ref(payload.grocycode),
            api_key_id=auth.api_key_id,
            source_ip=source_ip,
        )
        return WebhookAcceptedResponse(job_id=job_id)
    job_id = await target.service.accept_deferred_job(
        label,
        content_type=content_type,
        source_app=SOURCE_APP,
        api_key_id=auth.api_key_id,
        source_ip=source_ip,
    )
    return WebhookAcceptedResponse(job_id=job_id)
