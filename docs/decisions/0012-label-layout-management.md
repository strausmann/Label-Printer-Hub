# 0012 — Label layouts are first-class, integration-scoped, and multi-instance

- **Status:** Accepted
- **Date:** 2026-05-10
- **Deciders:** maintainer

## Context

Each label has a **layout** — a recipe describing how the label is rendered onto the tape: which fields appear, where, in what font size, with QR code or not, with which margins. Different integrations (Snipe-IT, Grocy, Spoolman) have different fields available, so they need different layouts. Different *use cases within an integration* (e.g. "long form asset tag with serial" vs. "minimal box label") also need different layouts.

The maintainer's requirements (verbatim):

> When you build label layouts, we should save which integration this layout is for and how it looks when printed. We should be able to save several layouts and use them when sending a print job.

The MVP plan originally hard-coded six default layouts (3 integrations × 2 tape sizes). That doesn't satisfy the maintainer's "multiple layouts, user-selectable per print job" requirement.

## Decision

Layouts are **first-class persisted entities** with these properties:

| Field | Purpose |
|---|---|
| `id` | UUID, internal reference |
| `name` | Human-readable label, unique within integration |
| `integration` | Which integration's data shape this layout consumes (`snipeit` / `grocy` / `spoolman` / `manual`) |
| `tape_mm` | Tape width this layout is designed for |
| `printer_model_filter` | Optional restriction (e.g. only PT-Series, or only QL-820) |
| `is_default` | Whether this is the default layout for its `(integration, tape_mm)` combination |
| `is_seed` | True for ones we ship; false for user-created (seed layouts cannot be deleted, only disabled) |
| `definition` | JSON spec: list of elements `{type, x, y, width, height, field, font_size, ...}` |
| `preview_png` | Cached rendered preview, regenerated when `definition` changes |
| `created_at`, `updated_at` | Timestamps |

**Multiple layouts per integration are supported.** Per `(integration, tape_mm)` exactly one is `is_default=true`; the rest are alternatives the user picks at print time.

**Layout selection at print time:**

1. Pull mode (UI): user picks integration + tape, sees a dropdown of compatible layouts (default highlighted), can override
2. Push mode (Grocy webhook): hub uses the integration's default for the tape size in `DEFAULT_TAPE_*` env var unless the webhook payload includes `layout_id`
3. API submission: caller may pass `layout_id` in the request body; otherwise default applies

**Editing layouts is post-MVP** (issue [#17](https://github.com/strausmann/label-printer-hub/issues/17) — visual layout editor). MVP ships with editable JSON definitions through the API and seeds 6-8 sensible defaults; the editor comes later.

**Element types** (extendable per integration):

| Type | Fields |
|---|---|
| `text` | `field`, `font_size`, `align`, `bold`, `truncate` |
| `qr` | `field` (data source), `size`, `error_correction` |
| `barcode` | `field`, `size`, `format` (Code128, EAN13, …) |
| `static_text` | `value`, `font_size`, … (constant, e.g. organisation prefix) |
| `image` | `src` (URL or data:), `width`, `height` |

`field` is a dotted path resolved against the `LabelData` payload from the integration (e.g. `title`, `primary_id`, `secondary[0]`, `qr_payload`, or integration-specific extras like `snipeit.serial`, `grocy.barcode`, `spoolman.filament.material`).

## Options considered

### Option A — First-class layouts, integration-scoped, user-selectable (chosen)
- Pros: matches maintainer's stated requirement; clean data model; allows user customisation; supports per-print override; persistence survives restarts
- Cons: more storage and UI than hard-coded layouts; default-flag bookkeeping per `(integration, tape_mm)` pair

### Option B — Hard-coded layouts in code only
- Pros: simplest implementation
- Cons: fails the requirement; users can't save custom layouts; changes need a code release

### Option C — Layouts stored as Jinja or Go templates
- Pros: huge expressive power; can do anything
- Cons: massive overkill; security implications (template injection); much harder to render a preview reliably

### Option D — Per-printer layouts (no integration scoping)
- Pros: simpler tagging
- Cons: doesn't model the actual relationship — Snipe-IT data and Grocy data have totally different shapes; a "Snipe-IT 24mm" layout makes no sense for a Grocy product

## Consequences

- **DB schema** adds a `layouts` table (and migrates the previous `templates` table → `layouts`):
  ```sql
  CREATE TABLE layouts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    integration TEXT NOT NULL,        -- snipeit | grocy | spoolman | manual
    tape_mm INTEGER NOT NULL,
    printer_model_filter TEXT,        -- nullable, e.g. "PT-*" or "QL-820NWB"
    is_default INTEGER NOT NULL DEFAULT 0,
    is_seed INTEGER NOT NULL DEFAULT 0,
    is_disabled INTEGER NOT NULL DEFAULT 0,
    definition TEXT NOT NULL,         -- JSON
    preview_png BLOB,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (integration, name)
  );
  CREATE INDEX idx_layouts_integration_tape ON layouts(integration, tape_mm, is_disabled);
  CREATE UNIQUE INDEX idx_layouts_default ON layouts(integration, tape_mm) WHERE is_default = 1;
  ```
- **API endpoints**:
  - `GET /api/layouts` — list, filter by `integration`, `tape_mm`, `printer_model`
  - `GET /api/layouts/{id}` — single
  - `GET /api/layouts/{id}/preview` — sample render (uses synthetic data so the preview is always meaningful)
  - `POST /api/layouts` — create custom layout
  - `PUT /api/layouts/{id}` — update (forbidden on `is_seed=true`)
  - `POST /api/layouts/{id}/set-default` — change default for `(integration, tape_mm)`; atomically clears the previous default
  - `DELETE /api/layouts/{id}` — soft-delete (sets `is_disabled=true`); seeds can't be hard-deleted
  - `POST /api/print/{printer}` accepts optional `layout_id` parameter
- **Seed layouts** ship at startup if missing — covers the common cases:
  - `snipeit-asset-12mm` (default), `snipeit-asset-24mm` (default), `snipeit-asset-with-serial-24mm`
  - `grocy-product-12mm` (default), `grocy-product-24mm` (default), `grocy-location-12mm`
  - `spoolman-spool-12mm` (default), `spoolman-spool-with-vendor-24mm` (default)
- **Webhook-payload extension**: Grocy/Spoolman API accepts optional `layout_id` to override the default
- **UI in the printer's tab**: a layout dropdown appears next to the tape selector, populated from the active integration's available layouts
- **Tests** cover: unique-default invariant, seed re-seeding on missing, disabled vs. deleted distinction, preview-cache invalidation on definition change

## References

- Issue [#17](https://github.com/strausmann/label-printer-hub/issues/17) — visual layout editor (post-MVP)
- Issue [#19](https://github.com/strausmann/label-printer-hub/issues/19) — SQLModel persistence (this ADR adds to that schema)
- Wiki page: [Snipe-IT Integration](https://github.com/strausmann/label-printer-hub/wiki/Snipe-IT-Integration), [Grocy Integration](https://github.com/strausmann/label-printer-hub/wiki/Grocy-Integration), [Spoolman Integration](https://github.com/strausmann/label-printer-hub/wiki/Spoolman-Integration) — describe the data fields each layout can use
- Related: ADR 0004 (plugin architecture — layout's `printer_model_filter` references plugin model_id), ADR 0011 (OpenAPI — layout schema is part of the contract)
