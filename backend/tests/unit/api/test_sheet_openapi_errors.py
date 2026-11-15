# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The OpenAPI document describes the 422 envelope the sheet APIs really return."""

from __future__ import annotations

import base64
import tempfile
from typing import Any

import pytest
from app.api.error_handlers import (
    SHEET_ERROR_SCHEMA_NAME,
    WEBHOOK_PREFIX,
    is_sheet_path,
)


@pytest.fixture
def schema(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    key = base64.urlsafe_b64encode(
        bytes(32)
    ).decode()  # all-zero throw-away key, schema export only
    monkeypatch.setenv("LABELYARD_SECRET_KEY", key)
    monkeypatch.setenv("LABELYARD_PUBLIC_URL", "http://localhost:8000")
    monkeypatch.setenv("LABELYARD_WEB_DIST_DIR", tempfile.gettempdir())
    monkeypatch.setenv("LABELYARD_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    from app.main import create_app

    return create_app()._app.openapi()  # type: ignore[no-any-return]


def test_sheet_routes_declare_the_envelope_for_422(schema: dict[str, Any]) -> None:
    ref = f"#/components/schemas/{SHEET_ERROR_SCHEMA_NAME}"
    seen = 0
    for path, item in schema["paths"].items():
        if not is_sheet_path(path):
            continue
        for operation in item.values():
            response = operation["responses"].get("422")
            if response is None:
                continue
            seen += 1
            assert response["content"]["application/json"]["schema"] == {"$ref": ref}, path
    assert seen > 10
    assert SHEET_ERROR_SCHEMA_NAME in schema["components"]["schemas"]


def test_other_routes_keep_the_default_validation_schema(schema: dict[str, Any]) -> None:
    others = [
        op["responses"]["422"]
        for path, item in schema["paths"].items()
        if not is_sheet_path(path) and not path.startswith(WEBHOOK_PREFIX)
        for op in item.values()
        if "content" in op["responses"].get("422", {})
    ]
    assert others
    assert all(
        r["content"]["application/json"]["schema"]
        == {"$ref": "#/components/schemas/HTTPValidationError"}
        for r in others
    )


def test_every_4xx_of_the_sheet_routes_carries_the_envelope(schema: dict[str, Any]) -> None:
    ref = f"#/components/schemas/{SHEET_ERROR_SCHEMA_NAME}"
    codes: set[str] = set()
    for path, item in schema["paths"].items():
        if not is_sheet_path(path):
            continue
        for operation in item.values():
            for code, response in operation["responses"].items():
                if code.startswith("4"):
                    codes.add(code)
                    assert response["content"]["application/json"]["schema"] == {"$ref": ref}, (
                        path,
                        code,
                    )
    assert {"404", "409", "413", "422"} <= codes


def test_error_detail_may_be_null(schema: dict[str, Any]) -> None:
    detail = schema["components"]["schemas"][SHEET_ERROR_SCHEMA_NAME]["properties"]["detail"]
    options = detail["properties"]["error_detail"]["anyOf"]
    assert {"type": "null"} in options


def test_webhook_routes_declare_the_envelope_for_422(schema: dict[str, Any]) -> None:
    """The handler answers a webhook validation error with the envelope (run-12 R12-1: the value
    is not repeated), so the document must say so, not ``HTTPValidationError`` (Codex P2)."""
    ref = f"#/components/schemas/{SHEET_ERROR_SCHEMA_NAME}"
    webhook_paths = [p for p in schema["paths"] if p.startswith(WEBHOOK_PREFIX)]
    assert len(webhook_paths) == 2
    for path in webhook_paths:
        for operation in schema["paths"][path].values():
            response = operation["responses"]["422"]
            assert response["content"]["application/json"]["schema"] == {"$ref": ref}, path


def test_every_path_with_the_no_echo_handler_is_declared(schema: dict[str, Any]) -> None:
    """One predicate decides both the answer and the document."""
    from app.api.error_handlers import answers_with_envelope

    ref = f"#/components/schemas/{SHEET_ERROR_SCHEMA_NAME}"
    for path, item in schema["paths"].items():
        if not answers_with_envelope(path):
            continue
        for operation in item.values():
            response = operation["responses"].get("422")
            if response is not None:
                assert response["content"]["application/json"]["schema"] == {"$ref": ref}, path
