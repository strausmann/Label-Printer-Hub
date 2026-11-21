<!--
SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# 0017 — Settings in the database; environment locks fields; secrets encrypted

- **Status:** Accepted
- **Date:** 2026-11-04
- **Deciders:** maintainer
- **Decision labels:** D4, D5, D6, D7, D25
- **Amended by:** [0026](0026-rename-to-labelyard.md) — the environment prefix is `LABELYARD_`; the `PRINTER_HUB_` names below are read as a fallback
- **Amended:** 2026-11-21 (#296, #412) — the SNMP community of a printer falls under D5 (D25), see "Amendment — 2026-11-21" at the end

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

## Amendment — 2026-11-21 (ADR audit, #296, #412): the SNMP community of a printer (D25)

Since 1.7.0 (#296) the SNMP community of a tape printer is set in the printer form. The API already treats it like a D5 secret:

- **Write-only.** Responses never contain it; they show `connection.snmp.community_set` instead (`backend/app/services/printer_admin_service.py:231-241`; field description in `backend/app/schemas/printer_admin.py:37-53`).
- **Bound to its SNMP target.** A request without a community keeps the stored one only for the same host and port; when either changes, the request is refused with `422 snmp_community_required`, so a stored community never follows the printer to another address (`printer_admin_service.py:204-226`).
- **Kept out of the runtime's state.** The runtime keeps only a SHA-256 digest of the wiring key that holds the community (`backend/app/services/printer_runtime.py:226-229`).

It is not encrypted at rest: it sits in plain text in the printer's `connection` JSON column (`backend/app/models/printer.py:38`), while D5 secrets are sealed with `LABELYARD_SECRET_KEY` (`backend/app/settings_store/store.py:7`). A copy or backup of the database therefore holds every community string.

**Decision (maintainer, 2026-11-21): printer connection secrets fall under D5.** The SNMP community is stored encrypted with the D5 mechanism from milestone 1.8.0; existing values are migrated in place, and the downgrade decrypts them. This is #412, still open. Until it ships, the plain-text storage is the known gap, not an accepted exception. Register label D25.

The environment names in the text above use the old `PRINTER_HUB_` prefix; since ADR 0026 they are `LABELYARD_`, with the old prefix read as a fallback.

