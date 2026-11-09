# 0025 — Minor and major releases come from milestone branches

- **Status:** Accepted
- **Date:** 2026-11-09
- **Deciders:** maintainer

## Context

[ADR 0008](0008-conventional-commits-and-semantic-release.md) lets semantic-release derive every version from the commits on `main`, released nightly. That made the version a side effect of merge order: every `feat` merged to `main` produced its own minor release the next night, so a milestone planned as `1.5.0` could leave `main` as `1.5.0`, `1.6.0` and `1.7.0` before it was complete, and nobody could test the milestone as a whole before users got it. One stray `feat:` title on a bug fix, or a `BREAKING CHANGE:` footer in a squash body, was enough to move the minor or major version by accident, with nothing stopping it.

We want planned version numbers (a GitHub milestone `x.y.0` ships as release `x.y.0`), testable previews of a milestone before it is released, and fixes that still ship on their own, quickly.

## Decision

We develop each minor and major version on an integration branch `milestone/x.y.0`, ship it as one pull request into `main` merged with a merge commit, and allow only patch-level or non-releasing changes to reach `main` any other way.

- A maintainer opens the GitHub milestone `x.y.0` and creates `milestone/x.y.0` from `main` when work on it starts. Feature PRs (`feat/…`) target that branch. Major versions only come through a milestone `x.0.0`.
- The milestone ships as **one** PR `milestone/x.y.0` → `main`, merged with a **merge commit** (not squash), so semantic-release sees every feature commit, computes exactly `x.y.0` and keeps every changelog entry.
- Bug and security fixes (`fix/…`) go to `main` directly and ship as nightly patch releases. After `main` moves, `main` is merged into every open `milestone/*` branch (the `milestone-sync.yml` workflow opens those PRs).
- Releases are still made by semantic-release on `main` only (`.releaserc.json`, `release.yml`, nightly 04:00 UTC plus manual dispatch). A milestone branch is never released itself; previews `x.y.0-rc.N` are built from it with the Preview image workflow and published to GHCR only.

Two guards enforce the rule, both implemented in `scripts/release_impact.py`, which classifies commits with the same release rules as `.releaserc.json`:

1. The PR check `release-impact` (`release-impact.yml`) on every PR into `main`: from a non-milestone branch, the PR title and all commits may only be patch or none; from `milestone/x.y.z`, the last release bumped by the highest impact must equal `x.y.z`, and the GitHub milestone `x.y.z` must be open.
2. The release guard, wired as `verifyReleaseCmd` of `@semantic-release/exec`, runs before anything is tagged or published: the computed version must be the next patch of the last release or the title of an open GitHub milestone. Otherwise the run aborts and opens an issue `release blocked: computed <v>`. It covers what a PR check cannot see, such as a direct push by an admin.

## Options considered

### Option A — milestone integration branches with two guards (chosen)
- Pros: version numbers follow the plan; a milestone can be previewed and tested as a whole; fixes still ship nightly; mistakes fail before merge and, at the latest, before publishing.
- Cons: one more long-lived branch per milestone; main has to be merged into it after fixes; the milestone PR must be merged with a merge commit, which is easy to get wrong by habit (the PR check and the guard catch the numbering, not the merge style).

### Option B — keep releasing every `feat` from `main`, with labels or a release freeze
- Pros: no extra branches.
- Cons: versions still depend on merge order; a freeze stops fixes as well; no preview of the whole milestone.

### Option C — semantic-release pre-release channels (`next`, `beta`) on the milestone branch
- Pros: native semantic-release feature, previews get Git tags.
- Cons: pre-release tags and GitHub Releases for every preview; a second release configuration to maintain; the `next` channel numbering does not map to planned GitHub milestones without the same guard anyway.

## Consequences

- New workflows `release-impact.yml` (PR check; intended as a required check on `main`) and `milestone-sync.yml`; `.releaserc.json` gains a `verifyReleaseCmd`.
- CI, CodeQL and the licence checks also run on pull requests into `milestone/**` (commitlint already ran on every PR).
- CONTRIBUTING.md, section "Milestones, branches and releases", is the contributor-facing description; CLAUDE.md and `.github/copilot-instructions.md` carry the short rule for AI assistants.
- ADR 0008 still holds; its "squash-merge is the default" is amended: milestone PRs into `main` and sync PRs into a milestone branch are merged with a merge commit.
- Sync PRs are opened with `GITHUB_TOKEN`, which starts no other workflows; their checks have to be started by closing and reopening the PR.
- Register label D21.

## References

- [ADR 0008](0008-conventional-commits-and-semantic-release.md) — Conventional Commits + semantic-release (amended by this ADR)
- [ADR 0007](0007-docker-image-tag-scheme.md) — Docker image tag scheme (previews are `x.y.0-rc.N`, GHCR only)
- Workflows: [`release-impact.yml`](../../.github/workflows/release-impact.yml), [`milestone-sync.yml`](../../.github/workflows/milestone-sync.yml), [`release.yml`](../../.github/workflows/release.yml)
- Script: [`scripts/release_impact.py`](../../scripts/release_impact.py)
