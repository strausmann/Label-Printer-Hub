"""The body of Grocy's label printer webhook (#281, spec section 6, R-281-3 to R-281-5).

Grocy (``helpers/WebhookRunner.php``, commit ``146f73af``) POSTs one JSON object per label: a
name field that depends on the label type, the Grocycode, ``details`` (the full product or
recipe row) and, for a stock entry, ``stock_entry`` and an optional ``due_date``. Its
``LABEL_PRINTER_PARAMS`` are merged into the same object and can add any key.

Only what the label needs is read. Every other field — ``details`` and ``stock_entry``
included — is ignored and never declared, so a pasted image in a description or an odd
``font_family`` parameter changes nothing. The label type comes from the Grocycode, not from
which name field is present; a name field that does not belong to the type is a
:class:`GrocyLabelMismatchError`. The hub never calls back to Grocy for a label.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.print_request import RAW_TEXT_MAX, RawLabelData
from app.sheets.text import sanitise_text

GrocyLabelType = Literal["product", "stock_entry", "chore", "battery", "recipe"]

GROCYCODE_PATTERN = r"^grcy:(p|b|c|r):[0-9]{1,10}(:[^:\s]{1,64}){0,3}$"
"""Grocy's ``grcy:<entity>:<id>[:<extra>…]`` (``docs/grocycode.md``), plus ``r`` (recipes),
which Grocy's code prints although the documented grammar does not list it."""

MAX_GROCY_LABEL_BODY = 1_048_576
"""The largest body the route reads (R-281-3): ``details`` can hold pasted images."""

GROCY_LABEL_BUDGET_S = 1.5
"""The route answers within this time (R-281-11); Grocy gives up after 2.0 s."""

DUE_DATE_MAX = 64

_ENTITY_TYPES: dict[str, GrocyLabelType] = {
    "b": "battery",
    "c": "chore",
    "r": "recipe",
}

_NAME_FIELD: dict[GrocyLabelType, str] = {
    "product": "product",
    "stock_entry": "product",
    "chore": "chore",
    "battery": "battery",
    "recipe": "recipe",
}

_CODE_RE = re.compile(GROCYCODE_PATTERN)


class GrocyLabelMismatchError(ValueError):
    """The name field of the code's label type is missing (``grocy_label_mismatch``)."""


def grocy_label_type(code: str) -> GrocyLabelType:
    """The label type of a Grocycode that matches :data:`GROCYCODE_PATTERN`."""
    parts = code.split(":")
    if parts[1] == "p":
        return "stock_entry" if len(parts) > 3 else "product"
    return _ENTITY_TYPES[parts[1]]


def _clean(value: str | None, max_len: int) -> str | None:
    if value is None:
        return None
    cleaned = sanitise_text(value, max_len=max_len)
    return cleaned or None


class GrocyLabelPayload(BaseModel):
    """What the hub reads from one label request of Grocy."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    grocycode: str = Field(
        pattern=GROCYCODE_PATTERN,
        description=(
            "The Grocycode of the object, for example 'grcy:p:12' (product), "
            "'grcy:p:12:63a1b2c3d4e5f' (stock entry), 'grcy:c:3' (chore), 'grcy:b:4' "
            "(battery) or 'grcy:r:5' (recipe). It decides the label type and is the QR code"
        ),
    )
    product: str | None = Field(
        default=None,
        max_length=RAW_TEXT_MAX,
        description="The product name, for a product or stock entry label",
    )
    chore: str | None = Field(
        default=None, max_length=RAW_TEXT_MAX, description="The chore name, for a chore label"
    )
    battery: str | None = Field(
        default=None,
        max_length=RAW_TEXT_MAX,
        description="The battery name, for a battery label",
    )
    recipe: str | None = Field(
        default=None, max_length=RAW_TEXT_MAX, description="The recipe name, for a recipe label"
    )
    due_date: str | None = Field(
        default=None,
        max_length=DUE_DATE_MAX,
        description=(
            "Grocy's localised due date line of a stock entry, for example 'DD: 2026-12-01'. "
            "Printed as the third line of a stock entry label"
        ),
    )

    @field_validator("product", "chore", "battery", "recipe")
    @classmethod
    def _clean_name(cls, value: str | None) -> str | None:
        return _clean(value, RAW_TEXT_MAX)

    @field_validator("due_date")
    @classmethod
    def _clean_due_date(cls, value: str | None) -> str | None:
        return _clean(value, DUE_DATE_MAX)

    @property
    def label_type(self) -> GrocyLabelType:
        return grocy_label_type(self.grocycode)

    def to_raw_label(self) -> RawLabelData:
        """The label data (R-281-5); a missing name of the code's type raises a mismatch."""
        label_type = self.label_type
        name = getattr(self, _NAME_FIELD[label_type])
        if not name:
            raise GrocyLabelMismatchError(
                f"a {label_type} label needs the '{_NAME_FIELD[label_type]}' field"
            )
        secondary = (self.due_date,) if label_type == "stock_entry" and self.due_date else ()
        return RawLabelData(
            title=name,
            primary_id=self.grocycode.split(":")[2],
            qr_payload=self.grocycode,
            secondary=secondary,
        )


def is_grocycode(value: object) -> bool:
    """Whether ``value`` is a string in :data:`GROCYCODE_PATTERN`."""
    return isinstance(value, str) and _CODE_RE.fullmatch(value) is not None
