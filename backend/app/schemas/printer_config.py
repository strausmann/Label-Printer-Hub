"""Phase 1i Sub-Task H: Pydantic-Schemas für printers.yaml.

C-H1-Fix: Klasse heißt PrinterYAMLConfig — verhindert Kollision mit DB-Model
`Printer`, Schemas `PrinterRead`, `PrinterStatus`.

MA-4-Fix: extra="forbid" auf allen Schemas — unbekannte Felder schlagen beim
Start laut fehl, erzwingt explizite Schema-Bumps.

MA-1-Fix: Cross-Validator schlägt PrinterConfigValidationError, wenn
cut_defaults.half_cut=True UND backend=brother_ql (kein echter Half-Cut).

m-H1-Fix: PrinterConfigValidationError als eigene Exception.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PrinterConfigValidationError(ValueError):
    """Semantisch ungültige printer_config-Werte."""


class SNMPConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    discover: bool = True
    community: str = "public"


class QueueConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timeout_s: int = 30


class CutDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")
    half_cut: bool = True
    cut_at_end: bool = True


class PrinterYAMLConfig(BaseModel):
    """C-H1-Fix: PrinterYAMLConfig (nicht PrinterConfig)."""

    model_config = ConfigDict(extra="forbid")  # MA-4-Fix

    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    backend: Literal["ptouch", "brother_ql"]
    model: str  # Library-konformes Modell (PT-P750W, QL-820NWB — ohne 'c')
    host: str
    port: int = 9100
    snmp: SNMPConfig = Field(default_factory=SNMPConfig)
    queue: QueueConfig = Field(default_factory=QueueConfig)
    cut_defaults: CutDefaults = Field(default_factory=CutDefaults)

    @model_validator(mode="after")
    def validate_cut_defaults_vs_backend(self) -> PrinterYAMLConfig:
        # MA-1-Fix: Cross-Validierung
        if self.cut_defaults.half_cut and self.backend == "brother_ql":
            raise PrinterConfigValidationError(
                f"PrinterYAMLConfig '{self.slug}': cut_defaults.half_cut=True erfordert "
                f"half_cut_supported=True (nur PT-Series). Setze cut_defaults.half_cut=false "
                f"für QL-Drucker."
            )
        return self


class PrintersFile(BaseModel):
    model_config = ConfigDict(extra="forbid")  # MA-4-Fix
    schema_version: int = 1
    printers: list[PrinterYAMLConfig]

    @field_validator("printers")
    @classmethod
    def slugs_unique(cls, v: list[PrinterYAMLConfig]) -> list[PrinterYAMLConfig]:
        slugs = [p.slug for p in v]
        if len(slugs) != len(set(slugs)):
            raise ValueError("Duplicate printer slug in printers.yaml")
        return v
