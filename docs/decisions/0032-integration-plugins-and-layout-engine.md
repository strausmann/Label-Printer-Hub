<!--
SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# 0032 — Integrations are entry-point plugins; a label is a content type drawn by the layout engine

- **Status:** Accepted
- **Accepted:** 2026-11-21 — shipped with PR #109 (Phase 1k.1a, 2026-06-06) and in use since; written down after the fact by the ADR audit of 2026-11-21
- **Date:** 2026-11-21
- **Deciders:** maintainer
- **Supersedes:** [0012](0012-label-layout-management.md) (label layouts as stored, integration-scoped records; never built)
- **Related:** [0004](0004-plugin-architecture-for-printer-models.md) (entry-point discovery), [0023](0023-sheet-archive.md) (sheet cells)

## Context

ADR 0012 planned label layouts as first-class records: stored per integration, several per integration, chosen when a print job is sent. It was never built (#24 closed as superseded). What the hub does instead came with PR #109, which replaced 21 hand-made templates by a layout engine, and with the integration plugins for Snipe-IT, Spoolman and Grocy. Neither has an ADR, so the reason why the hub has no stored layouts, and where an integration plugs in, could only be found in code and pull requests.

Two things had to be decided. Where does knowledge of an external app live, so that a new integration does not touch the print path? And what describes a label, so that one description prints on every tape width and in a sheet cell?

## Decision

**An integration is a plugin that turns an identifier of its app into label data; a label is described by a content type and the data, and the layout engine computes the drawing for the loaded tape. There are no stored layouts.**

- **Integration plugins.** Each external app is a module under `backend/app/integrations/<name>/` that implements the `IntegrationPlugin` protocol (`backend/app/integrations/base.py`: `lookup(identifier) -> LabelData`, `bind`, `reconfigure`, `is_configured`). Plugins are declared in the entry-point group `label_hub.integrations` (`backend/pyproject.toml:68-71`), loaded at start, checked against the protocol and registered in `IntegrationRegistry` (`backend/app/integrations/__init__.py:41`, `backend/app/integrations/registry.py:22`). A plugin that fails to load is logged and skipped. The print path knows plugins only by name: a print request carries either raw `data` or `lookup: {app, identifier}`, exactly one of them (`backend/app/schemas/print_request.py:92-118`), and `lookup_service` resolves the lookup through the registry (`backend/app/services/lookup_service.py:130-135`).
- **Content type, not layout.** A `ContentType` says what a label shows (QR only, QR with one to three lines, text lines, QR with a listing; `backend/app/schemas/content_type.py`), independent of the tape. Each content type has its required fields (`REQUIRED_FIELDS`, `backend/app/services/layout_engine.py:40`); data that lacks them is refused with `ContentTypeDataMismatchError` (422).
- **The layout engine draws it.** `LayoutEngine` (`backend/app/services/layout_engine.py`) renders tape width, content type and data into an image; pixel positions come from the tape geometry table `TAPE_GEOMETRY` (`backend/app/schemas/tape_geometry.py:58`), not from the content type. Per-print options choose orientation and, for 62 mm QL tape, a layout preset (`PrintOptions`, `print_request.py`; #258).
- **Sheet cells use the same contract.** The sheet cell renderer is a separate, swappable implementation, but it accepts the same content types and required fields as the tape engine (`backend/app/sheets/cell_render.py:6-13`).
- **No stored layouts.** Presets (`backend/app/models/preset.py`) store field values for a printer, not a layout.

## Options considered

### Option A — integration plugins plus content types and one layout engine (chosen)
- Pros: one description prints on every tape width and in sheet cells; a new tape width is a row in the geometry table, not a new template per layout; a new integration is one plugin and one entry point, with no change to the print path.
- Cons: the set of label shapes is fixed in code; a new shape is a new content type and engine code, not a user setting.

### Option B — stored, integration-scoped layouts (ADR 0012)
- Pros: users could design and keep their own layouts per integration.
- Cons: every layout has to work on every tape width; the 21 templates PR #109 replaced showed how quickly such a set drifts; a layout editor and its storage were never built.

### Option C — templates per tape width and use case
- Pros: full control over each label.
- Cons: the number of templates grows with tapes times uses; this is what PR #109 removed.

## Consequences

- ADR 0012 is superseded by this ADR; its header points here.
- Adding a label shape is a code change (content type, required fields, engine method, sheet renderer), reviewed like any other.
- An integration plugin from another package can register through the same entry-point group (ADR 0004, amendment of 2026-11-21); the project ships and tests the three bundled ones.
- The redesign of tape label rendering (#178, milestone 1.10.0) works inside this model; if it changes the model itself, it needs its own ADR.

## References

- PR #109 (layout engine), issue #24 (layout management, closed as superseded), #178 (tape rendering redesign, open), #258 (QL layout per tape width)
- Code: `backend/app/integrations/`, `backend/app/schemas/content_type.py`, `backend/app/services/layout_engine.py`, `backend/app/schemas/tape_geometry.py`, `backend/app/sheets/cell_render.py`
- Related ADRs: [0012](0012-label-layout-management.md) (superseded), [0004](0004-plugin-architecture-for-printer-models.md), [0023](0023-sheet-archive.md)
