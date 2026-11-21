<!--
SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# 0008 — Conventional Commits + semantic-release for automated releases

- **Status:** Accepted
- **Amended by:** [0025](0025-milestone-branches-for-minor-and-major-releases.md) — minor and major releases come from milestone branches merged with a merge commit; a release guard runs before anything is published
- **Amended:** 2026-11-21 — scopes, release tooling and the single image as built, see "Amendment — 2026-11-21" at the end
- **Date:** 2026-05-10
- **Deciders:** maintainer

## Context

Releases need version numbers, changelogs, Git tags, GitHub Releases, and Docker image pushes. Doing this by hand is tedious and error-prone — humans forget to bump, get the order wrong, or write inconsistent changelogs. We want the release process to be derivable from the commit history alone.

We also want the project's commit history to communicate intent, not just diffs, so that "what changed since 1.2.0" becomes a useful answer for users and downstream automation.

## Decision

We adopt **[Conventional Commits 1.0.0](https://www.conventionalcommits.org/)** as the mandatory commit-message format and **[semantic-release](https://github.com/semantic-release/semantic-release)** as the release tool.

**Format:**
```
<type>(<scope>): <subject>

<body>

<footer>
```

| Type | Version impact | Use |
|---|---|---|
| `feat` | minor | new feature |
| `fix` | patch | bug fix |
| `perf` | patch | performance |
| `docs` | none | documentation only |
| `test`, `refactor`, `chore`, `ci`, `style`, `build` | none | internal |
| `feat!` or `BREAKING CHANGE:` footer | major | breaking |

Allowed scopes: `printer-models`, `queue`, `status`, `api`, `ui`, `webhook`, `docker`, `ci`, `examples`, `docs`, `integration`, `pwa`, `security`, `release`. Validated by `commitlint` on PR titles.

**Release trigger:** **scheduled (nightly 04:00 UTC) + manual via `workflow_dispatch`**. Merges to `main` do NOT publish releases — they only accumulate changes for the next release window. This separation means merging stays cheap and frequent, while releasing remains a deliberate event the maintainer can review or postpone.

Maintainers do not manually tag releases. To trigger an unscheduled release (e.g. for a security hotfix), use the **Run workflow** button on the Release workflow.

**Release pipeline:**
1. Schedule fires at 04:00 UTC (or maintainer hits "Run workflow")
2. `release.yml` workflow runs `semantic-release` against `main` HEAD
3. semantic-release inspects commits since last tag → decides version bump (or skips if no releasable commits exist)
4. If a release is due: updates `CHANGELOG.md`, creates Git tag, creates GitHub Release
5. Release-published event triggers `docker-publish.yml` → builds and pushes both backend and frontend images per ADR 0007

**When a scheduled run skips publishing:** semantic-release evaluates *all* commits between the last tag and HEAD, not just commits made since the previous run. A scheduled release only skips when there are no `feat`, `fix`, or `perf` commits in that range. If a previous merge already added a `feat` commit, the next scheduled run will publish — adding `chore` or `docs` commits afterwards does not suppress the release. To intentionally postpone a release window, the only mechanism is to defer merges that would bump the version.

**Branch guard:** the release job runs only when `github.ref == 'refs/heads/main'`. `workflow_dispatch` can be triggered against any branch from the Actions UI; the guard ensures a release can never be published from a non-main ref.

## Options considered

### Option A — Conventional Commits + semantic-release (chosen)
- Pros: fully automated; deterministic versioning; rich changelogs; mature tooling; clear contributor expectations
- Cons: contributors must learn the format (one-time cost); breaking changes need explicit footer

### Option B — Manual versioning + hand-written changelog
- Pros: full human control
- Cons: easy to forget steps; inconsistent changelog quality; bottleneck on the maintainer for every release

### Option C — Calendar versioning (CalVer)
- Pros: no need to think about semver semantics
- Cons: doesn't communicate breaking changes; less useful for downstream consumers; doesn't match the Docker tag scheme of ADR 0007 which assumes semver

## Consequences

- `.releaserc.json` configures plugins: `commit-analyzer`, `release-notes-generator` (conventionalcommits preset), `changelog`, `github`, `git`
- `package.json` declares semantic-release dev dependencies
- `commitlint.config.cjs` enforces type/scope/subject rules; CI blocks PRs with non-conforming titles (`commitlint.yml` workflow)
- `CONTRIBUTING.md` documents the format with examples
- Squash-merge is the default merge mode; the squash-commit message must follow Conventional Commits (the PR title becomes that message)
- semantic-release writes `CHANGELOG.md` automatically — contributors must not touch it manually
- `BREAKING CHANGE:` in any commit footer triggers a major bump even on a `fix:` type — this is intentional

## References

- [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/)
- [semantic-release docs](https://semantic-release.gitbook.io/)
- Workflow: [`.github/workflows/release.yml`](../../.github/workflows/release.yml)
- Workflow: [`.github/workflows/commitlint.yml`](../../.github/workflows/commitlint.yml)
- Config: [`.releaserc.json`](../../.releaserc.json), [`commitlint.config.cjs`](../../commitlint.config.cjs)
- Related: ADR 0007 (Docker tag scheme — consumes the version semantic-release decides)

## Amendment — 2026-11-21 (ADR audit): scopes, tooling and image as built

The decision (Conventional Commits, semantic-release, nightly release from `main`) stands. Details of the text above that changed:

- **Scopes.** The scope list in the decision is outdated. The list in force is the `scope-enum` rule of `commitlint.config.cjs:26-62` (it adds, for example, `sheets`, `printers`, `decisions` and `spoolman`). The rule has level 1, so commitlint warns about a scope outside the list and does not fail.
- **Tooling.** semantic-release and its plugins are pinned with a lockfile in `.github/release-tools/`, and `release.yml` runs them from there (`.github/workflows/release.yml:96,129`); the root `package.json` holds only commitlint.
- **Pipeline step 5.** The release builds and pushes one image, `labelyard` (`.github/workflows/docker-publish.yml:88`; ADR 0015 and ADR 0026), not a backend and a frontend image.
- **Milestones and the release guard.** [ADR 0025](0025-milestone-branches-for-minor-and-major-releases.md) amends this ADR: minor and major versions come from `milestone/x.y.0` branches merged with a merge commit, and its guard runs as `verifyReleaseCmd` before anything is tagged (`.releaserc.json:71`).

