"""OpenAPI completeness gate for Phase 6a REST API surface.

Walks ``app.openapi()`` and asserts the API surface is complete and
consistent.  This is a regression guard -- future routes that skip
tags, response_model, or the webhook auth dependency will fail here
before merging.

Assertions
----------
1. Every non-deprecated route has at least one OpenAPI tag.
2. Every JSON response (non-204, non-HTML) has a schema reference or
   inline type in the OpenAPI document.
3. Total operation count is in the expected 22-30 range.
4. Webhook routes expose ``X-API-Key`` as a header parameter (proves
   the ``require_webhook_key`` dependency is wired into the schema, not
   just enforced at runtime).
5. All path segments are lowercase kebab/snake (no upper-case, no
   special chars outside ``[a-z0-9_-]``).
6. ``ProblemDetail`` is registered as a named component schema.

References:
    docs/superpowers/plans/2026-05-16-phase6a-rest-api.md -- Task 7
    Refs #18
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from app.main import app as _app_wrapper

# Unwrap the _LifespanManager to get the underlying FastAPI instance.
# _LifespanManager wraps the FastAPI app so tests can import `app` and get
# the lifespan behaviour — but openapi() lives on the inner FastAPI object.
_inner_app = _app_wrapper._app  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def openapi_schema() -> dict[str, Any]:
    """Return the built OpenAPI schema (cached for the module)."""
    return _inner_app.openapi()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iter_operations(schema: dict[str, Any]):
    """Yield ``(path, method, operation_dict)`` for every non-deprecated op."""
    for path, methods in schema["paths"].items():
        for method, op in methods.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            if op.get("deprecated"):
                continue
            yield path, method.lower(), op


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_every_route_has_tags(openapi_schema: dict[str, Any]) -> None:
    """Every non-deprecated route must declare at least one OpenAPI tag.

    Tags are required so that:
    - The Swagger UI groups endpoints logically.
    - The Go frontend oapi-codegen generates correctly-namespaced client code.
    - Future tooling (linting, contract tests) can filter by tag.
    """
    missing = [
        f"{method.upper()} {path}"
        for path, method, op in _iter_operations(openapi_schema)
        if not op.get("tags")
    ]
    assert missing == [], (
        "Routes missing OpenAPI tags (add `tags=[...]` to the decorator):\n"
        + "\n".join(f"  {r}" for r in missing)
    )


def test_json_responses_have_schemas(openapi_schema: dict[str, Any]) -> None:
    """Every JSON response body must reference a schema component or have an inline type.

    Responses that lack a schema cause oapi-codegen to emit ``interface{}``
    instead of typed structs, and break OpenAPI validators.

    Exempt:
    - 204 No Content (no body by definition).
    - ``text/html`` responses (QR landing pages return HTML, not JSON).
    """
    violations: list[str] = []
    for path, method, op in _iter_operations(openapi_schema):
        for status_code, response in (op.get("responses") or {}).items():
            # 204 has no body — exempt.
            if str(status_code) == "204":
                continue
            content = (response or {}).get("content") or {}
            json_payload = content.get("application/json")
            if not json_payload:
                # Not a JSON response (e.g. text/html from QR routes) — exempt.
                continue
            schema = json_payload.get("schema") or {}
            if not schema:
                violations.append(
                    f"{method.upper()} {path} [{status_code}]: missing schema entirely"
                )
                continue
            # Accept any of:
            # - a $ref to a named component (e.g. {"$ref": "#/components/schemas/Foo"})
            # - an array whose items have a $ref
            # - a oneOf/anyOf list whose options have $refs
            # - an inline object/scalar with an explicit "type" key
            has_ref = "$ref" in schema
            has_items_ref = schema.get("type") == "array" and "$ref" in (schema.get("items") or {})
            has_one_of_refs = any(
                "$ref" in opt for opt in (schema.get("oneOf") or schema.get("anyOf") or [])
            )
            has_inline_type = "type" in schema
            if not (has_ref or has_items_ref or has_one_of_refs or has_inline_type):
                violations.append(
                    f"{method.upper()} {path} [{status_code}]: "
                    f"JSON response schema has no $ref or type — got {schema!r}"
                )
    assert violations == [], "JSON responses without schema references:\n" + "\n".join(
        f"  {v}" for v in violations
    )


def test_endpoint_count_in_range(openapi_schema: dict[str, Any]) -> None:
    """Operation count must be between 22 and 30.

    Expected breakdown:
      printers (7) + templates (1) + jobs (6) + lookup (1) + webhooks (2)
      + qr-landing (4) = 21 new Phase-6a endpoints
      + existing /print (1) + /jobs/{id} (1) + /printer/resume (1)
        + /jobs/{id}/resume (1) = 4 legacy print.py endpoints
      + /healthz (1) = 1 meta endpoint
      Total = 26

    The range 22-30 is intentionally wide to tolerate minor additions
    (e.g. a future ``/healthz/db`` probe) without requiring this test to be
    updated.  It will still catch the case where an entire router is
    accidentally unregistered (count drops below 22) or a rogue batch of
    undocumented endpoints lands (count exceeds 30).
    """
    count = sum(1 for _ in _iter_operations(openapi_schema))
    assert 22 <= count <= 30, (
        f"Operation count {count} is outside the expected 22-30 range.  "
        "If you intentionally added or removed endpoints, update this test."
    )


def test_webhooks_require_api_key(openapi_schema: dict[str, Any]) -> None:
    """Webhook POST routes must declare ``X-API-Key`` as a required header parameter.

    This test proves that ``require_webhook_key`` (which reads
    ``x_api_key: str = Header(..., alias='X-API-Key')``) is wired into the
    route definitions and not just a runtime guard invisible to the schema.

    If this test fails, FastAPI likely sees the dependency via
    ``dependencies=[Depends(...)]`` at the route level but the function
    parameter is not being introspected — refactor the route to use
    ``_: None = Depends(require_webhook_key)`` as a positional parameter
    so FastAPI can surface the header in the schema.
    """
    webhook_paths = ("/api/webhook/spoolman", "/api/webhook/grocy")
    for path in webhook_paths:
        assert path in openapi_schema["paths"], (
            f"{path} not found in OpenAPI schema — is the webhooks router mounted?"
        )
        post_op = openapi_schema["paths"][path].get("post") or {}
        params = post_op.get("parameters") or []
        header_names = {p["name"].lower() for p in params if p.get("in") == "header"}
        assert "x-api-key" in header_names, (
            f"{path} POST is missing the ``X-API-Key`` header parameter in the "
            "OpenAPI schema.  The ``require_webhook_key`` dependency must use "
            "``Header(..., alias='X-API-Key')`` as a function parameter so that "
            "FastAPI surfaces it in the schema."
        )


def test_path_segments_are_lowercase(openapi_schema: dict[str, Any]) -> None:
    """All path segments must be lowercase kebab/snake identifiers.

    Path parameters (``{printer_id}``) are exempt.  Uppercase letters or
    non-standard characters in static segments indicate a naming convention
    violation.

    Allowed pattern: ``[a-z][a-z0-9_-]*`` — starts with a letter, followed
    by lowercase letters, digits, underscores, or hyphens.
    """
    segment_re = re.compile(r"^[a-z][a-z0-9_-]*$")
    violations: list[str] = []
    for path in openapi_schema["paths"]:
        for segment in path.split("/"):
            if not segment:
                continue
            # Path parameters like {printer_id} are exempt.
            if segment.startswith("{") and segment.endswith("}"):
                continue
            if not segment_re.match(segment):
                violations.append(f"{path!r} — bad segment: {segment!r}")
                break
    assert violations == [], "Paths with non-lowercase-kebab segments:\n" + "\n".join(
        f"  {v}" for v in violations
    )


def test_problem_detail_schema_in_components(openapi_schema: dict[str, Any]) -> None:
    """``ProblemDetail`` must be a named component schema.

    ProblemDetail (RFC 7807) is returned by multiple error paths across all
    Phase-6a routers.  It must appear in ``components.schemas`` so that:
    - The Go oapi-codegen frontend generates a typed ``ProblemDetail`` struct.
    - Consumers can reference it in their own OpenAPI tooling.

    If this test fails, check that ``app/schemas/problem.py`` defines
    ``ProblemDetail(BaseModel)`` and that at least one route uses it as a
    ``response_model`` (which causes FastAPI to register it as a component).
    """
    components = openapi_schema.get("components", {}).get("schemas", {})
    assert "ProblemDetail" in components, (
        "ProblemDetail is not registered in components.schemas.  "
        "Ensure at least one route declares ``response_model=ProblemDetail`` "
        "so FastAPI includes it in the schema."
    )
