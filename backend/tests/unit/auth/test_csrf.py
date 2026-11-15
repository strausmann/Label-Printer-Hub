# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""csrf.verify: double-submit token on state-changing session requests (spec 8.1)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

FAKE_CSRF = "fake-csrf-token-for-tests"


def _request(method: str, headers: dict[str, str] | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": method, "path": "/x", "headers": raw})


def _session(token: str = FAKE_CSRF) -> SimpleNamespace:
    return SimpleNamespace(csrf_token=token)


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_safe_methods_need_no_token(method: str) -> None:
    from app.auth import csrf

    csrf.verify(_request(method), _session())  # type: ignore[arg-type]


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_unsafe_method_without_header_rejected(method: str) -> None:
    from app.auth import csrf

    with pytest.raises(HTTPException) as exc:
        csrf.verify(_request(method), _session())  # type: ignore[arg-type]
    assert exc.value.status_code == 403
    assert exc.value.detail["error_code"] == "csrf_failed"  # type: ignore[index]


def test_wrong_token_rejected() -> None:
    from app.auth import csrf

    with pytest.raises(HTTPException) as exc:
        csrf.verify(_request("POST", {"X-CSRF-Token": "other"}), _session())  # type: ignore[arg-type]
    assert exc.value.status_code == 403


def test_matching_token_accepted() -> None:
    from app.auth import csrf

    csrf.verify(_request("POST", {"X-CSRF-Token": FAKE_CSRF}), _session())  # type: ignore[arg-type]


def test_non_ascii_header_rejected_not_crashing() -> None:
    from app.auth import csrf

    with pytest.raises(HTTPException) as exc:
        csrf.verify(_request("POST", {"X-CSRF-Token": "äbc"}), _session())  # type: ignore[arg-type]
    assert exc.value.status_code == 403


def test_new_token_is_random_and_urlsafe() -> None:
    from app.auth import csrf

    a, b = csrf.new_token(), csrf.new_token()
    assert a != b
    assert len(a) >= 32
    assert all(c.isalnum() or c in "-_" for c in a)
