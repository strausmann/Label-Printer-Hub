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


class TemplateNotFoundError(KeyError):
    """Requested template id is not registered. Subclasses KeyError so legacy
    callers that catch KeyError keep working."""


class TemplateLoader:
    """Class-level cache of seed templates."""

    _cache: ClassVar[dict[str, TemplateSchema]] = {}

    @classmethod
    def _load_single(cls, path: Path) -> TemplateSchema:
        """Parse one YAML file, raise TemplateValidationError on any failure."""
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except OSError as e:
            raise TemplateValidationError(f"{path.name}: could not read file: {e}") from e
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

        Atomic: all files are parsed into a staging dict before the cache is
        replaced. A failure during any single-file load raises
        TemplateValidationError and the cache remains in its previous state.

        Duplicate ids across YAML files raise TemplateValidationError —
        silently overwriting a previously-loaded template would mask a
        real authoring bug.
        """
        staging: dict[str, TemplateSchema] = {}
        duplicate_origin: dict[str, str] = {}  # id -> filename that first defined it

        for path in sorted(directory.glob("*.yaml")):
            template = cls._load_single(path)
            if template.id in staging:
                raise TemplateValidationError(
                    f"{path.name}: duplicate template id {template.id!r} "
                    f"(first defined in {duplicate_origin[template.id]})"
                )
            staging[template.id] = template
            duplicate_origin[template.id] = path.name

        # Atomic replace — only reached if every file parsed cleanly.
        cls._cache = staging

    @classmethod
    def get(cls, template_id: str) -> TemplateSchema:
        """Return the cached template or raise TemplateNotFoundError."""
        if template_id not in cls._cache:
            raise TemplateNotFoundError(template_id)
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
        """Replace the cache with templates from ``directory`` atomically.

        Unlike a naive ``clear() + load_dir()``, this method only mutates
        ``cls._cache`` if every YAML in the directory parses cleanly. A
        broken file (e.g. mid-edit save from the Phase-7 editor) raises
        TemplateValidationError and the cache stays on the previous valid
        set.
        """
        cls.load_dir(directory)  # load_dir is now atomic — same semantics

    @classmethod
    async def seed_db(cls, session: object) -> int:
        """Idempotent YAML-to-DB upsert: convert every cached TemplateSchema
        to a ``Template`` row with ``source='seed'`` and call
        ``templates_repo.upsert_seed``.

        Mapping (TemplateSchema → Template column):

        ============== =====================================================
        schema.id      Template.key — stable identifier
        schema.name    Template.name
        schema.app     Template.app (None for generic templates)
        schema.tape_mm Template.tape_width_mm
        schema.schema_version Template.schema_version
        schema.printer_model or "pt-series"
                       Template.printer_model — YAML value takes precedence,
                       falls back to "pt-series" for backward-compat
        schema.model_dump() Template.definition — serialised body
        ============== =====================================================

        User-created templates (``source='user'``) are never overwritten;
        the repository guarantees that contract.

        Returns the count of rows inserted or updated.
        """

        from app.models.template import Template
        from app.repositories import templates as templates_repo

        rows: list[Template] = [
            Template(
                key=schema.id,
                name=schema.name,
                app=schema.app,
                printer_model=(schema.printer_model or "pt-series"),
                tape_width_mm=schema.tape_mm,
                schema_version=schema.schema_version,
                definition=schema.model_dump(),
                source="seed",
            )
            for schema in cls._cache.values()
        ]

        return await templates_repo.upsert_seed(
            session,  # type: ignore[arg-type]
            rows,
        )
