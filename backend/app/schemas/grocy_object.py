# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""API schemas for the Grocy battery and chore lookups (the scan page's Grocycode view).

Only the facts the page shows. The response bodies are built field by field from Grocy's
answer, never passed through (Grocy's objects carry user fields and internal columns).
Dates are Grocy's own local time, so they carry no offset.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

_DATE = "Grocy's local time, without a time zone offset; null when Grocy has no such date."


class GrocyBatteryResult(BaseModel):
    """What Grocy knows about one battery."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(description="The battery id")
    name: str = Field(description="The battery's name")
    description: str | None = Field(default=None, description="The description, when one is set")
    url: str | None = Field(default=None, description="The battery's page in Grocy's web UI")
    last_charged: datetime | None = Field(
        default=None, description=f"When it was last charged. {_DATE}"
    )
    next_estimated_charge: datetime | None = Field(
        default=None,
        description=f"When it is estimated to need charging next; null without interval. {_DATE}",
    )
    charge_cycles: int = Field(default=0, ge=0, description="How often it was charged so far")


class GrocyChoreResult(BaseModel):
    """What Grocy knows about one chore."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(description="The chore id")
    name: str = Field(description="The chore's name")
    description: str | None = Field(default=None, description="The description, when one is set")
    url: str | None = Field(default=None, description="The chore's page in Grocy's web UI")
    last_tracked: datetime | None = Field(
        default=None, description=f"When it was last done. {_DATE}"
    )
    next_estimated_execution: datetime | None = Field(
        default=None,
        description=f"When it is estimated to be done next; null when it is not scheduled. {_DATE}",
    )
    assigned_to: str | None = Field(
        default=None,
        description="Display name of the user assigned to the next run, if Grocy returns one",
    )
