# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for the new required/optional settings fields (secret key, public URL, bootstrap key)."""

from __future__ import annotations

import base64

import pytest
from app.config import Settings
from pydantic import ValidationError

FAKE_KEY = base64.urlsafe_b64encode(b"fake-test-key-0123456789abcdef!!").decode()
PUBLIC_URL = "http://localhost:8000"


def _make(**overrides: object) -> Settings:
    kwargs: dict[str, object] = {"secret_key": FAKE_KEY, "public_url": PUBLIC_URL}
    kwargs.update(overrides)
    return Settings(_env_file=None, **kwargs)  # type: ignore[arg-type]


def test_printers_config_field_removed() -> None:
    assert "printers_config" not in Settings.model_fields


@pytest.mark.usefixtures("clean_settings_env")
def test_secret_key_required() -> None:
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None, public_url=PUBLIC_URL)  # type: ignore[call-arg]
    assert "secret_key" in str(exc.value)


@pytest.mark.usefixtures("clean_settings_env")
def test_public_url_required() -> None:
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None, secret_key=FAKE_KEY)  # type: ignore[call-arg]
    assert "public_url" in str(exc.value)


def test_secret_key_must_decode_to_32_bytes() -> None:
    short = base64.urlsafe_b64encode(b"0123456789abcdef").decode()
    with pytest.raises(ValidationError, match="32 bytes"):
        _make(secret_key=short)


def test_secret_key_must_be_base64url() -> None:
    with pytest.raises(ValidationError, match="base64url"):
        _make(secret_key="not base64 at all!!")


def test_secret_key_unpadded_accepted() -> None:
    raw = base64.urlsafe_b64encode(b"x" * 32).decode().rstrip("=")
    assert _make(secret_key=raw).secret_key.get_secret_value() == raw


def test_bootstrap_key_short_rejected() -> None:
    with pytest.raises(ValidationError, match="bootstrap_admin_key"):
        _make(bootstrap_admin_key="x" * 10)


def test_bootstrap_key_empty_passes() -> None:
    assert _make().bootstrap_admin_key.get_secret_value() == ""


def test_bootstrap_key_long_passes() -> None:
    assert _make(bootstrap_admin_key="x" * 32).bootstrap_admin_key.get_secret_value() == "x" * 32


def test_new_optional_defaults() -> None:
    s = _make()
    assert str(s.web_dist_dir) == "/opt/app/web"
    assert s.paperless_url == ""
    assert s.paperless_token.get_secret_value() == ""
    assert s.paperless_timeout == 5.0
