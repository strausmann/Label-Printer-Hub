# Style Guide for Gemini Code Reviews

This document teaches Gemini how to review PRs in this repository. Rules echo the canonical [CLAUDE.md](../CLAUDE.md).

## Project context

Self-hosted hub for Brother PT/QL label printers. Python (FastAPI) backend + Go (Tailwind/HTMX/PWA) frontend. Plugin-based for new printer models.

## Review priorities (highest first)

1. **Privacy violations.** Flag any hardcoded LAN IPs, real hostnames, real domains, real tokens, or PII. The maintainer's network must not be deducible from this repository.
2. **Trademark misuse.** Brother trademarks may only describe hardware compatibility. Flag any wording that suggests endorsement, partnership, or sponsorship.
3. **Plugin architecture violations.** Model-specific code outside `app/printer_models/<series>.py` is a bug.
4. **Brother Raster Command Reference compliance.** Status block parsing, tape codes, error bits must match the spec. If the PR adds new printer-protocol logic without referencing the spec section, ask for the citation.
5. **TDD.** Behaviour changes without tests get pushed back.
6. **Conventional Commits.** PR title and squash-merge subject must comply.
7. **Type safety.** `mypy --strict` on `app/`. Flag new `Any` introductions.
8. **Mid-print cancel.** If a PR enables cancelling a `printing` job over TCP/9100, flag it — the Brother spec forbids this.

## Languages and frameworks

- Python 3.12+, FastAPI, asyncio, SQLModel, pytest, ruff, mypy
- Go web server (frontend), Tailwind CSS, HTMX, Service Workers, Web Notifications API

## Things to flag

- Bare `except:` clauses
- `print()` for logging
- Synchronous I/O in async functions
- `requests` library (use `httpx`)
- New dependencies without rationale in PR description
- Files exceeding 400 lines that don't have a clear single responsibility
- Tests that mock Brother hardware behaviour in ways the spec doesn't authorise

## Things NOT to flag

- Use of HTMX (it's our chosen UI pattern)
- Server-Sent Events instead of WebSockets (deliberate)
- SQLite as the only DB (deliberate, single-container deployment)
- `asyncio.Queue` + lock pattern for the print queue (mandatory architecture)

## Tone

Professional, terse, evidence-based. Cite repo docs (CLAUDE.md, CONTRIBUTING.md, the Brother spec extract) when correcting a contributor. No condescension.
