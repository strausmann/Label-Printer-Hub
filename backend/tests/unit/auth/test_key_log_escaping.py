"""Rejected API keys are logged with their prefix escaped (CodeQL py/log-injection #18, #19).

The prefix comes from the request header. HTTP parsers refuse CR/LF in header values, but the
function itself must not rely on that: a control character in the prefix must not start a new
log line.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from app.auth import dependencies

_KEY = "lph_ab\r\nFAKE LOG LINE 0123456789abcdef"


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == dependencies._log.name]


async def test_unknown_key_prefix_is_logged_escaped(monkeypatch, caplog):
    async def no_row(_session, _prefix):
        return None

    monkeypatch.setattr(dependencies.api_keys_repo, "get_by_prefix", no_row)
    caplog.set_level(logging.DEBUG, logger=dependencies._log.name)

    with pytest.raises(dependencies.HTTPException) as exc:
        await dependencies._validate_api_key(None, _KEY, "read", "192.0.2.1")
    assert exc.value.status_code == 401

    messages = _messages(caplog)
    assert messages, "the rejected key must still be logged"
    assert not any("\n" in m or "\r" in m for m in messages)
    assert any("\\r\\n" in m for m in messages)


async def test_bcrypt_mismatch_prefix_is_logged_escaped(monkeypatch, caplog):
    row = SimpleNamespace(enabled=True, expires_at=None, key_hash="unused")

    async def a_row(_session, _prefix):
        return row

    async def mismatch(_key, _hash):
        return False

    monkeypatch.setattr(dependencies.api_keys_repo, "get_by_prefix", a_row)
    monkeypatch.setattr(dependencies, "verify_api_key_async", mismatch)
    caplog.set_level(logging.DEBUG, logger=dependencies._log.name)

    with pytest.raises(dependencies.HTTPException) as exc:
        await dependencies._validate_api_key(None, _KEY, "read", "192.0.2.1")
    assert exc.value.status_code == 401

    messages = _messages(caplog)
    assert messages, "the rejected key must still be logged"
    assert not any("\n" in m or "\r" in m for m in messages)
    assert any("\\r\\n" in m for m in messages)
