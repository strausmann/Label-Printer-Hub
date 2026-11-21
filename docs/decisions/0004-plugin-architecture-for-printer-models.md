<!--
SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# 0004 — Plugin architecture for printer models

- **Status:** Accepted
- **Amended by:** [0020](0020-backend-kinds-ipp-page-printers.md) — page printers are a separate backend kind (`ipp`), not a model plugin; this ADR still governs the Brother raster families
- **Amended:** 2026-11-21 (#413) — plugins are discovered through entry points as the hub uses them today; the rule that model code lives only in the plugins stays, see "Amendment — 2026-11-21" at the end
- **Date:** 2026-05-10
- **Deciders:** maintainer

## Context

The hub needs to support multiple Brother label-printer model families today (PT-Series and QL-Series) and ideally allow contributors to add support for additional models (more PT models, more QL models, possibly non-Brother families) without forking the project or rewriting core logic.

Models differ in: DPI (PT-Series 180, QL-Series 300), print-head pin count (128 vs 720), media types (TZe-Tape vs DK-Die-Cut), and minor status-block layout details. Models are uniformly identified by the SNMP `enterprises.2435.2.3.9.1.1.7.0` PJL string (`MFG:Brother;CMD:...;MDL:<model>;CLS:PRINTER;`).

The maintainer wants the hub to be modular: "the container is general, modules can optionally be trained for additional printer models."

## Decision

Every printer-model-specific behaviour lives in **one Python module per model family** under `backend/app/printer_models/<series>.py`, implementing the `PrinterModel` protocol from `printer_models/base.py`.

A **registry** (`printer_models/registry.py`) holds all loaded plugins. At runtime, when the hub first contacts a printer, it:

1. Reads the printer's SNMP PJL string (`enterprises.2435.2.3.9.1.1.7.0`)
2. Asks `ModelRegistry.find_by_pjl(pjl_string)` for the matching plugin
3. Uses that plugin for all subsequent operations on that printer

No model-specific logic exists outside the plugin module. `PrinterService`, `PrintQueue`, `StatusProbe`, and the API layer all interact with the abstract `PrinterModel` interface only.

## Options considered

### Option A — Plugin protocol + registry (chosen)
- Pros: matches maintainer's "modular" requirement; new models = new file + register call; easy to test in isolation; CodeQL can analyse each plugin separately; community contributions land as PRs that touch one file
- Cons: slightly more abstraction up front; registry pattern needs unit tests of its own

### Option B — One file per concern, model-specific branches inside
- Pros: simpler initially
- Cons: every new model touches several core files; merge conflicts grow; testing in isolation is harder; doesn't match maintainer's intent

### Option C — External plugin packages (entry points)
- Pros: third parties could ship pip-installable plugins
- Cons: significant overkill for the foreseeable scale; harder to package as a single container image; adds a release/distribution dimension we don't need yet

## Consequences

- Directory structure under `backend/app/printer_models/`:
  - `base.py` — `PrinterModel` Protocol + shared dataclasses (`StatusBlock`, `TapeSpec`, `PrintOptions`)
  - `registry.py` — `ModelRegistry` with `register()`, `find_by_pjl()`, `find_by_snmp_oid_value()`
  - `pt_series.py` — Brother PT-E550W, PT-P710BT, PT-P750W
  - `ql_series.py` — Brother QL-800, QL-810W, QL-820NWB
  - (future) `<other>_series.py`
- `PrinterModel` Protocol surface: `model_id`, `pjl_signatures`, `snmp_model_oid_value_substr`, `dpi`, `print_head_pins`, `query_status()`, `parse_status_block()`, `build_print_job()`, `width_to_pixels()`
- Tests: each plugin gets `tests/unit/printer_models/test_<series>.py` with mock TCP responses
- New plugin contributions: see `docs/plugin-development.md` (separate doc)
- Plugin auto-discovery on hub startup; manual override possible via env var if PJL discovery fails
- Major model behaviour changes (e.g. new tape types) bump the project's minor version (additive); breaking changes in the `PrinterModel` protocol bump major

## References

- Issue [#10](https://github.com/strausmann/label-printer-hub/issues/10) — PT-Series plugin
- Issue [#11](https://github.com/strausmann/label-printer-hub/issues/11) — QL-Series plugin
- Brother PJL identification spec: `docs/research/` (when migrated from maintainer's mono-repo)
- Related: ADR 0002 (Python backend), ADR 0006 (status sources)

## Amendment — 2026-11-21 (ADR audit, #413): entry points as used today; the rule stays

**Discovery runs through entry points.** Option C above rejected "external plugin packages (entry points)". The mechanism is in use today for the plugins the hub ships: model families, backends and integrations are entry-point groups declared in the hub's own `backend/pyproject.toml` (`label_hub.integrations` at lines 68-71, `label_hub.printer_backends` at 73-75, `label_hub.printer_models` at 77-79). They are walked once at start (lifespan step 2, `backend/app/main.py:279`; `ModelRegistry.ensure_discovered`, `backend/app/printer_models/registry.py:135`; `BackendRegistry.ensure_discovered`, `backend/app/printer_backends/__init__.py:53`; `backend/app/integrations/__init__.py:41`). A plugin that fails to load is logged and skipped. A package installed into the image that declares the same groups is loaded as well, and the plugin authoring guide says so (`website/src/content/docs/developers/plugin-authoring.md:55`); the project publishes, versions and tests no such package, so the release and distribution work Option C warned about is still not taken on. The two raster backends are chosen by the printer's `backend` value through `BackendRouter` (`backend/app/services/backend_router.py:21-22`); the backend group itself lists `mock` and `ptouch`.

**The rule "no model-specific logic exists outside the plugin module" stays and is enforced** (maintainer, 2026-11-21). It is not met yet:

- `backend/app/services/printer_model_registry.py:38-41` keeps a second model list with display texts for the admin UI. This is the open violation; #413 (milestone 1.8.0) removes it, lets the plugins report their metadata through the entry points and adds a guard test that fails on model metadata outside the plugins.
- The raster backends map model ids to their library's printer classes and carry a default model id (`backend/app/printer_backends/ptouch_backend.py:51-57,276`, `backend/app/printer_backends/brother_ql_backend.py:262`), and the test label reads that map (`backend/app/services/test_label.py:54`). These bind a backend to its library; #413 decides which of them is model metadata that belongs in the plugin.

Detection by the SNMP PJL string still works as described (`backend/app/services/printer_runtime.py:185-186`).
