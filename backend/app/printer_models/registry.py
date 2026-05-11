"""Discover printer-model plugins by PJL or SNMP fingerprint."""

from __future__ import annotations

from typing import ClassVar

from app.printer_models.base import PrinterModel


class ModelNotFoundError(Exception):
    """No registered plugin claims the given printer fingerprint."""


class ModelRegistry:
    """Class-level registry of PrinterModel plugins.

    Plugins register themselves at import time. Production code calls
    `find_by_pjl()` or `find_by_snmp_oid_value()` to resolve a discovered
    printer to its driver.
    """

    _models: ClassVar[list[PrinterModel]] = []

    @classmethod
    def register(cls, model: PrinterModel) -> None:
        """Append *model* to the registry. Duplicate registrations are not prevented."""
        cls._models.append(model)

    @classmethod
    def all(cls) -> list[PrinterModel]:
        """Return a copy of all registered plugins."""
        return list(cls._models)

    @classmethod
    def find_by_pjl(cls, pjl_string: str) -> PrinterModel:
        """Match a plugin by PJL MDL substring.

        Returns the first registered plugin whose signature matches. Registration
        order determines priority if multiple plugins match.

        Example pjl_string: 'MFG:Brother;CMD:PJL;MDL:PT-P750W;CLS:PRINTER;'
        """
        for model in cls._models:
            for sig in model.pjl_signatures:
                if sig in pjl_string:
                    return model
        raise ModelNotFoundError(f"No plugin matched PJL string: {pjl_string!r}")

    @classmethod
    def find_by_snmp_oid_value(cls, oid_value: str) -> PrinterModel:
        """Match a plugin by SNMP model-OID value substring.

        Returns the first registered plugin whose signature matches. Registration
        order determines priority if multiple plugins match.
        """
        for model in cls._models:
            if model.snmp_model_oid_value_substr in oid_value:
                return model
        raise ModelNotFoundError(f"No plugin matched SNMP OID value: {oid_value!r}")
