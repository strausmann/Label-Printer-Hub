# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""QR landing paths: the web app renders the item view (D1).

Routes (no /api/ prefix - these are the URLs printed as QR payloads)
-------------------------------------------------------------------
GET /loc/{entity_id}     - Snipe-IT location (the item view asks for it as ``loc:<id>``)
GET /asset/{entity_id}   - Snipe-IT asset
GET /spool/{entity_id}   - Spoolman filament spool
GET /product/{entity_id} - Grocy product

The server no longer renders HTML. Each path answers with the web app shell
and the app reads the item through ``GET /api/v1/lookup/{app}/{entity_id}``. The
paths are public by design: they are printed on physical labels and the shell
carries no data. The lookup endpoint behind them requires sign-in (read scope), as does every
client route of the web app. When no web app is mounted (API-only mode) they return a
JSON 404.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.web.spa import serve_index

router = APIRouter(tags=["qr-landing"])


def _app_shell(request: Request) -> Response:
    response = serve_index(request)
    if response is None:
        raise HTTPException(status_code=404, detail="web app not available")
    return response


@router.get("/loc/{entity_id}", include_in_schema=False)
async def loc_landing(request: Request, entity_id: str) -> Response:  # noqa: ARG001
    return _app_shell(request)


@router.get("/asset/{entity_id}", include_in_schema=False)
async def asset_landing(request: Request, entity_id: str) -> Response:  # noqa: ARG001
    return _app_shell(request)


@router.get("/spool/{entity_id}", include_in_schema=False)
async def spool_landing(request: Request, entity_id: str) -> Response:  # noqa: ARG001
    return _app_shell(request)


@router.get("/product/{entity_id}", include_in_schema=False)
async def product_landing(request: Request, entity_id: str) -> Response:  # noqa: ARG001
    return _app_shell(request)
