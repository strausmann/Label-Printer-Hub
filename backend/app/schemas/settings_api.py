"""Schemas of the settings API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, RootModel


class SettingView(BaseModel):
    key: str
    kind: Literal["str", "int", "float", "bool", "url", "secret", "enum"]
    # Always None for secrets (write-only, D5).
    value: Any | None = None
    is_set: bool
    locked: bool
    state: Literal["ok", "undecryptable", "env_secret_needs_env_url"] = "ok"
    choices: list[str] = Field(default_factory=list)


class SettingsUpdate(BaseModel):
    """Documented request body of ``PUT /api/v1/settings`` (parsed by hand, see the route)."""

    values: dict[str, Any]


class IntegrationTestRequest(BaseModel):
    """Documented request body of the test-connection route (parsed by hand)."""

    values: dict[str, Any] = Field(default_factory=dict)


class IntegrationTestResult(BaseModel):
    ok: bool
    status: int | None = None
    detail: str


class SettingsExport(RootModel[dict[str, Any]]):
    """Non-secret, non-locked settings as ``{key: value}``."""
