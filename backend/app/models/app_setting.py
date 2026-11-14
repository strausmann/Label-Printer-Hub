# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SQLModel table for runtime settings (D4/D5).

Non-secret values live JSON-encoded in ``value_json``. A secret is stored only as the
sealed token in ``secret_token`` (never plaintext); for a secret row ``value_json`` holds
``{"bound_url": ...}``, the URL the secret was saved with.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlmodel import Column, Field, SQLModel


class AppSetting(SQLModel, table=True):
    __tablename__ = "app_settings"

    key: str = Field(sa_column=Column(String, primary_key=True))
    value_json: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    secret_token: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
