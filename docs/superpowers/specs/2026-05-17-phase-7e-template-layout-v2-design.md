# Phase 7e Foundation Design — Template Layout System v2

**Date:** 2026-05-17
**Status:** Draft
**Tracking:** strausmann/label-printer-hub#22 (master), #81 (Phase 7e)
**Dependencies:**
- Phase 4 first-print renderer (existing PIL-based pipeline) is reused; only the *template authoring model* and *element-positioning logic* change
- Phase 7c (#78) NOT required — layout system is independent of auth
- SVG samples PR #83 provides the visual reference for v1 layouts as discussion-anchor for the v2 design

## 1. Executive Summary

Phase 7e replaces the current template schema (absolute pixel coordinates per element) with a **semantic layout system v2**:

- v1: template authors compute pixel coordinates by hand for every tape width (`{type: text, x: 100, y: 60, font_size: 14, field: title}`)
- v2: template authors declare *intent* (`layout: qr-left-text-right`, `text_lines: [{field: primary_id, font_size: 22}]`); the renderer computes positions, QR size, line spacing automatically per tape width

**Three canonical layouts in v2:**

| Layout | Use case | Renderer behavior |
|---|---|---|
| `qr-left-text-right` | 1-N text lines next to a single QR | QR fills the height of all text lines; text right-aligned to QR with constant gap |
| `qr-only` | No-text labels (compact QR identifier) | QR fills the full printable height |
| `qr-with-listing` | Aggregation: one big label with N child items (e.g. Kallax-Regal-Overview showing all 4 compartments) | QR left, item list right with each entry on its own line |

**Hard cut from v1:** TemplateLoader reads ONLY v2 (no backward-compat code path). All 12 seed templates are rewritten in v2 form in this phase. User-provided v1 templates (currently none exist in production) need manual migration; documented in the operator guide.

**Renderer auto-derives constants** (paddings, font line-heights, QR-to-text gap) from `tape_mm` and the number of text lines. Templates don't override these — guarantees visual consistency across all templates.

The Phase 7e implementation lives in the existing label-printer-hub backend; no new service or dependency required.

## 2. Schema v2 Specification

### Pydantic model

```python
# backend/app/schemas/template_v2.py

from typing import Literal, Annotated
from pydantic import BaseModel, ConfigDict, Field


class TextLineV2(BaseModel):
    """A single text line in a qr-left-text-right or qr-with-listing layout."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str                    # LabelData attribute name (e.g. "primary_id", "title")
    font_size: int = Field(default=18, ge=8, le=72)
    weight: Literal["normal", "bold"] = "normal"


class QrSpec(BaseModel):
    """QR-code element configuration."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    data_field: str               # LabelData attribute name (typically "qr_payload")
    ecc_level: Literal["L", "M", "Q", "H"] = "M"   # Error correction


class TemplateSchemaV2(BaseModel):
    """Phase 7e Template Schema v2 — semantic layout, renderer computes positions."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[2]
    id: str                       # Unique template key, e.g. "grocy-12mm"
    name: str                     # User-facing display name
    app: str | None               # Plugin name (grocy, snipeit, spoolman, hangar) or None for generic
    tape_mm: Literal[12, 18, 24]  # Brother P-Touch tape widths supported

    layout: Literal["qr-left-text-right", "qr-only", "qr-with-listing"]

    qr: QrSpec                    # Always required (all 3 layouts use a QR)
    text_lines: tuple[TextLineV2, ...] = ()       # Empty for qr-only; 1-4 entries for qr-left-text-right; treated as line-template for qr-with-listing
    listing_field: str | None = None              # Required when layout="qr-with-listing" — the LabelData field that holds the list of child items (e.g. "compartments")

    preview_sample: dict[str, str | int | float | bool | tuple[str, ...]] | None = None
```

### Validation

Pydantic validators enforce:

| Rule | Validates |
|---|---|
| `qr-only` → text_lines MUST be empty | `qr-left-text-right` and `qr-with-listing` MUST have at least 1 text_line |
| `qr-with-listing` → listing_field MUST be set | other layouts → listing_field MUST be None |
| `text_lines` ≤ 4 | hardware fits 4 lines max on 24mm tape, less on 12mm/18mm |
| Each `text_line.field` and `qr.data_field` must reference a valid `LabelData` attribute | reject otherwise with 422 + clear message |

### Why `tuple` over `list`

Phase 7d already established tuple-based sequence types so the frozen schema is deeply immutable. Same pattern here for `text_lines` + `preview_sample.*.tuple_values`.

## 3. Renderer-Computed Geometry

The new renderer module (`backend/app/services/label_renderer_v2.py`) computes pixel positions deterministically from `tape_mm` and `text_lines` count.

### Constants table

```python
# Brother PT @ 180 DPI — physical tape heights in pixels
TAPE_HEIGHT_PX = {12: 106, 18: 165, 24: 256}

# Per-tape paddings and gaps (all in pixels)
LAYOUT_CONSTANTS = {
    12: {
        "tape_padding_x": 6,       # Left/right edge padding
        "tape_padding_y": 4,       # Top/bottom edge padding
        "qr_text_gap": 8,          # Horizontal gap between QR and first text column
        "line_spacing": 4,         # Vertical gap between adjacent text lines
        "max_text_lines": 2,       # Practical limit on 12mm
    },
    18: {
        "tape_padding_x": 8,
        "tape_padding_y": 6,
        "qr_text_gap": 10,
        "line_spacing": 6,
        "max_text_lines": 3,
    },
    24: {
        "tape_padding_x": 10,
        "tape_padding_y": 8,
        "qr_text_gap": 12,
        "line_spacing": 8,
        "max_text_lines": 4,
    },
}
```

### Layout computation per type

**`qr-left-text-right`:**
1. Available tape height = `TAPE_HEIGHT_PX[tape_mm] - 2 * tape_padding_y`
2. Text-block height = `sum(line.font_size for line in text_lines) + line_spacing * (len(text_lines) - 1)`
3. QR size = `min(text_block_height, available_tape_height)` — QR is square; its height matches the text block (or the tape if text would overflow — validation prevents that)
4. QR position: `(tape_padding_x, (tape_height - qr_size) // 2)` — vertically centered
5. Text-block X start: `tape_padding_x + qr_size + qr_text_gap`
6. First text line Y: `(tape_height - text_block_height) // 2 + first_line.font_size` — baseline of first line, centered vertically

**`qr-only`:**
1. QR size = `available_tape_height` (full height minus paddings)
2. QR position: `(tape_padding_x, tape_padding_y)` — left-aligned, top-padded
3. No text rendering

**`qr-with-listing`:**
1. Same as `qr-left-text-right` for QR positioning
2. Text-block instead repeats the single `text_lines[0]` template for each item in `LabelData.{listing_field}`
3. Item rendering: e.g. for `listing_field="compartments"` with `LabelData.compartments = ["A", "B", "C", "D"]`, renders 4 lines using the template's font_size + spacing
4. If items would overflow available height, render as many fit + add "(+N more)" indicator at the bottom

### Why auto-derive

- Visual consistency: all 12mm templates look the same — same paddings, same font baseline alignment
- Author simplicity: no pixel math, just declare layout + data fields
- Future-proofing: when 36mm tape support is added, only the constants table grows; no per-template migration

If a user later wants overrides (e.g. larger paddings for a specific template), Phase 7e.1 can add `layout_overrides: dict | None`. For 7e, no overrides — strict consistency wins.

## 4. Migration Plan — 12 Seed Templates

All 12 seed templates in `backend/app/seed/templates/*.yaml` get rewritten in v2 form. Mapping:

| v1 file | v2 layout | text_lines | listing_field |
|---|---|---|---|
| `grocy-12mm.yaml` | qr-left-text-right | primary_id (22), title (14) | — |
| `grocy-18mm.yaml` | qr-left-text-right | primary_id (28), title (18), secondary line (14) | — |
| `grocy-24mm.yaml` | qr-left-text-right | primary_id (32), title (22), 2 secondary (14) | — |
| `snipeit-{12,18,24}mm.yaml` | qr-left-text-right | same as grocy | — |
| `spoolman-{12,18,24}mm.yaml` | qr-left-text-right | same | — |
| `qr-only-{12,18,24}mm.yaml` | qr-only | (empty) | — |

**New aggregation templates seeded in this phase** (3 new files, one per tape width):

| New file | v2 layout | text_lines (treated as item-line template) | listing_field |
|---|---|---|---|
| `kallax-regal-overview-12mm.yaml` | qr-with-listing | `[{field: item, font_size: 16}]` | `compartments` |
| `kallax-regal-overview-18mm.yaml` | qr-with-listing | `[{field: item, font_size: 20}]` | `compartments` |
| `kallax-regal-overview-24mm.yaml` | qr-with-listing | `[{field: item, font_size: 24}]` | `compartments` |

These align with the Hangar Kallax-Regal use case from Phase 7d brainstorming (one "Regal-Übersicht" label vs N "Fach"-Labels). 

### TemplateLoader changes

```python
# backend/app/services/template_loader.py — new validation
def _validate_schema_version(definition: dict) -> None:
    if definition.get("schema_version") != 2:
        raise SchemaVersionError(
            f"Template '{definition.get('id')}' has unsupported schema_version "
            f"{definition.get('schema_version')!r}. Phase 7e dropped v1 — "
            "migrate the template to v2 layout fields (layout, qr, text_lines)."
        )
```

Existing v1 templates either get rewritten as part of this PR (the 12 seed templates) or fail loud with the message above (any user templates). Migration guide in operator docs.

### Database

`templates.definition` column already holds the JSON-blob; no DB schema change needed. The `definition` JSON simply contains a different shape post-Phase-7e.

If a deployed DB has v1 templates seeded, they survive the upgrade until next seed-sync (then they get overwritten). To force-clean: operator runs `make seed-resync` (existing target) to wipe + re-seed from the new YAML files.

## 5. LabelData Extensions

For `qr-with-listing` to render item lists, `LabelData` needs a way to carry the list. Add an optional `items` field:

```python
# backend/app/schemas/label_data.py — extended

class LabelData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_id: str
    title: str
    qr_payload: str
    secondary: tuple[str, ...] = ()
    items: tuple[LabelDataItem, ...] = ()     # NEW — for qr-with-listing aggregation


class LabelDataItem(BaseModel):
    """A single child item in an aggregation label."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    item: str         # Display text (e.g. compartment label "A", "B", "C")
    qr_payload: str | None = None    # Optional: each child has its own QR payload (not rendered, future use)
```

`text_lines[0].field` for a `qr-with-listing` template references `"item"` — this resolves against `LabelDataItem.item` per child in the loop.

### Caller responsibility

For `qr-with-listing`, the caller (Hangar's Print-Page, or Label-Hub's QR-Tab with the Hangar plugin) must populate `LabelData.items` with the child list. Single-item layouts (`qr-left-text-right`, `qr-only`) ignore the `items` field entirely.

## 6. Endpoint Impact

### `/api/render/preview` and `/api/print` (added in Phase 7d)

No signature change. The renderer dispatches on `template.layout` internally.

### `/api/templates/{key}/preview` (added in Phase 7c-prior UI-fix PR)

No signature change. The route looks up `template.preview_sample`, builds `LabelData` from it (now including `items` if the template is `qr-with-listing`), passes to renderer.

`preview_sample` for aggregation templates includes the `items` list:

```yaml
preview_sample:
  primary_id: "Kallax 02"
  title: "Werkstatt"
  qr_payload: "https://hangar.example.com/locations/kallax-02"
  items:
    - {item: "A — Schrauben"}
    - {item: "B — Muttern"}
    - {item: "C — Werkzeug"}
    - {item: "D — Kabel"}
```

### Frontend changes

- `/templates/{key}` template-detail page renders the new aggregation samples correctly (no code change — preview-PNG endpoint just returns the rendered PNG, frontend already shows it)
- `/qr-print` (Phase 7d) needs awareness of aggregation templates: when a user picks `qr-with-listing` template, the form should ask for the listing data; Hangar plugin's `get_children()` directly provides this

## 7. Renderer Code Layout

```
backend/app/services/
├── label_renderer.py            # OLD — Phase 4 v1 renderer (kept for reference, removed in this PR)
├── label_renderer_v2.py         # NEW — semantic v2 renderer
│   ├── render(template, data) -> Image    # public entry point, dispatches on layout
│   ├── _render_qr_left_text_right(...)
│   ├── _render_qr_only(...)
│   ├── _render_qr_with_listing(...)
│   ├── _compute_qr_size(...)
│   └── _compute_text_block_height(...)
├── svg_renderer.py              # Phase 7e parallel: keep SVG output (PR #83) updated to v2 layouts
└── ...
```

The v1 renderer file is deleted, not just deprecated. Hard cut. References in tests and other modules are updated.

## 8. Testing Strategy

| Layer | Test type | Coverage |
|---|---|---|
| Schema validation | Unit | All Pydantic validators reject invalid combinations (e.g. qr-only with text_lines, qr-with-listing without listing_field) |
| Constants table | Unit | TAPE_HEIGHT_PX and LAYOUT_CONSTANTS have entries for all supported tape widths |
| Layout computation | Unit | Given (tape_mm=12, text_lines=2), `_compute_qr_size` returns expected px value |
| Layout `qr-left-text-right` | Render | Sample data → PIL Image with QR on left, 2 text lines on right, correct pixel positions |
| Layout `qr-only` | Render | QR fills full height, no text |
| Layout `qr-with-listing` | Render | LabelData.items=4 → 4 lines rendered; items=10 → renders as many fit + "(+N more)" tag |
| SVG renderer parity | Render | The new v2 SVG renderer produces matching layouts to the PIL renderer (both consume the same v2 template) |
| TemplateLoader rejection | Integration | v1 template (schema_version=1) → loader raises SchemaVersionError on startup, lifespan logs the affected template key |
| Seed templates | Integration | All 12 (+3 new aggregation) seed YAMLs pass v2 validation + render successfully via preview endpoint |
| End-to-end | Integration | POST /api/print with a `qr-with-listing` template + items=[A,B,C,D] → 1 print job, rendered correctly |

Coverage target `fail_under = 80`. The v2 renderer should exceed 95% line coverage given the small number of layout variants.

## 9. Documentation

New page at `docs/site/operations/templates/authoring-v2.md`:

- v2 schema overview with examples
- "How do I add a new template" walkthrough
- Layout selection guide (decision tree: do I have a QR? do I have text? is it an aggregation?)
- LabelData field reference
- Tape-width capacity table

The existing `docs/site/operations/templates/layouts.md` (PR #83 SVG samples page) gets a "Phase 7e v2 redesign — see authoring-v2.md" banner at the top.

Operator migration guide: if user templates exist (none in production today, but the path matters), the doc explains how to convert v1 absolute coordinates → v2 semantic fields.

## 10. Out-of-Scope

Explicit non-goals for Phase 7e:

- **Custom layout types beyond the 3 canonical** (no `qr-right-text-left`, no `text-only`, no `qr-top-text-bottom`) — keep the implementation focused; add later if a real use case appears
- **Per-template layout overrides** — strict consistency wins; no `layout_overrides` field
- **WYSIWYG template editor** — Phase 7f or later if the YAML editing pain becomes a thing
- **Tape widths beyond 12/18/24mm** — 36mm/6mm support is a constants-table extension once hardware demands it
- **Image elements** (logos, photos) — current renderer renders text + QR only; image elements stay deferred
- **Multi-printer-model layouts** (PT-series vs QL-series geometry differences) — current scope assumes PT-series 180-DPI tape only

## 11. Definition of Done

- [ ] `TemplateSchemaV2` Pydantic model + validators implemented
- [ ] `label_renderer_v2.py` implements all 3 layouts with PIL output
- [ ] `svg_renderer.py` updated to produce v2-layout SVGs
- [ ] `TemplateLoader` validates schema_version=2 strictly, rejects v1 with clear error
- [ ] 12 existing seed templates rewritten in v2 format
- [ ] 3 new `kallax-regal-overview-*` aggregation seed templates added
- [ ] `LabelData` extended with `items: tuple[LabelDataItem, ...]`
- [ ] Old `label_renderer.py` removed (hard cut)
- [ ] All tests passing, coverage >= 80%
- [ ] `make oapi` regenerates client if any endpoint signature changed (likely none)
- [ ] `make docs-svg-samples` produces updated SVGs for all 15 (12 + 3 new) templates
- [ ] New `docs/site/operations/templates/authoring-v2.md` operator doc
- [ ] `docs/site/operations/templates/layouts.md` updated with v2 banner
- [ ] Production smoke after deploy: render preview of each of the 15 seed templates, confirm visual correctness
- [ ] Refs #22 + Closes #81 in the PR

## 12. Self-Review

- **Privacy:** spec uses RFC 5737 / example.com placeholders consistently
- **Hard-cut rationale:** Phase 7b deploy already established that we control all template sources (12 seed templates, no user-authored ones in production). Hard cut is safe + simpler than backward-compat code.
- **Aggregation use case:** `qr-with-listing` directly supports the Hangar Kallax-Regal "drucke alle Fächer als ein Label" pattern from Phase 7d brainstorming.
- **Renderer constants vs override flexibility:** chose strict consistency over per-template overrides. Real use cases for overrides are unknown today; YAGNI.
- **Tape widths:** committed to 12/18/24mm. 36mm/6mm support is a constants-table addition; spec'd in the out-of-scope section.
