# 0025 — The project is called Labelyard

- **Status:** Accepted
- **Date:** 2026-11-11
- **Deciders:** maintainer
- **Amends:** [ADR 0007](0007-docker-image-tag-scheme.md) (image name)

## Context

The project grew from a hub for two Brother label printers into a tool for printers, sheet types, archives and integrations. "Label Printer Hub" (now the subtitle of Labelyard) describes a part of that, is long, and has no unique handle: the abbreviations in use were never agreed names and drifted apart across the code, the image, the command line and the documentation.

Renaming has a cost that is easy to underestimate. Some old names live outside our control: in users' compose files, environment files, exported files, API clients and registry pulls. A rename that breaks them turns a branding decision into an outage for everybody who runs the hub.

## Decision

We call the project **Labelyard**, with the subtitle "the self-hosted Label Printer Hub for all your labels". The old display name survives only as that subtitle and in the sentence "Formerly *Label Printer Hub*." in the README.

We change everything we own and keep everything that users' data or clients depend on. The compatibility table is binding:

| Surface | New | Old | Compatibility |
|---|---|---|---|
| Image | `ghcr.io/strausmann/labelyard`, `docker.io/<user>/labelyard` | `ghcr.io/strausmann/label-printer-hub-backend`, `docker.io/<user>/label-printer-hub-backend` | Old images are not updated. Users change `image:` once |
| Repository | `strausmann/labelyard` | `strausmann/Label-Printer-Hub` | GitHub redirects the old address |
| Environment prefix | `LABELYARD_` | `PRINTER_HUB_` | Old prefix still read as a fallback; the new one wins; empty values are ignored on both; one startup warning lists the names; kept until at least 2.0.0 |
| PDF font variable | `LABELYARD_PDF_FONT` | `PRINTHUB_PDF_FONT` | Same rules as the prefix |
| Command | `labelyard` | the former command (see the migration guide) | The old command stays as an alias |
| API key header | `X-Label-Hub-Key` | — | Unchanged: it is a client-facing identifier |
| Key prefix | `lh_` | — | Unchanged |
| Database file name | `printer-hub.db` | — | Unchanged, so existing installs find their data |
| Sheet-type file format name | `<slug>.sheet-type` | — | Unchanged: stored in users' exported files |
| API paths | `/api/v1/...` | — | Unchanged |

A brand guard (`scripts/brand_guard.py`) lists every remaining old name outside an allow-list that mirrors this table, so the rename stays finished.

The migration steps for users are in [the migration guide](../migration/labelyard.md).

## Options considered

### Option A — rename, keep every data-bound name (picked)
- Pros: users upgrade by changing one line; no data migration; the brand is consistent where we control it.
- Cons: a few old names stay for good (header, key prefix, database file name); two prefixes must be supported for a while.

### Option B — rename everything including the header and the database file
- Pros: no leftovers.
- Cons: breaks every API client and needs a data migration for a cosmetic gain.

### Option C — keep the old name
- Pros: no work, no risk.
- Cons: the name stays ambiguous, and the drifting abbreviations stay.

## Consequences

- ADR 0007 keeps its text; the image it names is now `labelyard`. Its header carries an `Amended` line.
- Old images and the old repository address stop receiving updates; Watchtower and Renovate rules pinned to them never offer 1.6.0.
- Reading two environment prefixes is code we maintain until 2.0.0. Dropping the old prefix then needs its own decision.
- We claim no registered trademark for "Labelyard"; see the [trademark policy](../policies/trademarks.md).

## References

- Migration guide: [`docs/migration/labelyard.md`](../migration/labelyard.md)
- Brand guard: `scripts/brand_guard.py`
- Related: [ADR 0007](0007-docker-image-tag-scheme.md), [ADR 0017](0017-settings-in-database-env-locks-encrypted-secrets.md)
