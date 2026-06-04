"""Phase 1i Sub-Task H (CA-2): BackendRouter.

Map printer_slug -> Backend-Instanz + PrintService-Instanz.
Wird in lifespan nach PrinterConfigLoader.load_file() instanziert.
batch_dispatch ruft router.service_for(slug) auf (R4-A-C2-Fix: Volle Multi-Printer).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.printer_backends.base import PrinterBackend
from app.printer_backends.brother_ql_backend import BrotherQLBackend
from app.printer_backends.ptouch_backend import PTouchBackend
from app.schemas.printer_config import PrinterYAMLConfig

if TYPE_CHECKING:
    from app.services.print_service import PrintService


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
