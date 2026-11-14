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
   ``check_printer_access`` (403 with the fixed message, mapped or not); then a disabled or
   page printer answers 503 ``grocy_label_printer_unavailable``.
3. A content error (unparseable JSON, a schema failure, a code outside ``GROCYCODE_PATTERN``,
   a text over 512 characters: ``grocy_label_invalid``; a name field that does not match the
   type: ``grocy_label_mismatch``) answers 202 with a ``failed`` job on the target printer.
4. Otherwise a deferred job is accepted (``PrintService.accept_deferred_job``) and the route
   answers 202; preflight, render and the queue hand-off run after the answer (R-281-11).

No answer names a printer, and none repeats the body or the token.
"""

from __future__ import annotations

import json
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
from app.repositories import printers as printers_repo
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
    grocy_label_content_type_key,
    grocy_label_printer_key,
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


async def _target_printer(
    request: Request, session: AsyncSession, auth: AuthContext, label_type: GrocyLabelType
) -> Any:
    """The ``PrintService`` of the label type's printer, after the access check."""
    slug = resolve_grocy_target(request.app.state.settings_store, label_type)
    if slug is not None:
        printer = await printers_repo.get_by_slug(session, slug)
        if printer is None:
            raise _unavailable()  # before the access check: reveals nothing about printers
        printer_id: UUID = printer.id
        usable = printer.enabled and printer.backend != "ipp"
    else:
        printer_id = UUID(await _resolve_default_printer_id(session))
        usable = True
    check_printer_access(auth, printer_id, default_printer=True)
    service = request.app.state.printer_runtime.print_service_for(printer_id) if usable else None
    if service is None:
        raise _unavailable()
    return service


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
            "``grocy_label_printer_unavailable`` (the mapped printer is unknown, disabled or "
            "not a tape printer) or no enabled tape printer."
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
        "default target, and without one the first enabled tape printer).  The route "
        "answers 202 within 1.5 s with the job's UUID: printing runs afterwards, and a "
        "printer failure (offline, no tape) sets the job ``failed`` with the code "
        "``POST /api/v1/print`` would answer.  A "
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
    service = await _target_printer(request, session, auth, label_type)
    source_ip = request.client.host if request.client else None

    error_code: str | None = None
    try:
        payload = GrocyLabelPayload.model_validate(document)
        label = payload.to_raw_label()
    except GrocyLabelMismatchError:
        error_code = "grocy_label_mismatch"
    except ValidationError:
        error_code = "grocy_label_invalid"
    if error_code is not None:
        job_id = await service.record_failed_job(
            error_code,
            api_key_id=auth.api_key_id,
            source_ip=source_ip,
            source_app=SOURCE_APP,
            message=_CONTENT_ERROR_MESSAGES[error_code],
        )
        return WebhookAcceptedResponse(job_id=job_id)

    content_type = ContentType(store.get(grocy_label_content_type_key(label_type)))
    job_id = await service.accept_deferred_job(
        label,
        content_type=content_type,
        source_app=SOURCE_APP,
        api_key_id=auth.api_key_id,
        source_ip=source_ip,
    )
    return WebhookAcceptedResponse(job_id=job_id)
