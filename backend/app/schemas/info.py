"""Schemas for ``GET /api/info`` and ``GET /api/v1/system/logs``."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class InfoAuth(BaseModel):
    model_config = ConfigDict(frozen=True)

    sso_configured: bool
    bootstrap_open: bool


class InfoIntegration(BaseModel):
    """Whether an integration is set up. Never carries a URL or a key."""

    model_config = ConfigDict(frozen=True)

    name: Literal["snipeit", "grocy", "spoolman"]
    configured: bool


class Info(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str
    revision: str
    build_date: str
    default_language: Literal["en", "de"]
    display_name: str
    auth: InfoAuth
    features: dict[str, bool]
    integrations: list[InfoIntegration]


class LogEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    ts: datetime
    level: str
    logger: str
    message: str
