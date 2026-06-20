"""Phase 1i Sub-Task H (CA-2): BackendRouter.

Map printer_slug -> Backend-Instanz + PrintService-Instanz.
batch_dispatch ruft router.service_for(slug) auf (R4-A-C2-Fix: Volle Multi-Printer).

Phase 5 (#124): PrinterYAMLConfig und verwandte Klassen hierher verschoben —
PrinterConfigLoader (YAML-Parser) und printer_config.py (Schema-Datei) entfernt.
BackendRouter ist nun einziger Konsument dieser Laufzeit-Konfiguration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.printer_backends.base import PrinterBackend
from app.printer_backends.brother_ql_backend import BrotherQLBackend
from app.printer_backends.ptouch_backend import PTouchBackend

if TYPE_CHECKING:
    from app.services.print_service import PrintService


# ---------------------------------------------------------------------------
# Laufzeit-Konfigurationsmodelle (verschoben aus app/schemas/printer_config.py)
# ---------------------------------------------------------------------------


class PrinterConfigValidationError(ValueError):
    """Semantisch ungültige Drucker-Konfigurationswerte."""


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
    """Laufzeit-Drucker-Konfiguration.

    Ursprünglich aus printers.yaml geladen (Phase 1i). Ab Phase 5 (#124)
    wird diese Klasse aus DB-Printer-Rows gebaut — printers.yaml entfällt.
    """

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    backend: Literal["ptouch", "brother_ql"]
    model: str
    host: str
    port: int = 9100
    snmp: SNMPConfig = Field(default_factory=SNMPConfig)
    queue: QueueConfig = Field(default_factory=QueueConfig)
    cut_defaults: CutDefaults = Field(default_factory=CutDefaults)

    @model_validator(mode="after")
    def validate_cut_defaults_vs_backend(self) -> PrinterYAMLConfig:
        if self.cut_defaults.half_cut and self.backend == "brother_ql":
            raise PrinterConfigValidationError(
                f"PrinterYAMLConfig '{self.slug}': cut_defaults.half_cut=True erfordert "
                f"half_cut_supported=True (nur PT-Series). Setze cut_defaults.half_cut=false "
                f"für QL-Drucker."
            )
        return self


class UnknownBackendError(ValueError):
    """Raised when a PrinterYAMLConfig references an unknown backend string."""


class BackendRouter:
    def __init__(self, configs: list[PrinterYAMLConfig]) -> None:
        self._configs: dict[str, PrinterYAMLConfig] = {c.slug: c for c in configs}
        self._backends: dict[str, PrinterBackend] = {c.slug: self._build_one(c) for c in configs}
        # R4-A-C2-Fix: PrintService-Map, befüllt via register_service() im Lifespan.
        self._services: dict[str, PrintService] = {}

    def get(self, slug: str) -> PrinterBackend | None:
        return self._backends.get(slug)

    def all(self) -> list[PrinterBackend]:
        return list(self._backends.values())

    def config(self, slug: str) -> PrinterYAMLConfig | None:
        return self._configs.get(slug)

    def slugs(self) -> list[str]:
        return list(self._configs.keys())

    def register_service(self, slug: str, service: PrintService) -> None:
        """Registriert einen PrintService für einen Drucker-Slug.

        Wird vom Lifespan nach make_queue_printer() pro Drucker aufgerufen.
        """
        self._services[slug] = service

    def service_for(self, slug: str) -> PrintService:
        """Gibt den PrintService für einen Drucker-Slug zurück.

        Raises KeyError wenn der Slug unbekannt oder service noch nicht registriert.
        """
        try:
            return self._services[slug]
        except KeyError as err:
            raise KeyError(
                f"No PrintService registered for slug={slug!r}. "
                f"Known slugs: {list(self._services.keys())}"
            ) from err

    @staticmethod
    def _build_one(cfg: PrinterYAMLConfig) -> PrinterBackend:
        if cfg.backend == "ptouch":
            return PTouchBackend(host=cfg.host, port=cfg.port, model_id=cfg.model)
        if cfg.backend == "brother_ql":
            return BrotherQLBackend(host=cfg.host, port=cfg.port, model_id=cfg.model)
        raise UnknownBackendError(f"Unknown backend: {cfg.backend!r}")
