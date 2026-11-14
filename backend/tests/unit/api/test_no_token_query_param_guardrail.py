# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Guardrail: no route declares a FastAPI parameter that takes a URL ``token`` (#281).

The URL token (``require_print_token``) is read from the raw query string on purpose. A
declared ``token`` query parameter would put the key into the OpenAPI document and, on a
validation error, echo it in a 422 body that Grocy shows to its user.

What it walks: every route (included routers flattened) and every sub-dependency of it.
What it reports, comparing names case-insensitively with ``token``:

- a query parameter whose name or alias is ``token``;
- a field of a query parameter **model** (``q: Annotated[Model, Query()]``, also inside
  ``Model | None`` or a nested model) whose name or any alias is ``token``;
- an ``APIKeyQuery`` or ``APIKeyCookie`` security dependency with ``name="token"``.

What it cannot see: a route that reads ``request.query_params["token"]`` or the raw query
string by hand, a model field whose alias is produced by an ``alias_generator`` at runtime
in a way ``model_fields`` does not expose, and an ``APIKeyHeader`` named ``token`` (a
header is not part of the logged URL, so it is not reported). Review and the token-reader
tests cover those.
"""

from __future__ import annotations

import typing
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Query
from fastapi.security import APIKeyCookie, APIKeyHeader, APIKeyQuery
from pydantic import BaseModel, Field

from tests.helpers.routes import iter_api_routes

FORBIDDEN = "token"


def _is_forbidden(*names: object) -> bool:
    return any(isinstance(n, str) and n.lower() == FORBIDDEN for n in names)


def _models_in(annotation: Any, seen: set[type]) -> list[type[BaseModel]]:
    """Every BaseModel class in an annotation (``Model``, ``Model | None``, ``list[Model]``)."""
    found: list[type[BaseModel]] = []
    if (
        isinstance(annotation, type)
        and issubclass(annotation, BaseModel)
        and annotation not in seen
    ):
        seen.add(annotation)
        found.append(annotation)
    for arg in typing.get_args(annotation):
        found += _models_in(arg, seen)
    return found


def _model_token_fields(annotation: Any, path: str) -> list[str]:
    hits: list[str] = []
    seen: set[type] = set()
    pending = [(m, path) for m in _models_in(annotation, seen)]
    while pending:
        model, prefix = pending.pop()
        for fname, info in model.model_fields.items():
            aliases = [info.alias, info.serialization_alias]
            va = info.validation_alias
            aliases += [va] if isinstance(va, str) else list(getattr(va, "choices", []) or [])
            if _is_forbidden(fname, *aliases):
                hits.append(f"{prefix}.{fname} (model {model.__name__})")
            pending += [(m, f"{prefix}.{fname}") for m in _models_in(info.annotation, seen)]
    return hits


def _token_params(dependant: Any) -> list[str]:
    found = []
    for field in dependant.query_params:
        if _is_forbidden(field.name, field.alias):
            found.append(f"{field.name} (alias {field.alias})")
        found += _model_token_fields(field.field_info.annotation, field.name)
    call = dependant.call
    if isinstance(call, APIKeyQuery | APIKeyCookie) and _is_forbidden(call.model.name):
        found.append(f"{type(call).__name__}(name={call.model.name!r})")
    for sub in dependant.dependencies:
        found += _token_params(sub)
    return found


def _offending_routes(app: FastAPI) -> list[str]:
    # iter_api_routes flattens included routers; a plain walk of app.routes would see
    # almost no route and pass vacuously.
    offending = []
    for route in iter_api_routes(app.routes):
        params = _token_params(route.dependant)
        if params:
            offending.append(f"{sorted(route.methods)} {route.path}: {', '.join(params)}")
    return offending


# Probe models for the counter-test. Module level, because with postponed annotations
# FastAPI resolves a route's annotations against the module globals.
class Inner(BaseModel):
    TOKEN: str


class Filters(BaseModel):
    page: int = 1
    key: str = Field(default="", alias="Token")


class Outer(BaseModel):
    inner: Inner | None = None


class Clean(BaseModel):
    page: int = 1
    tokenizer: str = Field(default="", alias="xtoken")


def test_no_route_declares_a_token_query_parameter() -> None:
    from app.main import create_app

    app = create_app()._app  # the FastAPI instance behind the lifespan wrapper
    assert len(iter_api_routes(app.routes)) > 50, "route discovery is broken"
    offending = _offending_routes(app)
    assert not offending, (
        "Route(s) declare a 'token' query parameter; read the URL token with "
        "require_print_token (raw query string) instead:\n  " + "\n  ".join(offending)
    )


def test_guardrail_sees_a_declared_token_parameter() -> None:
    """Counter-test: throwaway routes with each way of declaring the name are caught,
    on a probe app and on the real app."""
    probe = FastAPI()

    @probe.get("/direct")
    async def direct(token: str = Query()) -> None:
        return None

    @probe.get("/alias")
    async def alias(key: str = Query(alias="Token")) -> None:
        return None

    def _dep(TOKEN: str = Query()) -> str:  # noqa: N803
        return TOKEN

    @probe.get("/nested")
    async def nested(value: str = Depends(_dep)) -> None:
        return None

    @probe.get("/model")
    async def model(q: Annotated[Filters, Query()]) -> None:
        return None

    @probe.get("/optional-model")
    async def optional_model(q: Annotated[Inner | None, Query()] = None) -> None:
        return None

    @probe.get("/nested-model")
    async def nested_model(q: Annotated[Outer, Query()]) -> None:
        return None

    @probe.get("/api-key-query")
    async def api_key_query(k: str = Depends(APIKeyQuery(name="Token"))) -> None:
        return None

    @probe.get("/api-key-cookie")
    async def api_key_cookie(k: str = Depends(APIKeyCookie(name="token"))) -> None:
        return None

    # Not reported on purpose (see the module docstring): a header and an unrelated name.
    @probe.get("/api-key-header")
    async def api_key_header(k: str = Depends(APIKeyHeader(name="token"))) -> None:
        return None

    @probe.get("/innocent")
    async def innocent(q: Annotated[Clean, Query()], tokenizer: str = "") -> None:
        return None

    offending = _offending_routes(probe)
    paths = sorted(o.split(" ", 2)[1].rstrip(":") for o in offending)
    assert paths == sorted(
        [
            "/direct",
            "/alias",
            "/nested",
            "/model",
            "/optional-model",
            "/nested-model",
            "/api-key-query",
            "/api-key-cookie",
        ]
    ), offending

    from app.main import create_app

    real = create_app()._app
    throwaway = {
        "/api/v1/t7-throwaway": direct,
        "/api/v1/t7-throwaway-model": model,
        "/api/v1/t7-throwaway-api-key-query": api_key_query,
    }
    for path, endpoint in throwaway.items():
        real.add_api_route(path, endpoint, methods=["GET"])
    found = {o.split(" ", 2)[1].rstrip(":") for o in _offending_routes(real)}
    assert set(throwaway) <= found, found
