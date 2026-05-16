"""API schema for the lookup endpoint (Phase 6a Task 4).

``LookupResult`` is the JSON-serialisable view of what ``AppLookupService``
returns.  It wraps ``LabelData`` (the internal domain object) by projecting its
fields into a stable REST shape — callers see ``app``, ``id``, ``name``,
``url`` (external deep-link), and ``extra`` for integration-specific extras.

Keeping this as a separate schema (rather than exposing ``LabelData`` directly)
means we can evolve the internal ``LabelData`` shape without changing the
public API contract.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LookupResult(BaseModel):
    """REST view of a resolved integration entity."""

    model_config = ConfigDict(frozen=True)

    app: Literal["snipeit", "grocy", "spoolman"] = Field(
        description="Integration app that resolved this entity",
    )
    id: str = Field(
        description="The entity identifier as supplied by the caller",
    )
    name: str = Field(
        description="Human-readable display name of the entity",
    )
    url: str = Field(
        description=(
            "Deep-link URL to the entity in the integration's web UI "
            "(e.g. Snipe-IT asset page, Grocy product page, Spoolman spool page)"
        ),
    )
    extra: dict[str, object] = Field(
        default_factory=dict,
        description=(
            "Integration-specific extras not covered by the core fields. "
            "Contents vary by app — see each integration's plugin docs."
        ),
    )
