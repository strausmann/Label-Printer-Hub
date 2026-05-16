"""RFC 7807 Problem Details schema.

Used for consistent error responses across all Phase 6a REST routes.

References:
    https://www.rfc-editor.org/rfc/rfc7807
    docs/superpowers/specs/2026-05-16-phase6a-rest-api-design.md
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProblemDetail(BaseModel):
    """RFC 7807 Problem Details object.

    All fields are optional except ``type``, ``title``, and ``status``.
    The ``extensions`` field carries additional problem-type-specific
    context (e.g. ``expected_mm`` / ``loaded_mm`` for tape mismatches).
    """

    type: str = Field(
        default="about:blank",
        description="URI reference identifying the problem type",
    )
    title: str = Field(description="Short human-readable summary of the problem")
    status: int = Field(description="HTTP status code")
    detail: str | None = Field(
        default=None,
        description="Human-readable explanation specific to this occurrence",
    )
    instance: str | None = Field(
        default=None,
        description="URI reference identifying this specific occurrence",
    )
    extensions: dict[str, object] = Field(
        default_factory=dict,
        description="Additional problem-type-specific fields",
    )
