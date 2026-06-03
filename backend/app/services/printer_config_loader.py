"""Phase 1i Sub-Task H: PrinterConfigLoader (analog TemplateLoader).

M-H4-Fix: load_file (eine Datei, kein Glob) — printers.yaml ist eine einzelne Datei.
M-H6-Fix: by_backend() entfernt (YAGNI).
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import yaml

from app.schemas.printer_config import PrintersFile, PrinterYAMLConfig


class PrinterConfigLoader:
    _cache: ClassVar[dict[str, PrinterYAMLConfig]] = {}

    @classmethod
    def load_file(cls, path: Path) -> None:
        """Parse YAML, validate via PrintersFile, atomic replace cache."""
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        parsed = PrintersFile.model_validate(raw)
        cls._cache = {p.slug: p for p in parsed.printers}

    @classmethod
    def reload_file(cls, path: Path) -> None:
        """API-Reservierung für künftiges Hot-Reload (Phase-1i: identisch zu load_file)."""
        cls.load_file(path)

    @classmethod
    def get(cls, slug: str) -> PrinterYAMLConfig | None:
        return cls._cache.get(slug)

    @classmethod
    def all(cls) -> list[PrinterYAMLConfig]:
        return list(cls._cache.values())

    @classmethod
    def clear(cls) -> None:
        """Test-only helper — reset cache between fixture-scoped tests."""
        cls._cache = {}
