# CLAUDE.md — AI Assistant Configuration

This file configures **Claude Code** (and other LLM-based tools that read it) for this repository. It is intentionally short — the actual project knowledge lives in [`docs/`](docs/).

## Read these first

When you start working in this repository, read in this order:

1. [`README.md`](README.md) — project overview
2. [`website/src/content/docs/developers/architecture.md`](website/src/content/docs/developers/architecture.md) — current architecture in one page (published at https://labelyard.app/developers/architecture/)
3. [`docs/decisions/`](docs/decisions/) — ADRs explaining **why** every architectural choice was made
4. [`docs/policies/privacy.md`](docs/policies/privacy.md) — what must NOT be committed (binding)
5. [`docs/policies/trademarks.md`](docs/policies/trademarks.md) — Brother trademark rules (binding)
6. [`docs/learnings/code-review-patterns.md`](docs/learnings/code-review-patterns.md) — recurring AI-review findings, **avoid these proactively** so we don't burn review cycles on the same mistakes
7. [`CONTRIBUTING.md`](CONTRIBUTING.md) — Conventional Commits, TDD workflow, PR rules

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
| **README screenshots** — a new UI feature gets its screenshot in the same PR; an essential UI change updates the affected ones (`pnpm screenshots`) | [CONTRIBUTING.md](CONTRIBUTING.md#web-ui-screenshots) |
| **Type hints + mypy --strict** in Python | [CONTRIBUTING.md](CONTRIBUTING.md) |
| **Use `httpx` not `requests`**, `pysnmp` v6+ asyncio API, `logging` not `print()` | — |
| **Website in English and German together** — every page under `website/src/content/docs/` changes in both languages in the same PR | [CONTRIBUTING.md](CONTRIBUTING.md#website) |
| **Write for the reader** — goal first, short sentences, glossary terms (`docs/glossary.toml`), German natively with „du“, English and German in the same PR | [CONTRIBUTING.md](CONTRIBUTING.md#writing) |

## Branches, PR targets and merge style (mandatory)

Version numbers are planned through milestones ([CONTRIBUTING.md — Milestones, branches and releases](CONTRIBUTING.md#milestones-branches-and-releases), [ADR 0025](docs/decisions/0025-milestone-branches-for-minor-and-major-releases.md)). The `release-impact` check and the release guard reject anything else.

- **Features (`feat`) and breaking changes** branch from `milestone/x.y.0` (or `milestone/x.0.0`) and the PR targets that milestone branch. Never put a `feat`, `!` or `BREAKING CHANGE:` commit or PR title on `main` outside a milestone merge — that includes "small" features hidden in a fix PR.
- **Fixes, docs, CI, chores** branch from `main` and target `main`. Only patch-level or non-releasing changes go to `main` directly.
- **Milestone PRs** (`milestone/x.y.0` → `main`) and **sync PRs** (`main` → `milestone/x.y.0`) are merged with a **merge commit**. Never squash or rebase them. Everything else is squash-merged.
- Releases happen from `main` only. Never tag, release or publish from a milestone branch; previews are `x.y.0-rc.N` images from the Preview image workflow.

## Things you should propose, not do silently

- Adding a new dependency — explain why in the PR description
- New API endpoint — must come with OpenAPI schema (auto via FastAPI Pydantic models — see [ADR 0011](docs/decisions/0011-openapi-as-api-contract.md))
- New file over ~400 lines — ask whether it should be split
- Architecture change — propose as an ADR PR before implementing. An ADR is `Proposed` until the change ships, then `Accepted` in the same PR; a replaced ADR gets `Superseded by` in its header. Register rows and ADR headers must agree (`backend/tests/unit/test_decision_register.py`)
- Mid-print cancel logic on TCP/9100 — refuse, this is forbidden ([ADR 0005](docs/decisions/0005-print-queue-is-mandatory.md))

## Where to put new things

| Type of work | Location |
|---|---|
| Architectural decision (with rationale) | New ADR under [`docs/decisions/`](docs/decisions/) |
| Engineering doc (reference) | [`docs/`](docs/) |
| User-facing tutorial / FAQ / integration recipe | [Wiki](https://github.com/strausmann/labelyard/wiki) |
| Sample compose file | [`examples/`](examples/) |
| Brother spec extracts / research | [`docs/research/`](docs/research/) |
| Ongoing bugfix or feature | Issue + branch + PR (fix → `main`, feature → `milestone/x.y.0`) |

## When you don't know

Ask in the PR description or open a draft PR with questions. Don't fabricate — especially around Brother protocol details, library APIs, or maintainer-specific deployment values.

## Peer-review with other AI assistants

Every pull request in this project is reviewed by **Codex** (`chatgpt-codex-connector`; comment `@codex review` to request a new review after changes). **GitHub Copilot** can be requested on a PR and follows [`.github/copilot-instructions.md`](.github/copilot-instructions.md).

When working on a PR:

- **Read their comments carefully** — they often catch real issues (security, style, language idioms) that the maintainer is happy to defer to. Their false-positive rate is non-zero but the signal is good.
- **Reply to every comment** — either fix or explain why not. Silent dismissal is bad form and loses the review's value.
- **Don't pretend their feedback didn't happen**. If a Gemini comment says "this looks like SQL injection", and you decide it's actually parameterised query, write that reply explicitly.
- **Treat them as colleagues, not gates**. Their suggestions are inputs to your judgement, not commands. The maintainer is the final arbiter.

The full review workflow is documented in [CONTRIBUTING.md](CONTRIBUTING.md) section 7.

## Privacy reminder

You will sometimes be invoked from contexts that have access to the maintainer's private repos and notes (e.g. `homelab-pangolin-client`). **Never** transcribe values from those contexts into this public repository. Use placeholders. The CI `privacy-scan` job will reject obvious leaks but it can't catch everything — your judgement is the first line of defence.
