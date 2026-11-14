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

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.printer_backends.ipp.client import validate_ipp_uri
from app.schemas.label_layout import LayoutDefault, check_layout_defaults
from app.sheets.text import sanitise_text

SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$"
TRAY_KEY_PATTERN = r"^[a-z0-9][a-z0-9-]{0,63}$"
"""IPP ``media-source`` keyword shape, or ``auto`` (send no ``media-source``)."""
MAX_TRAYS = 16
MAX_IPP_URI_LENGTH = 1023
"""RFC 8011 ``uri`` values are at most 1023 octets."""


SNMP_COMMUNITY_DOC = (
    "Write-only (#296). Omitted or null keeps the stored community (``public`` on create); "
    "a non-empty string replaces it. Responses never carry it; they report "
    "``connection.snmp.community_set`` instead."
)


class SNMPConfig(BaseModel):
    """SNMP status discovery of a tape printer. The community is write-only (#296)."""

    # ``None`` means "keep the stored one"; the service resolves it (merge_snmp_community).
    # An explicit empty string with ``discover`` on is refused here; whether a stored
    # community satisfies ``discover`` only the service can tell, as it knows the stored row.

    discover: bool = False
    community: str | None = Field(default=None, max_length=64, description=SNMP_COMMUNITY_DOC)

    @model_validator(mode="after")
    def _community_required_if_discover(self) -> SNMPConfig:
        if self.discover and self.community == "":
            raise ValueError("snmp.community ist Pflicht wenn snmp.discover=True ist")
        return self


class PrinterConnection(BaseModel):
    """Verbindungsparameter für einen Drucker."""

    host: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65535)
    snmp: SNMPConfig = Field(default_factory=SNMPConfig)


class IppConnection(BaseModel):
    """Connection of an IPP page printer (spec 11.1): URI and TLS verification (OC-17).

    Only ``ipp``, ``ipps``, ``http`` and ``https``; no user info, no fragment
    (``validate_ipp_uri``). IPP authentication is out of scope (OC-2).
    """

    model_config = ConfigDict(extra="forbid")

    uri: str = Field(min_length=1, max_length=MAX_IPP_URI_LENGTH)
    tls_verify: bool = True

    @field_validator("uri")
    @classmethod
    def _valid_uri(cls, value: str) -> str:
        validate_ipp_uri(value)  # fixed message per rule, never the URI
        return value


class TrayIn(BaseModel):
    """One tray of a page printer as the admin configures it."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=TRAY_KEY_PATTERN)
    label: str = Field(min_length=1, max_length=60)
    load_hint: str | None = Field(default=None, max_length=200)
    enabled: bool = True
    is_default: bool = False

    @field_validator("label")
    @classmethod
    def _clean_label(cls, value: str) -> str:
        cleaned = sanitise_text(value, max_len=60)
        if not cleaned:
            raise ValueError("label must not be empty")
        return cleaned

    @field_validator("load_hint")
    @classmethod
    def _clean_hint(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return sanitise_text(value, max_len=200) or None


def check_trays(trays: list[TrayIn]) -> list[TrayIn]:
    """Unique keys, at least one enabled tray, exactly one default and it is enabled."""
    keys = [t.key for t in trays]
    if len(keys) != len(set(keys)):
        raise ValueError("tray keys must be unique")
    if not any(t.enabled for t in trays):
        raise ValueError("at least one tray must be enabled")
    defaults = [t for t in trays if t.is_default]
    if len(defaults) != 1:
        raise ValueError("exactly one tray must be the default")
    if not defaults[0].enabled:
        raise ValueError("the default tray must be enabled")
    return trays


_LAYOUT_DEFAULTS_DOC = (
    "Stored label layout per tape width in mm (#258), used when a print job names none: "
    '{"62": {"orientation": "across", "preset": "compact"}}. ``across`` and presets exist '
    "for 62 mm only; a missing width uses the tape default (62 mm across/compact, else along). "
    "Ignored for page printers."
)


class PrinterCutDefaults(BaseModel):
    """Standard-Schnitteinstellungen für einen Drucker."""

    half_cut: bool = False


class PrinterQueueSettings(BaseModel):
    """Warteschlangen-Einstellungen für einen Drucker."""

    timeout_s: int = Field(ge=1, le=600, default=30)


class PrinterCreatePayload(BaseModel):
    """Payload für das Anlegen eines neuen Druckers via Admin-API.

    ``ipp`` printers take an ``IppConnection`` and a required ``trays`` list; their
    ``model`` is optional (filled from the probe) and SNMP and cut defaults do not
    apply. Tape backends keep a required ``model`` and must not send ``trays``.
    """

    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(pattern=SLUG_PATTERN)
    model: str | None = Field(default=None, min_length=1, max_length=255)
    backend: Literal["ptouch", "brother_ql", "ipp"]  # D18: ipp is a backend kind
    connection: PrinterConnection | IppConnection
    queue: PrinterQueueSettings = Field(default_factory=PrinterQueueSettings)
    cut_defaults: PrinterCutDefaults = Field(default_factory=PrinterCutDefaults)
    layout_defaults: dict[int, LayoutDefault] = Field(
        default_factory=dict, description=_LAYOUT_DEFAULTS_DOC
    )
    enabled: bool = True
    trays: list[TrayIn] | None = Field(default=None, min_length=1, max_length=MAX_TRAYS)

    @field_validator("trays")
    @classmethod
    def _trays_rules(cls, value: list[TrayIn] | None) -> list[TrayIn] | None:
        return None if value is None else check_trays(value)

    @field_validator("layout_defaults")
    @classmethod
    def _layout_rules(cls, value: dict[int, LayoutDefault]) -> dict[int, LayoutDefault]:
        return check_layout_defaults(value)

    @model_validator(mode="after")
    def _backend_rules(self) -> Self:
        if self.backend == "ipp":
            if not isinstance(self.connection, IppConnection):
                raise ValueError("connection of an ipp printer must be {uri, tls_verify}")
            if self.trays is None:
                raise ValueError("trays are required for an ipp printer")
        else:
            if not isinstance(self.connection, PrinterConnection):
                raise ValueError("connection of a tape printer must be {host, port, snmp}")
            if self.trays is not None:
                raise ValueError("trays are only allowed for an ipp printer")
            if self.model is None:
                raise ValueError("model is required for a tape printer")
        return self


class PrinterUpdatePayload(BaseModel):
    """Payload für das Aktualisieren eines bestehenden Druckers via Admin-API.

    Der Service ignoriert stillschweigend: slug, model, backend, id.
    Alle Felder sind optional — ein leerer Body ist ein gültiger PATCH.

    The payload carries no backend, so the service checks ``connection`` against the
    stored row's backend; ``trays`` (replace-all) are for ``ipp`` printers only.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    connection: PrinterConnection | IppConnection | None = None
    queue: PrinterQueueSettings | None = None
    cut_defaults: PrinterCutDefaults | None = None
    layout_defaults: dict[int, LayoutDefault] | None = Field(
        default=None, description=_LAYOUT_DEFAULTS_DOC + " Replaces the stored set."
    )
    enabled: bool | None = None
    trays: list[TrayIn] | None = Field(default=None, min_length=1, max_length=MAX_TRAYS)

    @field_validator("trays")
    @classmethod
    def _trays_rules(cls, value: list[TrayIn] | None) -> list[TrayIn] | None:
        return None if value is None else check_trays(value)

    @field_validator("layout_defaults")
    @classmethod
    def _layout_rules(
        cls, value: dict[int, LayoutDefault] | None
    ) -> dict[int, LayoutDefault] | None:
        return None if value is None else check_layout_defaults(value)
