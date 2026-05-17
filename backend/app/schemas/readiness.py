"""Phase 7b Cluster 1e — readiness response shape."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class CheckStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ok", "fail", "skipped", "stale"]
    detail: str | None = None
    metric: dict[str, Any] | None = None


class ReadinessResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ready", "degraded", "not-ready"]
    checks: dict[str, CheckStatus]
    version: str
    revision: str
