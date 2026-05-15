"""Discover printer-model plugins by PJL or SNMP fingerprint."""

from __future__ import annotations

import logging
from importlib.metadata import entry_points
from typing import ClassVar

from app.printer_models.base import PrinterModel

log = logging.getLogger(__name__)


class ModelNotFoundError(Exception):
    """No registered plugin claims the given printer fingerprint."""


class ModelRegistry:
    """Class-level registry of PrinterModel plugins.

    Plugins register themselves at import time via :meth:`register`, or are
    discovered lazily from the ``label_hub.printer_models`` entry-points group
    by calling :meth:`ensure_discovered`.

    Production code calls :meth:`find_by_pjl`, :meth:`find_by_snmp_oid_value`,
    or :meth:`find_by_model_id` to resolve a discovered printer to its driver.
    """

    _models: ClassVar[list[PrinterModel | type[PrinterModel]]] = []
    _discovered: ClassVar[bool] = False

    @classmethod
    def register(cls, model: PrinterModel | type[PrinterModel]) -> None:
        """Append *model* to the registry.

        Accepts either a :class:`PrinterModel` instance (original form) or a
        class object (as delivered by entry-points). Both carry the required
        class-level attributes (``model_id``, ``pjl_signatures``,
        ``snmp_model_oid_value_substr``).

        Duplicate registrations are not prevented.
        """
        # Resolve to class for validation — works for both instances and classes.
        entry_cls: type[PrinterModel] = model if isinstance(model, type) else type(model)
        model_id = getattr(entry_cls, "model_id", "<unknown>")

        if any(not sig for sig in entry_cls.pjl_signatures):
            raise ValueError(
                f"PrinterModel {model_id!r} has an empty PJL signature; "
                "empty substrings match every input and would shadow other plugins"
            )
        if not entry_cls.snmp_model_oid_value_substr:
            raise ValueError(
                f"PrinterModel {model_id!r} has an empty SNMP OID substring; "
                "empty substrings match every input and would shadow other plugins"
            )
        cls._models.append(model)

    @classmethod
    def all(cls) -> list[PrinterModel | type[PrinterModel]]:
        """Return a copy of all registered plugins (instances or classes)."""
        return list(cls._models)

    @classmethod
    def find_by_pjl(cls, pjl_string: str) -> PrinterModel | type[PrinterModel]:
        """Match a plugin by PJL MDL substring.

        Returns the first registered plugin whose signature matches. Registration
        order determines priority if multiple plugins match.

        Example pjl_string: 'MFG:Brother;CMD:PJL;MDL:PT-P750W;CLS:PRINTER;'
        """
        for model in cls._models:
            entry_cls: type[PrinterModel] = model if isinstance(model, type) else type(model)
            for sig in entry_cls.pjl_signatures:
                if sig in pjl_string:
                    return model
        raise ModelNotFoundError(f"No plugin matched PJL string: {pjl_string!r}")

    @classmethod
    def find_by_snmp_oid_value(cls, oid_value: str) -> PrinterModel | type[PrinterModel]:
        """Match a plugin by SNMP model-OID value substring.

        Returns the first registered plugin whose signature matches. Registration
        order determines priority if multiple plugins match.
        """
        for model in cls._models:
            entry_cls: type[PrinterModel] = model if isinstance(model, type) else type(model)
            if entry_cls.snmp_model_oid_value_substr in oid_value:
                return model
        raise ModelNotFoundError(f"No plugin matched SNMP OID value: {oid_value!r}")

    @classmethod
    def find_by_model_id(cls, model_id: str) -> type[PrinterModel]:
        """Return the driver *class* whose ``model_id`` equals *model_id*.

        Accepts both class objects and instances in the internal registry;
        always returns the class.

        Raises :exc:`ModelNotFoundError` with a helpful listing of available
        model IDs if no match is found.
        """
        for entry in cls._models:
            entry_cls: type[PrinterModel] = entry if isinstance(entry, type) else type(entry)
            if getattr(entry_cls, "model_id", None) == model_id:
                return entry_cls
        available_ids = sorted(
            {
                getattr(
                    e if isinstance(e, type) else type(e),
                    "model_id",
                    "?",
                )
                for e in cls._models
            }
        )
        available = ", ".join(available_ids) or "<none registered>"
        raise ModelNotFoundError(f"Unknown printer_model {model_id!r}. Available: {available}")

    @classmethod
    def ensure_discovered(cls) -> None:
        """Walk the ``label_hub.printer_models`` entry-points group exactly once.

        Idempotent: subsequent calls are no-ops. Intended to be called at
        application startup (e.g. FastAPI lifespan) so that installed plugins
        are available without explicit import-time registration.
        """
        if cls._discovered:
            return
        cls._discovered = True
        for ep in entry_points(group="label_hub.printer_models"):
            try:
                driver_cls = ep.load()
            except Exception:
                log.exception("Failed to load printer-model entry-point %r", ep.name)
                continue
            try:
                cls.register(driver_cls)
            except (ValueError, TypeError):
                log.exception("Failed to register printer-model %r", ep.name)
