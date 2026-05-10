# CLAUDE.md — AI Assistant Configuration

This file configures **Claude Code** (and other LLM-based tools that read it) for this repository. It is intentionally short — the actual project knowledge lives in [`docs/`](docs/).

## Read these first

When you start working in this repository, read in this order:

1. [`README.md`](README.md) — project overview
2. [`docs/architecture.md`](docs/architecture.md) — current architecture in one page
3. [`docs/decisions/`](docs/decisions/) — ADRs explaining **why** every architectural choice was made
4. [`docs/policies/privacy.md`](docs/policies/privacy.md) — what must NOT be committed (binding)
5. [`docs/policies/trademarks.md`](docs/policies/trademarks.md) — Brother trademark rules (binding)
6. [`CONTRIBUTING.md`](CONTRIBUTING.md) — Conventional Commits, TDD workflow, PR rules

If you're about to make a non-trivial change without having read those first, stop and read them.

## Hard rules (no exceptions)

| Rule | Reference |
|---|---|
| **Conventional Commits** for every commit. semantic-release depends on it | [CONTRIBUTING.md](CONTRIBUTING.md), [ADR 0008](docs/decisions/0008-conventional-commits-and-semantic-release.md) |
| **TDD** — failing test first, then code | [CONTRIBUTING.md](CONTRIBUTING.md) |
| **Plugin architecture** — model-specific code only in `app/printer_models/<series>.py` | [ADR 0004](docs/decisions/0004-plugin-architecture-for-printer-models.md) |
| **Print queue mandatory** — never bypass it | [ADR 0005](docs/decisions/0005-print-queue-is-mandatory.md) |
| **No private network artefacts** — IPs/hostnames/domains/tokens | [`docs/policies/privacy.md`](docs/policies/privacy.md) |
| **Brother trademark fair use only** | [`docs/policies/trademarks.md`](docs/policies/trademarks.md) |
| **Type hints + mypy --strict** in Python | [CONTRIBUTING.md](CONTRIBUTING.md) |
| **Use `httpx` not `requests`**, `pysnmp` v6+ asyncio API, `logging` not `print()` | — |

## Things you should propose, not do silently

- Adding a new dependency — explain why in the PR description
- New API endpoint — must come with OpenAPI schema (auto via FastAPI Pydantic models — see [ADR 0011](docs/decisions/0011-openapi-as-api-contract.md))
- New file over ~400 lines — ask whether it should be split
- Architecture change — propose as an ADR PR before implementing
- Mid-print cancel logic on TCP/9100 — refuse, this is forbidden ([ADR 0005](docs/decisions/0005-print-queue-is-mandatory.md))

## Where to put new things

| Type of work | Location |
|---|---|
| Architectural decision (with rationale) | New ADR under [`docs/decisions/`](docs/decisions/) |
| Engineering doc (reference) | [`docs/`](docs/) |
| User-facing tutorial / FAQ / integration recipe | [Wiki](https://github.com/strausmann/label-printer-hub/wiki) |
| Sample compose file | [`examples/`](examples/) |
| Brother spec extracts / research | [`docs/research/`](docs/research/) |
| Ongoing bugfix or feature | Issue + branch + PR |

## When you don't know

Ask in the PR description or open a draft PR with questions. Don't fabricate — especially around Brother protocol details, library APIs, or maintainer-specific deployment values.

## Privacy reminder

You will sometimes be invoked from contexts that have access to the maintainer's private repos and notes (e.g. `homelab-pangolin-client`). **Never** transcribe values from those contexts into this public repository. Use placeholders. The CI `privacy-scan` job will reject obvious leaks but it can't catch everything — your judgement is the first line of defence.
