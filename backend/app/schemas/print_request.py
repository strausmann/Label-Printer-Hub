"""Request schemas for POST /print and supporting models."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PrintLookupRequest(BaseModel):
    """Resolve label data via an integration plugin."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    app: str
    identifier: str


class PrintOptions(BaseModel):
    """Per-print options — copies, cut behaviour, resolution."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    copies: int = Field(default=1, ge=1, le=10)
    auto_cut: bool = True
    high_resolution: bool = False
    # Phase 1i C-Fix:
    half_cut: bool = False
    last_page: bool = True


class RawLabelData(BaseModel):
    """Raw label payload accepted when the client supplies data directly.

    Mirrors LabelData minus `source_app` (always set to "manual" server-side).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    title: str
    primary_id: str
    qr_payload: str
    secondary: list[str] = Field(default_factory=list)


class PrintRequest(BaseModel):
    """Top-level POST /print body."""

    model_config = ConfigDict(extra="forbid")
    template_id: str
    lookup: PrintLookupRequest | None = None
    data: RawLabelData | None = None
    options: PrintOptions = Field(default_factory=PrintOptions)
    on_tape_mismatch: Literal["fail", "queue"] = "fail"

    @model_validator(mode="after")
    def _exactly_one_source(self) -> Self:
        if (self.lookup is None) == (self.data is None):
            raise ValueError("Exactly one of `lookup` or `data` must be set.")
        return self
