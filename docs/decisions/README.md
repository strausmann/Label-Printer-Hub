# Architecture Decision Records (ADRs)

This directory holds the binding architecture decisions for this project. Each decision is one file. Each file stays once written — to revise, write a new ADR that supersedes the old one and update the old one's status.

## Why ADRs?

So that anyone (including future-us) can answer **"why did we do it this way?"** by reading one short document — not by archeology through commits, issues, and chat logs.

## How to read

Start with [`0001-two-container-architecture.md`](0001-two-container-architecture.md), which is the highest-level decision. The others slot into it.

Each ADR follows the [Nygard format](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions): Context → Decision → Consequences.

## Statuses

| Status | Meaning |
|---|---|
| `Proposed` | Drafted, not yet accepted |
| `Accepted` | Live and binding |
| `Deprecated` | No longer recommended but still present |
| `Superseded by N` | Replaced — see ADR N for the current decision |

## Index

| # | Title | Status |
|---|---|---|
| [0001](0001-two-container-architecture.md) | Two-container architecture (separate backend and frontend) | Accepted |
| [0002](0002-python-fastapi-backend.md) | Python + FastAPI for the backend | Accepted |
| [0003](0003-go-tailwind-htmx-pwa-frontend.md) | Go + Tailwind + HTMX + PWA for the frontend | Accepted |
| [0004](0004-plugin-architecture-for-printer-models.md) | Plugin architecture for printer models | Accepted |
| [0005](0005-print-queue-is-mandatory.md) | Print queue is mandatory (printer has none) | Accepted |
| [0006](0006-status-sources-by-phase.md) | Status sources by phase (ESC i S / passive / SNMP) | Accepted |
| [0007](0007-docker-image-tag-scheme.md) | Docker image tag scheme | Accepted |
| [0008](0008-conventional-commits-and-semantic-release.md) | Conventional Commits + semantic-release | Accepted |
| [0009](0009-server-sent-events-over-websockets.md) | Server-Sent Events instead of WebSockets | Accepted |
| [0010](0010-pwa-progressive-enhancement.md) | PWA with progressive enhancement | Accepted |
| [0011](0011-openapi-as-api-contract.md) | OpenAPI as the canonical API contract (oapi-codegen + interactive docs) | Accepted |
| [0012](0012-label-layout-management.md) | Label layouts are first-class, integration-scoped, multi-instance | Accepted |
| [0013](0013-browse-cart-bulk-print-ui-pattern.md) | Browse + cart + bulk-print UI pattern | Accepted |

## How to write a new ADR

1. Copy [`_template.md`](_template.md) to `NNNN-short-slug.md` where NNNN is the next free number, zero-padded
2. Fill in the sections honestly — including options not chosen
3. Open a PR with the ADR alone (separate from implementation, when feasible)
4. After merge, update the index above
