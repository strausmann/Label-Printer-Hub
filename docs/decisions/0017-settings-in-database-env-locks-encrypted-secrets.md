<!--
SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# 0017 — Settings in the database; environment locks fields; secrets encrypted

- **Status:** Accepted
- **Date:** 2026-11-04
- **Deciders:** maintainer
- **Decision labels:** D4, D5, D6, D7

## Context

Until now the hub was configured only through environment variables and a `printers.yaml` file. Integration URLs, tokens and printers could not be changed without editing files and restarting. The new UI should let an operator configure integrations and printers (D6), but existing deployments that set values in the environment must keep working and must not be silently overridden. Integration secrets must not sit in the database in plain text, and a fresh install needs a way to sign in without a seeded, well-known admin key.

## Decision

Runtime settings live in the database and are editable through the settings API and UI. Rules:

**Environment wins and locks (D4).** If an environment variable is set to a non-empty value, it overrides the stored value and the field is reported as locked; the UI shows it read-only with the reason. An empty environment value does not lock.

**Secrets are encrypted and write-only (D5).** Secret values are stored with AES-GCM using a master key from `PRINTER_HUB_SECRET_KEY`, with per-key additional authenticated data so a ciphertext cannot be moved to another key. Secrets are never returned by any API; the UI can only set or clear them. A secret is bound to the normalised URL that was effective when it was saved: if the URL changes the secret must be re-entered, and it is only ever sent when the target URL equals the binding. Saving a secret with no effective URL is rejected (`url_required_for_secret`). An environment-provided secret is usable only together with an environment-provided URL; otherwise it is treated as unconfigured and the settings description says why.

**Printers are managed in the UI (D6).** The `printers.yaml` file and the dead `printers_config` setting are removed.

**Bootstrap key and recovery (D7).** Migrations no longer seed an admin API key. The operator supplies a bootstrap key through `PRINTER_HUB_BOOTSTRAP_ADMIN_KEY` (at least 32 characters; empty disables bootstrap). The backend never generates or prints one. It is accepted for sign-in only while no enabled admin key exists, and a bootstrap session may only create an unrestricted, unexpired admin key. Once an admin key exists the bootstrap key is refused (`bootstrap_disabled`) and the variable should be removed. If all admin access is lost, `printer-hub admin create-key` run inside the container creates a new admin key. Existing databases keep their rows.

## Options considered

### Option A — database store, env overrides and locks (picked)
- Pros: UI-editable; existing env deployments unchanged; clear precedence.
- Cons: two sources of truth, mitigated by explicit lock reporting.

### Option B — environment only
- Pros: simplest, declarative.
- Cons: no in-app configuration; every change is a redeploy.

### Option C — store settings and let the UI override the environment
- Pros: UI always effective.
- Cons: silently defeats operators who pin config in compose; surprising and hard to audit.

## Consequences

- `PRINTER_HUB_SECRET_KEY` becomes a required variable; losing it makes stored secrets unreadable (they must be re-entered).
- Secret rotation of the master key is not part of this decision and can follow.
- Fresh installs have no default credential; operators set the bootstrap key variable or use the recovery command.

## References

- Spec: `docs/superpowers/specs/2026-11-03-web-ui-redesign-design.md` (sections 8 and 10)
- Related ADR-0015, ADR-0019
