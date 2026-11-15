# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Schemas for ``GET /api/v1/info`` and ``GET /api/v1/system/logs``."""

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


class InfoCalibrationScale(BaseModel):
    """The mini scale at a crossing of the calibration page: the app draws its schematic from it."""

    model_config = ConfigDict(frozen=True)

    half_mm: float
    step_mm: float
    line_mm: float
    tick_half_mm: float
    tick_whole_mm: float
    tick_centre_mm: float


class Info(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str
    revision: str
    build_date: str
    license: str
    source_url: str
    default_language: Literal["en", "de"]
    display_name: str
    auth: InfoAuth
    features: dict[str, bool]
    integrations: list[InfoIntegration]
    calibration_scale: InfoCalibrationScale


class LogEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    ts: datetime
    level: str
    logger: str
    message: str
