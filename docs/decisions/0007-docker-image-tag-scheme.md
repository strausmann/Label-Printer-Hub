# 0007 — Docker image tag scheme

- **Status:** Accepted
- **Date:** 2026-05-10
- **Deciders:** maintainer

## Context

Each release publishes container images. Users want predictable tags so they can pin appropriately: some need exact reproducibility (`1.2.3`), some want auto-update within a major line (`1`), some want any stable version (`latest`).

Pre-releases (release candidates, betas) must not silently take over `latest` or major-line tags or downstream automated systems would break.

## Decision

Every **stable** release publishes the image with **four** tags pointing to the same digest:

| Tag | Example for `1.2.3` |
|---|---|
| `<major>.<minor>.<patch>` | `1.2.3` |
| `<major>.<minor>` | `1.2` |
| `<major>` | `1` |
| `latest` | `latest` |

**Pre-releases** (semver with hyphen, e.g. `1.0.0-rc.1` or `2.0.0-beta.3`) publish **only the full version tag** — never `<major>.<minor>`, `<major>`, or `latest`.

Both backend and frontend images (per ADR 0001) follow this scheme identically and are released together at the same version.

Builds are multi-architecture: `linux/amd64` + `linux/arm64`. The four tags reference a manifest list pointing at both architectures.

OCI labels are populated on every image: `org.opencontainers.image.version`, `org.opencontainers.image.revision`, `org.opencontainers.image.source`, `org.opencontainers.image.licenses`.

## Options considered

### Option A — Four tags per release (chosen)
- Pros: matches Docker community convention; users can pin at any granularity; pre-release safety
- Cons: slightly more registry storage (negligible — all tags point to one digest)

### Option B — Only full version + `latest`
- Pros: simpler
- Cons: forces users to either pin to exact version or trust `latest`; no middle ground

### Option C — Full version only, no `latest`
- Pros: most strict; users must explicitly opt into version
- Cons: makes "just give me something working" harder; bad first impression

## Consequences

- `.github/workflows/docker-publish.yml` uses `docker/metadata-action` with `type=semver` patterns + `type=raw` for `latest` gated by `!contains(tag, '-')`
- `docker/metadata-action` automatically suppresses `{{major}}.{{minor}}` and `{{major}}` for pre-releases — no extra logic needed
- A post-push CI step verifies the multi-arch manifest contains both `linux/amd64` and `linux/arm64`
- README's "Container images and tags" section documents the user-visible contract
- Future major bump: same scheme, `2.0.0` → `2.0`, `2`, `latest` (overwrites previous `latest`)

## References

- Workflow: [`.github/workflows/docker-publish.yml`](../../.github/workflows/docker-publish.yml)
- Related: ADR 0001 (two-container, both follow this scheme), ADR 0008 (semantic-release publishes the tags)
