"""Pydantic v2-Schemas für die Admin-API der Drucker-Verwaltung (Task 2.1).

Referenzen:
    docs/superpowers/specs/ — Admin-API Design
    Issue #124 — Printers YAML-to-DB Migration

Designentscheidungen:
    - SNMPConfig ist ein verschachteltes Objekt (konsistent mit altem YAML-Schema)
    - PrinterUpdatePayload hat nur optionale Felder (PATCH-Semantik)
    - slug, model, backend und id werden bei Updates ignoriert (Kommentar im Schema)
    - Backend ist ein Literal um ungültige Werte schon im Schema abzulehnen
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$"


class SNMPConfig(BaseModel):
    """Verschachtelt — konsistent mit altem YAML-Schema."""

    discover: bool = False
    community: str | None = Field(default="public", max_length=64)

    @model_validator(mode="after")
    def _community_required_if_discover(self) -> SNMPConfig:
        if self.discover and not self.community:
            raise ValueError("snmp.community ist Pflicht wenn snmp.discover=True ist")
        return self


class PrinterConnection(BaseModel):
    """Verbindungsparameter für einen Drucker."""

    host: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65535)
    snmp: SNMPConfig = Field(default_factory=SNMPConfig)


class PrinterCutDefaults(BaseModel):
    """Standard-Schnitteinstellungen für einen Drucker."""

    half_cut: bool = False


class PrinterQueueSettings(BaseModel):
    """Warteschlangen-Einstellungen für einen Drucker."""

    timeout_s: int = Field(ge=1, le=600, default=30)


class PrinterCreatePayload(BaseModel):
    """Payload für das Anlegen eines neuen Druckers via Admin-API."""

    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(pattern=SLUG_PATTERN)
    model: str = Field(min_length=1, max_length=255)
    backend: Literal["ptouch", "brother_ql"]
    connection: PrinterConnection
    queue: PrinterQueueSettings = Field(default_factory=PrinterQueueSettings)
    cut_defaults: PrinterCutDefaults = Field(default_factory=PrinterCutDefaults)
    enabled: bool = True


class PrinterUpdatePayload(BaseModel):
    """Payload für das Aktualisieren eines bestehenden Druckers via Admin-API.

    Der Service ignoriert stillschweigend: slug, model, backend, id.
    Alle Felder sind optional — ein leerer Body ist ein gültiger PATCH.
    """

    name: str | None = None
    connection: PrinterConnection | None = None
    queue: PrinterQueueSettings | None = None
    cut_defaults: PrinterCutDefaults | None = None
    enabled: bool | None = None
