<!--
SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# GitHub Copilot Instructions

These instructions apply to GitHub Copilot Chat and inline suggestions in this repository.

The full project rules live in [CLAUDE.md](../CLAUDE.md). This file is a working subset Copilot can lean on quickly.

## Stack

- **Backend:** Python 3.12+, FastAPI, SQLModel (SQLite), asyncio, ruff, mypy strict
- **Frontend:** Go web server + Tailwind CSS + HTMX + PWA (manifest, service worker, web notifications)
- **Tests:** pytest (Python), `testing` package + Playwright (Go/e2e)
- **CI:** GitHub Actions, semantic-release, Dependabot

## Repeated patterns we want to follow

Before suggesting code, skim [`docs/learnings/code-review-patterns.md`](../docs/learnings/code-review-patterns.md). It collects findings from previous AI reviews so we don't keep re-suggesting things this codebase has explicitly rejected (e.g. `list[Flag]` instead of `IntFlag`, hyphenated `workflow_dispatch` inputs, broad `except Exception` in tests).

## Mandatory conventions

1. **Conventional Commits.** Every commit message: `<type>(<scope>): <subject>`. semantic-release depends on this.

2. **Test-Driven Development.** Failing test first, then implementation.

3. **Plugin architecture for printer models.** Anything model-specific goes in `app/printer_models/<series>.py` implementing the `PrinterModel` protocol from `app/printer_models/base.py`. Never hardcode model logic elsewhere.

4. **Print queue is mandatory.** Brother printers have no built-in queue. Use `asyncio.Queue` + worker per printer. Persist jobs in SQLite.

5. **Status sources by phase:**
   - Pre-print: TCP/9100 `ESC i S` (1B 69 53) → 32-byte status block
   - Active print: passive read of automatic Brother status notifications
   - Idle dashboard: SNMP Display-OID `1.3.6.1.2.1.43.16.5.1.2.1.1`

6. **Type hints everywhere.** mypy strict on `app/`. No `Any` unless boundary.

7. **No mid-print cancel.** Brother spec forbids commands during print. Pause/cancel only from `queued` or `paused` states.

8. **Branches and PR targets.** Features (`feat`, `!`, `BREAKING CHANGE:`) branch from and target `milestone/x.y.0`; fixes, docs and CI branch from and target `main`. Never suggest a `feat` commit or PR title for `main` outside a milestone merge. Merge milestone PRs (`milestone/x.y.0` → `main`) and sync PRs (`main` → `milestone/x.y.0`) with a merge commit, never squash. Releases come from `main` only. Details: [CONTRIBUTING.md — Milestones, branches and releases](../CONTRIBUTING.md#milestones-branches-and-releases).

9. **Website in English and German together.** A page under `website/src/content/docs/` changes in English and in German (`de/`, same slug) in the same pull request; the `website / locale parity` check fails otherwise.

10. **Write for the reader.** Goal first, then how; short sentences, one idea each. German is written natively (not word for word) and says „du“. Use the term from `docs/glossary.toml` for every concept, in both languages; the `prose` check (Vale) fails on the former product name and on rejected terms. See [CONTRIBUTING.md](../CONTRIBUTING.md#writing).

## Trademark and privacy

- **Brother, P-touch, PT-Series, QL-Series** are trademarks of **Brother Industries, Ltd.** This project is **not affiliated** with them.
- **Never include private IPs, hostnames, real domains, or tokens** in code, tests, examples, or docs. Use placeholders: `192.0.2.10`, `printer.example.com`, `<your-token>`.

## When suggesting code

- Prefer existing patterns in this repo.
- For HTTP clients use `httpx` (not `requests`).
- For SNMP use `pysnmp` v6+ asyncio API.
- For raster encoding follow the Brother spec at `docs/research/brother-spec/` if present, or link to the upstream PDF.
- For UI state changes: emit an `EventBus` event so SSE-connected clients update.
- For PWA features: progressive enhancement — non-PWA browsers must still work.

## Do not suggest

- Bare `except:`
- `print()` for logging — use `logging` module
- Hardcoded LAN IPs or domain names
- "TODO" comments without an issue link
- Mocking Brother hardware in unit tests when a fake protocol responder is more accurate
- Adding `Any` to type hints to silence mypy
