"""Tests for TemplateLoader — YAML parsing + registry validation."""

from collections.abc import Iterator
from pathlib import Path
from textwrap import dedent

import pytest
from app.integrations.registry import IntegrationRegistry
from app.schemas.label_data import LabelData
from app.services.template_loader import (
    TemplateLoader,
    TemplateValidationError,
)


class _StubPlugin:
    def __init__(self, name: str) -> None:
        self.name = name
        self.display_name = name.title()

    async def lookup(self, identifier: str) -> LabelData:
        raise NotImplementedError


@pytest.fixture(autouse=True)
def _populate_registry() -> Iterator[None]:
    """Each test starts with snipeit/spoolman/grocy registered."""
    IntegrationRegistry._plugins.clear()
    TemplateLoader._cache.clear()
    IntegrationRegistry.register(_StubPlugin("snipeit"))
    IntegrationRegistry.register(_StubPlugin("spoolman"))
    IntegrationRegistry.register(_StubPlugin("grocy"))
    yield
    IntegrationRegistry._plugins.clear()
    TemplateLoader._cache.clear()


def _write_yaml(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(dedent(body).lstrip())
    return p


def test_load_single_parses_valid_yaml(tmp_path: Path) -> None:
    """Happy path — well-formed YAML with a known integration."""
    path = _write_yaml(
        tmp_path,
        "x.yaml",
        """
        schema_version: 1
        id: x
        name: X
        app: snipeit
        tape_mm: 24
        elements:
          - { type: qr, x: 0, y: 0, size: 100, data_field: qr_payload }
    """,
    )
    template = TemplateLoader._load_single(path)
    assert template.id == "x"
    assert template.app == "snipeit"
    assert len(template.elements) == 1


def test_load_single_accepts_app_null_for_generic_template(tmp_path: Path) -> None:
    """Generic templates have app: null and skip the registry check."""
    path = _write_yaml(
        tmp_path,
        "qr-only.yaml",
        """
        schema_version: 1
        id: qr-only
        name: QR only
        app: null
        tape_mm: 24
        elements:
          - { type: qr, x: 0, y: 0, size: 100, data_field: qr_payload }
    """,
    )
    template = TemplateLoader._load_single(path)
    assert template.app is None


def test_load_single_rejects_non_mapping_root(tmp_path: Path) -> None:
    """Top-level YAML must be a mapping (dict), not a list or string."""
    path = _write_yaml(tmp_path, "list.yaml", "- not_a_mapping\n")
    with pytest.raises(TemplateValidationError, match="must be a mapping"):
        TemplateLoader._load_single(path)


def test_load_single_rejects_invalid_yaml_syntax(tmp_path: Path) -> None:
    """Genuine YAML parse errors propagate as TemplateValidationError."""
    path = _write_yaml(tmp_path, "broken.yaml", "id: x\n  bad: indent\nname [\n")
    with pytest.raises(TemplateValidationError, match="YAML parse error"):
        TemplateLoader._load_single(path)


def test_load_single_rejects_missing_required_fields(tmp_path: Path) -> None:
    """Missing required field surfaces the Pydantic ValidationError detail."""
    path = _write_yaml(
        tmp_path,
        "incomplete.yaml",
        """
        schema_version: 1
        id: x
        name: X
    """,
    )
    with pytest.raises(TemplateValidationError, match="schema validation failed"):
        TemplateLoader._load_single(path)


def test_load_single_rejects_unknown_integration(tmp_path: Path) -> None:
    """An app value not in IntegrationRegistry fails with a helpful message."""
    path = _write_yaml(
        tmp_path,
        "future.yaml",
        """
        schema_version: 1
        id: future
        name: Future
        app: not_a_real_integration
        tape_mm: 24
        elements: []
    """,
    )
    with pytest.raises(
        TemplateValidationError, match=r"unknown integration 'not_a_real_integration'"
    ):
        TemplateLoader._load_single(path)


def test_load_dir_caches_all_templates(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path,
        "a.yaml",
        """
        schema_version: 1
        id: a
        name: A
        app: snipeit
        tape_mm: 24
        elements: []
    """,
    )
    _write_yaml(
        tmp_path,
        "b.yaml",
        """
        schema_version: 1
        id: b
        name: B
        app: grocy
        tape_mm: 18
        elements: []
    """,
    )

    TemplateLoader.load_dir(tmp_path)
    assert sorted(TemplateLoader._cache) == ["a", "b"]


def test_load_dir_raises_on_first_bad_file(tmp_path: Path) -> None:
    """Strict failure — shipping broken seed YAML is a build-time bug."""
    _write_yaml(
        tmp_path,
        "good.yaml",
        """
        schema_version: 1
        id: good
        name: Good
        app: snipeit
        tape_mm: 24
        elements: []
    """,
    )
    _write_yaml(tmp_path, "bad.yaml", "this is not yaml: [unclosed\n")

    with pytest.raises(TemplateValidationError, match=r"bad\.yaml"):
        TemplateLoader.load_dir(tmp_path)


def test_load_dir_ignores_non_yaml_files(tmp_path: Path) -> None:
    """README.md or .gitkeep next to YAMLs are not loaded."""
    _write_yaml(
        tmp_path,
        "a.yaml",
        """
        schema_version: 1
        id: a
        name: A
        app: snipeit
        tape_mm: 24
        elements: []
    """,
    )
    (tmp_path / "README.md").write_text("not yaml")
    (tmp_path / ".gitkeep").write_text("")

    TemplateLoader.load_dir(tmp_path)
    assert list(TemplateLoader._cache) == ["a"]


def test_get_returns_cached_template(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path,
        "a.yaml",
        """
        schema_version: 1
        id: a
        name: A
        app: snipeit
        tape_mm: 24
        elements: []
    """,
    )
    TemplateLoader.load_dir(tmp_path)
    assert TemplateLoader.get("a").id == "a"


def test_get_raises_keyerror_for_unknown_id(tmp_path: Path) -> None:
    TemplateLoader.load_dir(tmp_path)  # empty dir
    with pytest.raises(KeyError, match="not loaded"):
        TemplateLoader.get("nope")


def test_all_returns_shallow_copy(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path,
        "a.yaml",
        """
        schema_version: 1
        id: a
        name: A
        app: snipeit
        tape_mm: 24
        elements: []
    """,
    )
    TemplateLoader.load_dir(tmp_path)
    snapshot = TemplateLoader.all()
    snapshot.clear()
    assert list(TemplateLoader._cache) == ["a"]


def test_by_app_filters_to_matching_templates(tmp_path: Path) -> None:
    for spec_id, app in [("a", "snipeit"), ("b", "snipeit"), ("c", "grocy"), ("d", None)]:
        app_yaml = "null" if app is None else app
        _write_yaml(
            tmp_path,
            f"{spec_id}.yaml",
            f"""
            schema_version: 1
            id: {spec_id}
            name: {spec_id.upper()}
            app: {app_yaml}
            tape_mm: 24
            elements: []
        """,
        )
    TemplateLoader.load_dir(tmp_path)

    snipeit_templates = TemplateLoader.by_app("snipeit")
    assert sorted(t.id for t in snipeit_templates) == ["a", "b"]

    generic_templates = TemplateLoader.by_app(None)
    assert [t.id for t in generic_templates] == ["d"]


def test_reload_clears_cache_then_loads_fresh(tmp_path: Path) -> None:
    """reload(dir) discards old entries and reads the directory anew."""
    initial = _write_yaml(
        tmp_path,
        "a.yaml",
        """
        schema_version: 1
        id: a
        name: Original
        app: snipeit
        tape_mm: 24
        elements: []
    """,
    )
    TemplateLoader.load_dir(tmp_path)
    assert TemplateLoader.get("a").name == "Original"

    initial.write_text(
        dedent("""
        schema_version: 1
        id: a
        name: Updated
        app: snipeit
        tape_mm: 24
        elements: []
    """).lstrip()
    )
    _write_yaml(
        tmp_path,
        "b.yaml",
        """
        schema_version: 1
        id: b
        name: B
        app: grocy
        tape_mm: 18
        elements: []
    """,
    )

    TemplateLoader.reload(tmp_path)

    assert TemplateLoader.get("a").name == "Updated"
    assert sorted(TemplateLoader._cache) == ["a", "b"]


def test_reload_removes_stale_entries(tmp_path: Path) -> None:
    """A file that disappears between loads is dropped from the cache."""
    p = _write_yaml(
        tmp_path,
        "a.yaml",
        """
        schema_version: 1
        id: a
        name: A
        app: snipeit
        tape_mm: 24
        elements: []
    """,
    )
    TemplateLoader.load_dir(tmp_path)
    assert "a" in TemplateLoader._cache

    p.unlink()
    TemplateLoader.reload(tmp_path)
    assert "a" not in TemplateLoader._cache


def test_load_single_wraps_oserror_in_template_validation_error(tmp_path: Path) -> None:
    """OSError from path.read_text() must be wrapped, not propagated raw."""
    # File doesn't exist — read_text raises FileNotFoundError (a subclass of OSError)
    missing = tmp_path / "does-not-exist.yaml"
    with pytest.raises(TemplateValidationError, match="could not read file"):
        TemplateLoader._load_single(missing)


def test_load_dir_atomic_on_failure_keeps_previous_cache(tmp_path: Path) -> None:
    """A failure in any file leaves the cache exactly as it was before the call."""
    # First, populate the cache with a known-good template
    _write_yaml(
        tmp_path,
        "good.yaml",
        """
        schema_version: 1
        id: good
        name: Good
        app: snipeit
        tape_mm: 24
        elements: []
    """,
    )
    TemplateLoader.load_dir(tmp_path)
    snapshot = dict(TemplateLoader._cache)

    # Add a broken sibling and try to reload
    _write_yaml(tmp_path, "bad.yaml", "this is not yaml: [unclosed\n")

    with pytest.raises(TemplateValidationError):
        TemplateLoader.load_dir(tmp_path)

    # Cache is the pre-call snapshot — `good` is still loaded
    assert dict(TemplateLoader._cache) == snapshot
    assert "good" in TemplateLoader._cache


def test_load_dir_rejects_duplicate_ids(tmp_path: Path) -> None:
    """Two YAMLs declaring the same id must fail loudly."""
    _write_yaml(
        tmp_path,
        "a.yaml",
        """
        schema_version: 1
        id: duplicate
        name: First
        app: snipeit
        tape_mm: 24
        elements: []
    """,
    )
    _write_yaml(
        tmp_path,
        "b.yaml",
        """
        schema_version: 1
        id: duplicate
        name: Second
        app: grocy
        tape_mm: 18
        elements: []
    """,
    )

    with pytest.raises(TemplateValidationError, match=r"duplicate template id 'duplicate'"):
        TemplateLoader.load_dir(tmp_path)

    # Neither got into the cache — the failure happens during the staging loop
    assert "duplicate" not in TemplateLoader._cache


def test_reload_preserves_cache_on_failure(tmp_path: Path) -> None:
    """reload() on a directory with a broken file leaves the previous cache intact."""
    _write_yaml(
        tmp_path,
        "a.yaml",
        """
        schema_version: 1
        id: a
        name: A
        app: snipeit
        tape_mm: 24
        elements: []
    """,
    )
    TemplateLoader.load_dir(tmp_path)
    assert "a" in TemplateLoader._cache

    # Add a broken YAML; reload must fail without wiping the cache
    _write_yaml(tmp_path, "broken.yaml", "this is not yaml: [unclosed\n")

    with pytest.raises(TemplateValidationError):
        TemplateLoader.reload(tmp_path)

    # Previous cache is intact
    assert "a" in TemplateLoader._cache
