# 0014 — Pangolin-SSO and Bypass are trusted for all scopes

- **Status:** Accepted
- **Date:** 2026-06-23
- **Deciders:** Project Owner

## Context

In Phase 7c (Issue #78, 2026-05-17) we introduced per-app authentication on top of the Pangolin-edge gating. The motivation was leak-defence: if the `claude-automation` Basic-Auth bypass secret leaks, callers should not automatically have full CRUD on every endpoint.

The implementation introduced three auth scopes (`read`, `print`, `admin`) and four auth paths:

1. `X-Label-Hub-Key` — API key (each key carries its own scope set + per-printer ACL)
2. Pangolin-SSO (`Remote-User` + `X-Pangolin-Token` trust-token)
3. Pangolin-SSO Legacy (`X-Pangolin-User`)
4. Pangolin Bypass (Basic-Auth `claude-automation:...`)

Paths 2/2b/3 were hard-coded to grant **read scope only**. This was intentional defensive design.

Two practical problems surfaced in production:

- The HTML UI in the Frontend has admin routes (`/admin/printers`, `/admin/api-keys`) that need `admin` scope. Browser users authenticated via Pangolin SSO got a 503 from the Frontend (Backend returned 401 because the SSO path could not satisfy `admin`). The Admin UI was effectively unusable through SSO — which is its primary access path.
- The Bypass path was also `read`-only. Tooling that needs to script printer changes from a curl had to provision an API key first, despite the bypass-secret already being a strongly-guarded high-trust credential (single Vault item, rotated separately).

A wider context point: this project is deployed in HomeLab-sized installations today, and is designed to scale into multi-team OSS setups. Per-integration scoping on API keys is genuinely useful (e.g. Snipe-IT should be able to print but not delete printers). Per-browser-user scoping is not — Pangolin already controls who can reach the upstream at all via its Resource Policy.

## Decision

**Pangolin-SSO and Pangolin-Bypass are trusted for any scope the caller requests.** API keys continue to enforce their stored scope.

`require_scope(required)` resolves like this:

1. `X-Label-Hub-Key` — the key's scope must satisfy `required` (unchanged)
2. Pangolin-SSO (Standard headers or Legacy) — grants `required` directly
3. Pangolin Bypass — grants `required` directly

The defense-in-depth for SSO is now provided exclusively by Pangolin's Resource Policy: it decides who can reach `labels.strausmann.cloud` at all. Anyone who passes that gate is treated as a fully authenticated operator.

The defense-in-depth for Bypass is now operational hygiene: the bypass-secret lives in Vault, is rotated on suspected leak, and is meant for ad-hoc curl and emergency operations — production integrations are expected to use scoped API keys.

## Options considered

### Option A — what we picked: SSO and Bypass trusted for all scopes

- Pros:
  - Browser-UI works out of the box for SSO-authenticated users
  - Bypass is a real fallback again (not just a read fallback)
  - Tiny code change (≈5 LOC), tiny conceptual change
  - Aligns with the existing trust model: Pangolin owns the edge, the app trusts what comes through
- Cons:
  - Bypass-secret leak now grants full access. Mitigation: secret lives in Vault, rotation is a single ENV change + stack restart
  - No app-side per-user role distinction. Acceptable because that is what Pangolin's Resource Policy / roles are for

### Option B — Keep scope-tiering, add an SSO admin-user allow-list

- Pros: Preserves "leak → only read" defense
- Cons:
  - Requires per-deployment ENV var (`PRINTER_HUB_SSO_ADMIN_USERS=…`)
  - Two places define who is admin (Pangolin's policy + this ENV) → drift risk
  - Adds friction every time an OSS user wants to use the Admin UI: "why is my UI giving 503?"

### Option C — Remove the scope system entirely

- Pros: Smallest mental model
- Cons:
  - Removes per-integration scoping on API keys, which is the part that genuinely earns its keep (Hangar with `print`-only, Snipe-IT with `read`-only, Grocy-webhook unaffected). Rejected by the project owner during the decision discussion.

## Consequences

- `backend/app/auth/dependencies.py::require_scope`: SSO and Bypass paths return `scope=required` instead of a hard-coded `"read"`. The `pangolin_bypass_scope_downgrade` feature flag is left in `Settings` for one release to avoid forcing an env-config change on existing deployments, but the runtime no longer reads it for decision-making.
- `backend/tests/unit/auth/test_dependencies.py`: the previous "SSO blocked on print" test is replaced by a parametrised test that asserts SSO grants `print` and `admin`.
- API key behaviour is unchanged. The Admin UI for managing API keys is unchanged.
- Frontend (`frontend/internal/api/client.go`) is unchanged.
- OpenAPI schema is unchanged.
- DB migrations are unchanged.

### Follow-ups

- After one release cycle, drop the `pangolin_bypass_scope_downgrade` Settings field (dead flag).
- If a future deployment ever does want SSO-tiered access (multi-team setup with viewer/operator roles), the natural place is a Pangolin-role-based check on `Remote-Role`, configurable via env — not in scope here.

## References

- Issue #78 — Phase 7c original auth introduction
- PR #130 — `X-Pangolin-Token` forwarding in Frontend
- PR #132 — `Remote-User` forwarding in Frontend
- ADR 0011 — OpenAPI-as-contract (auth headers must remain part of contract)
