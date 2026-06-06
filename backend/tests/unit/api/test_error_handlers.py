"""Unit tests for app.api.error_handlers.

Each test builds a minimal FastAPI app with one route that raises a mapped
exception, registers the global handlers via :func:`register_error_handlers`,
then hits the route and asserts the RFC 7807 ProblemDetail shape + status code.

All mapped exceptions are covered (one test per mapping in ``_MAPPING``).

Phase 1k.1a (Task 25): TemplateNotFoundError and template_loader removed.
Tests for template_not_found removed; error_handlers._MAPPING no longer
contains a TemplateNotFoundError entry.
"""

from __future__ import annotations

import pytest
from app.api.error_handlers import register_error_handlers
from app.printer_backends.exceptions import (
    PrinterCoverOpenError,
    PrinterOfflineError,
    TapeEmptyError,
    TapeMismatchError,
)
from app.services.errors import AppLookupNotFoundError
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _app_raising(exc: Exception) -> FastAPI:
    """Return a tiny app whose single route raises *exc* unconditionally."""
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise exc

    return app


# ---------------------------------------------------------------------------
# One test per _MAPPING entry
# ---------------------------------------------------------------------------


def test_printer_offline_returns_503_problem_detail() -> None:
    client = TestClient(
        _app_raising(PrinterOfflineError("host unreachable")),
        raise_server_exceptions=False,
    )
    r = client.get("/boom")
    assert r.status_code == 503
    body = r.json()
    assert body["type"] == "printer-offline"
    assert body["status"] == 503
    assert "host unreachable" in body["detail"]
    assert "title" in body


def test_tape_mismatch_returns_409_problem_detail() -> None:
    exc = TapeMismatchError(expected_mm=12, loaded_mm=24)
    client = TestClient(_app_raising(exc), raise_server_exceptions=False)
    r = client.get("/boom")
    assert r.status_code == 409
    body = r.json()
    assert body["type"] == "tape-mismatch"
    assert body["status"] == 409
    assert "12mm" in body["detail"]


def test_tape_empty_returns_409_problem_detail() -> None:
    client = TestClient(
        _app_raising(TapeEmptyError("no media")),
        raise_server_exceptions=False,
    )
    r = client.get("/boom")
    assert r.status_code == 409
    body = r.json()
    assert body["type"] == "tape-empty"
    assert body["status"] == 409


def test_printer_cover_open_returns_409_problem_detail() -> None:
    client = TestClient(
        _app_raising(PrinterCoverOpenError("cover open")),
        raise_server_exceptions=False,
    )
    r = client.get("/boom")
    assert r.status_code == 409
    body = r.json()
    assert body["type"] == "printer-cover-open"
    assert body["status"] == 409


def test_app_lookup_not_found_returns_404_problem_detail() -> None:
    client = TestClient(
        _app_raising(AppLookupNotFoundError("asset 99 not found")),
        raise_server_exceptions=False,
    )
    r = client.get("/boom")
    assert r.status_code == 404
    body = r.json()
    assert body["type"] == "app-lookup-not-found"
    assert body["status"] == 404
    assert "asset 99 not found" in body["detail"]


# ---------------------------------------------------------------------------
# Shape invariants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        PrinterOfflineError("offline"),
        TapeMismatchError(expected_mm=6, loaded_mm=None),
        TapeEmptyError("empty"),
        PrinterCoverOpenError("open"),
        AppLookupNotFoundError("not found"),
    ],
)
def test_all_handlers_return_problem_detail_with_required_fields(exc: Exception) -> None:
    """Every mapped exception must produce a body with type/title/status."""
    client = TestClient(_app_raising(exc), raise_server_exceptions=False)
    r = client.get("/boom")
    body = r.json()
    assert "type" in body
    assert "title" in body
    assert "status" in body
    # extensions may be absent (exclude_none drops it when empty)
    # instance is optional
