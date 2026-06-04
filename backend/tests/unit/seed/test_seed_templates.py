"""Smoke tests: every shipped seed template parses and renders.

This is the build-time safety net — if a YAML in app/seed/templates/
breaks any contract (schema, registry, geometry, renderer), this
suite fails before the PR can merge.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from app.integrations.registry import IntegrationRegistry
from app.schemas.label_data import LabelData
from app.services.label_renderer import (
    DEFAULT_LABEL_WIDTH_PX,
    TAPE_HEIGHT_PX,
    LabelRenderer,
)
from app.services.template_loader import TemplateLoader

SEED_DIR = Path(__file__).parent.parent.parent.parent / "app" / "seed" / "templates"
EXPECTED_IDS = {
    "grocy-12mm",
    "grocy-18mm",
    "grocy-24mm",
    "hangar-furniture-12mm",
    "hangar-furniture-18mm",
    "hangar-furniture-24mm",
    "qr-only-12mm",
    "qr-only-18mm",
    "qr-only-24mm",
    "samla-deckel-12mm",
    "samla-deckel-24mm",
    "samla-deckel-62mm",
    "samla-stirntag-12mm",
    "samla-stirntag-24mm",
    "samla-stirntag-62mm",
    "snipeit-12mm",
    "snipeit-18mm",
    "snipeit-24mm",
    "spoolman-12mm",
    "spoolman-18mm",
    "spoolman-24mm",
}


class _StubPlugin:
    def __init__(self, name: str) -> None:
        self.name = name
        self.display_name = name.title()

    async def lookup(self, identifier: str) -> LabelData:
        raise NotImplementedError


@pytest.fixture(autouse=True)
def _populate_registry() -> Iterator[None]:
    IntegrationRegistry._plugins.clear()
    TemplateLoader._cache.clear()
    for name in ["snipeit", "spoolman", "grocy"]:
        IntegrationRegistry.register(_StubPlugin(name))
    TemplateLoader.load_dir(SEED_DIR)
    yield
    IntegrationRegistry._plugins.clear()
    TemplateLoader._cache.clear()


@pytest.fixture
def dummy_data() -> LabelData:
    return LabelData(
        title="Example",
        primary_id="HH-AK-BY01",
        qr_payload="https://example.test/asset/123",
        source_app="snipeit",
        secondary=("S/N: 1234", "Loc: Office"),
    )


def test_all_expected_templates_are_loaded() -> None:
    """The shipped set is exactly the 21 templates the spec calls for.

    15 original templates + 6 new Samla templates (Phase 1i Task 10):
    samla-stirntag-{12,24,62}mm and samla-deckel-{12,24,62}mm.
    """
    assert set(TemplateLoader.all()) == EXPECTED_IDS


@pytest.mark.parametrize("template_id", sorted(EXPECTED_IDS))
def test_each_template_renders_with_dummy_label_data(
    template_id: str, dummy_data: LabelData
) -> None:
    """Every shipped template must produce a 1-bit PIL image without raising."""
    template = TemplateLoader.get(template_id)
    image = LabelRenderer().render(template, dummy_data)
    assert image.mode == "1"
    # Height (tape axis) is pin-locked; width may be trimmed to inked content.
    assert image.height == TAPE_HEIGHT_PX[template.tape_mm]
    assert 1 <= image.width <= DEFAULT_LABEL_WIDTH_PX
