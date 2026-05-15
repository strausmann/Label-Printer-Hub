"""Load and cache seed templates from YAML files.

TemplateLoader is class-level state (analogous to IntegrationRegistry).
Importing this module does not load anything — call ``load_dir(path)``
from ``main.py`` after plugin discovery so the registry-validation
sees all registered plugins.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import yaml
from pydantic import ValidationError

from app.integrations.registry import IntegrationRegistry
from app.schemas.template import TemplateSchema


class TemplateValidationError(Exception):
    """A YAML file failed to parse into a valid TemplateSchema."""


class TemplateLoader:
    """Class-level cache of seed templates."""

    _cache: ClassVar[dict[str, TemplateSchema]] = {}

    @classmethod
    def _load_single(cls, path: Path) -> TemplateSchema:
        """Parse one YAML file, raise TemplateValidationError on any failure."""
        try:
            raw = yaml.safe_load(path.read_text())
        except yaml.YAMLError as e:
            raise TemplateValidationError(f"{path.name}: YAML parse error: {e}") from e

        if not isinstance(raw, dict):
            raise TemplateValidationError(
                f"{path.name}: top-level YAML must be a mapping, got {type(raw).__name__}"
            )

        try:
            template = TemplateSchema(**raw)
        except ValidationError as e:
            raise TemplateValidationError(f"{path.name}: schema validation failed: {e}") from e

        if template.app is not None and template.app not in IntegrationRegistry.names():
            raise TemplateValidationError(
                f"{path.name}: references unknown integration {template.app!r}. "
                f"Registered: {IntegrationRegistry.names()}"
            )

        return template

    @classmethod
    def load_dir(cls, directory: Path) -> None:
        """Parse every ``*.yaml`` in ``directory`` and cache by template id.

        Strict: any single-file failure raises TemplateValidationError
        and the cache is left in whatever state it was before the call
        (the broken file is not silently skipped — shipping a broken
        seed template is a build-time bug).
        """
        for path in sorted(directory.glob("*.yaml")):
            template = cls._load_single(path)
            cls._cache[template.id] = template

    @classmethod
    def get(cls, template_id: str) -> TemplateSchema:
        """Return the cached template or raise KeyError."""
        if template_id not in cls._cache:
            raise KeyError(f"Template {template_id!r} not loaded")
        return cls._cache[template_id]

    @classmethod
    def all(cls) -> dict[str, TemplateSchema]:
        """Return a shallow copy of the cache (caller may mutate safely)."""
        return dict(cls._cache)

    @classmethod
    def by_app(cls, app: str | None) -> list[TemplateSchema]:
        """Return all templates whose ``app`` matches the argument exactly.

        ``by_app(None)`` returns generic (QR-only) templates.
        """
        return [t for t in cls._cache.values() if t.app == app]

    @classmethod
    def reload(cls, directory: Path) -> None:
        """Drop the cache then re-run load_dir.

        Used by the future template editor (Phase 7) after a YAML write.
        """
        cls._cache.clear()
        cls.load_dir(directory)
