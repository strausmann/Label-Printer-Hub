# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SQLModel table for browser sessions of the web UI.

Model only; the session behaviour (issue, verify, revoke) is added with the auth work.
``token_hash`` is the SHA-256 hex digest of the session cookie value; the cookie value
itself is never stored.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String
from sqlmodel import Column, Field, SQLModel


class UiSession(SQLModel, table=True):
    __tablename__ = "ui_sessions"
    __table_args__ = (Index("ix_ui_sessions_token_hash", "token_hash", unique=True),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    token_hash: str = Field(sa_column=Column(String, nullable=False))
    csrf_token: str = Field(sa_column=Column(String, nullable=False))
    # "api-key" | "pangolin-sso" | "bootstrap"
    source: str = Field(sa_column=Column(String, nullable=False))
    # "read" | "print" | "admin"
    scope: str = Field(sa_column=Column(String, nullable=False))
    api_key_id: UUID | None = Field(
        default=None,
        sa_column=Column(ForeignKey("api_keys.id"), nullable=True),
    )
    allowed_printer_ids: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    user: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    # pangolin-sso only: HMAC-SHA256 (keyed with LABELYARD_SECRET_KEY) of the trust token
    # the session was minted with; never the token itself. A rotated or cleared token
    # invalidates the session.
    sso_trust_fingerprint: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    revoked_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
