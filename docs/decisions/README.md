<!--
SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Architecture Decision Records (ADRs)

This directory holds the binding architecture decisions for this project. Each decision is one file. Each file stays once written — to revise, write a new ADR that supersedes the old one and update the old one's status.

## Why ADRs?

So that anyone (including future-us) can answer **"why did we do it this way?"** by reading one short document — not by archeology through commits, issues, and chat logs.

## How to read

Start with [`0015-single-process-deployment.md`](0015-single-process-deployment.md), which is the highest-level decision (it supersedes 0001). The others slot into it.

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
| [0001](0001-two-container-architecture.md) | Two-container architecture (separate backend and frontend) | Superseded by 0015 |
| [0002](0002-python-fastapi-backend.md) | Python + FastAPI for the backend | Accepted |
| [0003](0003-go-tailwind-htmx-pwa-frontend.md) | Go + Tailwind + HTMX + PWA for the frontend | Superseded by 0016 |
| [0004](0004-plugin-architecture-for-printer-models.md) | Plugin architecture for printer models | Accepted (amended by 0020) |
| [0005](0005-print-queue-is-mandatory.md) | Print queue is mandatory (printer has none) | Accepted (amended by 0020) |
| [0006](0006-status-sources-by-phase.md) | Status sources by phase (ESC i S / passive / SNMP) | Accepted (amended 2026-11-10: SNMP is the network source) |
| [0007](0007-docker-image-tag-scheme.md) | Docker image tag scheme | Accepted (single image, see 0015; image name amended by 0026) |
| [0008](0008-conventional-commits-and-semantic-release.md) | Conventional Commits + semantic-release | Accepted (amended by 0025) |
| [0009](0009-server-sent-events-over-websockets.md) | Server-Sent Events instead of WebSockets | Accepted (JSON stream, see 0015/0016) |
| [0010](0010-pwa-progressive-enhancement.md) | PWA with progressive enhancement | Accepted |
| [0011](0011-openapi-as-api-contract.md) | OpenAPI as the canonical API contract (oapi-codegen + interactive docs) | Accepted |
| [0012](0012-label-layout-management.md) | Label layouts are first-class, integration-scoped, multi-instance | Superseded by `LayoutEngine` + `ContentType` (PR #109) |
| [0013](0013-browse-cart-bulk-print-ui-pattern.md) | Browse + cart + bulk-print UI pattern | Accepted (amended 2026-11-10: no browse grid, search instead) |
| [0014](0014-pangolin-sso-and-bypass-trusted-for-all-scopes.md) | Pangolin-SSO and Bypass are trusted for all scopes | Superseded by 0019 |
| [0015](0015-single-process-deployment.md) | Single-process deployment: the backend serves the UI | Accepted |
| [0016](0016-react-typescript-web-ui.md) | React + TypeScript web UI | Accepted |
| [0017](0017-settings-in-database-env-locks-encrypted-secrets.md) | Settings in the database; environment locks fields; secrets encrypted | Accepted |
| [0018](0018-decision-register.md) | Public decision register with D/V/L labels | Accepted |
| [0019](0019-proxy-headers-need-trust-token.md) | Proxy identity headers are trusted only with the trust token | Accepted |
| [0020](0020-backend-kinds-ipp-page-printers.md) | Page printers are a backend kind (IPP) with the hub's own client | Accepted |
| [0021](0021-api-versioning.md) | Every API route lives under `/api/v1` | Accepted |
| [0022](0022-design-system-and-app-layout.md) | Design system and app layout | Accepted |
| [0023](0023-sheet-archive.md) | Sheet archive, physical sheets and calibration (D13–D19) | Accepted |
| [0024](0024-runtime-printer-wiring-and-hardware-identity.md) | Printers are wired at runtime through one code path and identified by hardware | Accepted |
| [0025](0025-milestone-branches-for-minor-and-major-releases.md) | Minor and major releases come from milestone branches | Accepted |
| [0026](0026-rename-to-labelyard.md) | The project is called Labelyard | Accepted |

The [decision register](register.md) lists the short `D<n>` labels cited in code.

## How to write a new ADR

1. Copy [`_template.md`](_template.md) to `NNNN-short-slug.md` where NNNN is the next free number, zero-padded
2. Fill in the sections honestly — including options not chosen
3. Open a PR with the ADR alone (separate from implementation, when feasible)
4. Add the ADR to the index above and, if it carries a `D<n>` label, to the [register](register.md)

## Keeping ADRs current

- An ADR is `Proposed` until the change ships, then `Accepted` **in the same PR** that ships it.
- A replaced ADR gets `Superseded by` in its header; a partly changed one gets an `Amended` header line or a short dated "Amendment" section. The decision text itself is never rewritten.
- The status in the register row, the ADR header and the index above must agree; `backend/tests/unit/test_decision_register.py` fails otherwise. It also fails when a label that code already uses is still `Proposed`.
