"""Guardrail: no route declares a FastAPI query parameter named ``token`` (#281).

The URL token (``require_print_token``) is read from the raw query string on purpose. A
declared ``token`` query parameter would put the key into the OpenAPI document and, on a
validation error, echo it in a 422 body that Grocy shows to its user. This walks every
route's dependency tree (``query_params`` of the route and of every sub-dependency) and
fails on a parameter whose name or alias is ``token`` in any case.

Limit: it sees FastAPI-declared parameters only. A route that reads
``request.query_params["token"]`` by hand is invisible to it; that is what review and the
token-reader tests are for.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Query

from tests.helpers.routes import iter_api_routes

FORBIDDEN = "token"


def _token_params(dependant: Any) -> list[str]:
    found = [
        f"{field.name} (alias {field.alias})"
        for field in dependant.query_params
        if FORBIDDEN in {str(field.name).lower(), str(field.alias).lower()}
    ]
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

    assert len(_offending_routes(probe)) == 3, _offending_routes(probe)

    from app.main import create_app

    real = create_app()._app
    real.add_api_route("/api/v1/t7-throwaway", direct, methods=["GET"])
    assert [o for o in _offending_routes(real) if "t7-throwaway" in o]
