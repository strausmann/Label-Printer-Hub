"""Label-template schema describing the layout of a printable label.

A `TemplateSchema` is a recipe for placing QR codes and text on the
printable area of a Brother tape. The renderer consumes a template plus a
`LabelData` payload and emits a 1-bit PIL Image ready for the printer.

Templates are frozen at construction so they can be safely seeded as
module-level constants (see app/seed/templates.py in PR D2).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class LayoutElement(BaseModel):
    """A single drawable element — either a QR code or a text run.

    The `type` field discriminates which subset of the optional fields
    is required. `model_validator(mode="after")` enforces the contract
    at construction time so the renderer can trust the shape.
    """

    model_config = ConfigDict(frozen=True)

    type: Literal["qr", "text"]
    x: int
    y: int
    # qr-specific
    size: int | None = None
    data_field: str | None = None
    # text-specific
    field: str | None = None
    font_size: int | None = None

    @model_validator(mode="after")
    def _validate_per_type(self) -> LayoutElement:
        if self.type == "qr":
            if not self.data_field:
                raise ValueError("qr element requires data_field")
            if self.size is None or self.size <= 0:
                raise ValueError(f"qr element requires a positive size (got {self.size!r})")
        else:  # type == "text"
            if not self.field:
                raise ValueError("text element requires field")
            if self.font_size is None or self.font_size <= 0:
                raise ValueError(
                    f"text element requires a positive font_size (got {self.font_size!r})"
                )
        return self


class TemplateSchema(BaseModel):
    """A complete label template — identity, target app, tape size, and layout."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    id: str
    name: str
    app: Literal["snipeit", "grocy", "spoolman"]
    tape_mm: int
    elements: tuple[LayoutElement, ...]
