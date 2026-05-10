# 0008 — Conventional Commits + semantic-release for automated releases

- **Status:** Accepted
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

**Release trigger:** push to `main`. Maintainers do not manually tag releases.

**Release pipeline:**
1. Push to `main`
2. `release.yml` workflow runs `semantic-release`
3. semantic-release inspects commits since last tag → decides version bump
4. Updates `CHANGELOG.md`, creates Git tag, creates GitHub Release
5. Release-published event triggers `docker-publish.yml` → builds and pushes both backend and frontend images per ADR 0007

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
