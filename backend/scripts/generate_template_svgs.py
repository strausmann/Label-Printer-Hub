"""Generate SVG samples for every seed template under docs/.

Run with:
    cd backend && uv run python scripts/generate_template_svgs.py

Writes one ``{template-id}.svg`` per seed template that contains a
``preview_sample`` block into:
    docs/site/operations/templates/svg-samples/

These SVGs are the visual basis for the Phase 7e layout-system brainstorming
(GitHub issue #81).  They are pure-vector: text is rendered as ``<text>``
elements, QR codes as ``<path>`` elements — no raster embeds.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

# Ensure the project root is on sys.path so ``app.*`` imports work when the
# script is executed directly via ``uv run python scripts/…`` from the
# ``backend/`` directory.
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.services.svg_renderer import render_template_svg  # noqa: E402

SEED_DIR = _BACKEND_DIR / "app" / "seed" / "templates"
OUT_DIR = _BACKEND_DIR.parent / "docs" / "site" / "operations" / "templates" / "svg-samples"


def main() -> int:
    """Generate one SVG per seed template that has a preview_sample.

    Returns:
        0 on success, 1 if any template lacks a preview_sample (counted as a
        warning, not a failure).
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    skipped: list[str] = []

    for yaml_file in sorted(SEED_DIR.glob("*.yaml")):
        definition: dict[str, object] = yaml.safe_load(yaml_file.read_text())
        sample = definition.get("preview_sample")
        if not sample:
            print(f"SKIP  {yaml_file.name}: no preview_sample")  # noqa: T201
            skipped.append(yaml_file.name)
            continue

        template_id = str(definition.get("id", yaml_file.stem))
        svg = render_template_svg(definition, dict(sample))  # type: ignore[arg-type]
        out_path = OUT_DIR / f"{template_id}.svg"
        out_path.write_text(svg, encoding="utf-8")
        written.append(out_path)
        print(f"WROTE {out_path}")  # noqa: T201

    print()  # noqa: T201
    print(f"Done: {len(written)} SVG(s) written, {len(skipped)} skipped.")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
