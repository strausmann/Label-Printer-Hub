# Contributing to Label Printer Hub

Thanks for your interest in contributing! This document explains how to participate effectively.

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). By participating, you agree to abide by its terms.

## Contributor License Agreement

[![CLA assistant](https://cla-assistant.io/readme/badge/strausmann/Label-Printer-Hub)](https://cla-assistant.io/strausmann/Label-Printer-Hub)

Contributions need a signed [Contributor License Agreement](CLA.md). You sign it once through [CLA assistant](https://cla-assistant.io/): when you open your first pull request, the bot comments with a link; follow it, sign in with GitHub and accept. The `license/cla` check must pass before a pull request can be merged.

## Ways to contribute

| Contribution | Where |
|---|---|
| Report a bug | [Issues → Bug report](../../issues/new?template=bug_report.yml) |
| Suggest a feature | [Issues → Feature request](../../issues/new?template=feature_request.yml) |
| **Add a new printer model** | [Issues → Plugin request](../../issues/new?template=plugin_request.yml) — see also [`docs/plugin-development.md`](docs/plugin-development.md) |
| Ask a question | [Discussions](../../discussions) |
| Improve documentation | PR directly |
| Security issue | See [SECURITY.md](SECURITY.md) (do **not** open a public issue) |

## Development workflow

### 1. Fork & clone

```bash
gh repo fork strausmann/label-printer-hub --clone
cd label-printer-hub
```

### 2. Set up your environment

Backend (Python):
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
```

Frontend (from `frontend/`, pnpm):
```bash
pnpm install
pnpm dev          # Vite dev server; /api is proxied to a backend on localhost:8000
```

To build and run the whole hub from source without printer hardware, use the smoke-test compose file (throw-away keys,
one container, built from the local tree):

```bash
export PRINTER_HUB_SECRET_KEY="$(openssl rand -base64 32 | tr '+/' '-_')"
docker compose -f dev/docker-compose.smoke.yml up --build
# UI and API on http://localhost:8000
curl http://localhost:8000/healthz
```

### 3. Create a branch

Branch from `main` for a fix, docs, CI or other non-releasing change, and from the milestone branch `milestone/x.y.0` for a feature. Which base a pull request targets decides what it may contain, see [Milestones, branches and releases](#milestones-branches-and-releases).

Branch naming follows Conventional Commits prefix:

| Prefix | Use for |
|---|---|
| `milestone/x.y.0`, `milestone/x.y.x` | Integration branch of a minor/major milestone, or of a patch milestone `x.y.x` (maintainers create it); its PRs target it |
| `feat/` | New feature |
| `fix/` | Bug fix |
| `docs/` | Documentation only |
| `refactor/` | Code change without behaviour change |
| `test/` | Test additions/changes |
| `chore/` | Tooling, deps, CI |
| `perf/` | Performance |
| `ci/` | CI changes only |

Example: `git checkout -b feat/ptouch-tape-detection origin/milestone/1.5.0`.

### 4. Make changes — TDD please

This project follows **Test-Driven Development**. Every behaviour change requires:

1. Write a failing test first
2. Make the test pass with minimal code
3. Refactor if needed
4. Commit (Conventional Commits)

Run tests:
```bash
pytest                          # all
pytest tests/unit -v            # unit only
pytest tests/integration -v     # integration
pytest tests/hardware -v -m hw  # hardware-in-the-loop (skipped by default)
```

### 5. Commit messages — Conventional Commits

This is **mandatory**. We use [semantic-release](https://github.com/semantic-release/semantic-release) which generates version numbers and changelogs automatically from commit messages.

Format:
```
<type>(<scope>): <subject>

<body>

<footer>
```

Examples:
```
feat(printer-models): add Brother PT-D610BT plugin

Implements PrinterModel protocol for the PT-D610BT desktop label printer.
Tested with TZe-12mm and TZe-24mm tapes.

Closes #42
```

```
fix(queue): retry job no longer duplicates on race

Adds idempotency check before enqueueing the retry copy.
```

```
feat!: rename PrinterService.print() to submit_job()

BREAKING CHANGE: API consumers must update method calls. The new method
returns immediately with a JobId instead of blocking until print is done.
```

| Type | Effect on version | When to use |
|---|---|---|
| `feat` | minor (1.x.0) | New feature |
| `fix` | patch (1.0.x) | Bug fix |
| `perf` | patch | Performance improvement |
| `docs` | none (no release) | Docs only |
| `test`, `refactor`, `chore`, `ci`, `style` | none | Internal |
| `feat!` or `BREAKING CHANGE:` footer | major (x.0.0) | Breaking API change |

Scopes we use: `printer-models`, `queue`, `status`, `api`, `ui`, `webhook`, `docker`, `ci`, `examples`.

### 6. Push & open a Pull Request

- Use the [PR template](.github/pull_request_template.md) — fill in all sections
- Link the issue with `Closes #<num>` or `Refs #<num>`
- Wait for CI to pass
- Address review comments

Feature, fix and other topic PRs are squash-merged. The squash commit message **must** follow Conventional Commits — semantic-release will use it. Two kinds of PRs are the exception and are merged with a **merge commit**: the milestone PR `milestone/x.y.0` → `main` and the sync PRs `main` → `milestone/x.y.0` (see [Milestones, branches and releases](#milestones-branches-and-releases)).

### 7. Code review — humans and AIs

This project takes **AI-assisted code review seriously** as part of the standard PR workflow:

| Reviewer | What they look at | How to read their feedback |
|---|---|---|
| **Maintainer (human)** | Architecture fit, ADR compliance, hardware-specific behaviour, judgement calls | Authoritative — addresses or explains why not |
| **Gemini Code Assist** | Style, common pitfalls, security smells, language idiom — configured in [`.gemini/styleguide.md`](.gemini/styleguide.md) | Take seriously — false positives exist but the signal is good. Reply inline if disagreeing |
| **GitHub Copilot Chat** | (When invoked on a PR) similar to Gemini, plus deep code context. Following [`.github/copilot-instructions.md`](.github/copilot-instructions.md) | Same — read every comment, reply or fix |

**Workflow:**

1. Open the PR (draft is fine — push triggers reviews)
2. Wait for CI green + AI reviews to land (usually within 1-2 minutes)
3. **Read every AI comment.** Even when you disagree, write a brief reply explaining why — that builds the project's institutional memory of "we don't do X because Y"
4. Address legitimate findings with a follow-up commit; the reviewers re-run on push
5. Mark the PR ready for review when AI feedback is addressed
6. The maintainer reviews next; squash-merge follows their approval

**A PR is not ready to merge if:**
- AI reviewers found issues that haven't been addressed or explicitly dismissed (with reasoning)
- CI is red
- The PR title doesn't follow Conventional Commits
- The PR description is missing the linked issue or hardware-impact note (where relevant)

**One feature = one branch = one PR.** Don't bundle unrelated changes — that defeats the review value. If you discover an unrelated bug while working on a feature, file a separate issue and a separate PR.

**Before opening a PR, skim [`docs/learnings/code-review-patterns.md`](docs/learnings/code-review-patterns.md).** It collects recurring findings from previous AI reviews so you can self-correct in advance. When an AI review surfaces a *new* recurring pattern that's likely to bite future PRs, add it to that file in the same follow-up commit.

**Wait for the AI reviewers, even on small PRs.** Gemini and Copilot post within ~1-2 minutes. Merging a small "trivial" PR with `--admin` before they've commented forfeits the review value and makes follow-up comments awkward to address. If a PR is *truly* time-critical (security fix, broken main), call it out explicitly in the PR description and own that you're skipping the review window — and address any post-merge comments in a follow-up PR.

**Side-effects must be in the PR description.** If a PR primarily fixes A but also changes B, list both in the description. Reviewers shouldn't have to discover changes by reading the diff line by line.

## Triage

Issues opened from a form get the labels the form names (for example `area:sheets`). People outside the project cannot set labels themselves, so a maintainer sets the rest while triaging: the type label comes from what the reporter chose, not from the reporter. For the *Sheet type dimensions* form it comes from the `kind` field: "Dimensions are wrong" gets `type:bug`, "Dimensions are confirmed" gets `type:feedback`.

## Adding a new printer model (plugin)

Want to add support for a new Brother model (or even a non-Brother printer)? Excellent.

1. Open a [Plugin request issue](../../issues/new?template=plugin_request.yml) so others know it's in progress
2. Read [`docs/plugin-development.md`](docs/plugin-development.md)
3. Implement `app/printer_models/<your_model>.py` against the `PrinterModel` protocol
4. Add tests in `tests/unit/printer_models/test_<your_model>.py`
5. If you have hardware: add an integration test under `tests/hardware/`
6. Open a PR — title `feat(printer-models): add <Model> plugin`

We try to verify each plugin against real hardware before merging when feasible. If you're contributing a plugin for hardware we don't have access to, we'll merge based on tests + your hardware confirmation.

## Local CI checks

Before opening a PR, run from `backend/`:

```bash
ruff check .                  # linting (blocking in CI)
ruff format --check .         # formatting (blocking in CI)
mypy app/                     # type checking (blocking in CI — strict mode)
pytest                        # tests (blocking in CI)
```

The CI workflow runs the same. **All four are hard gates** — no warn-only:

- `ruff check` and `ruff format --check` reject style/lint issues
- `mypy` runs in strict mode (configured in `pyproject.toml` `[tool.mypy] strict = true`); type-check failures fail the build
- `pytest` requires all tests pass; coverage floor is 80% (configured in `pyproject.toml`)

If you want to bypass a gate locally during exploration, use `mypy --no-strict-optional` etc., but the merged code must pass strict checks.

PRs that fail any check won't be reviewed until green.

### Web UI: the on-screen keyboard

The hub is used on phones and tablets next to the printer. When a text field has the focus and the on-screen keyboard
is open, the field, its list and the main buttons of a dialog must stay in sight (or be reachable by scrolling inside
the dialog). Browsers shrink the page for the keyboard in two different ways, so a layout that works in one can be wrong
in the other:

- Chromium resizes the layout viewport (`interactive-widget=resizes-content` in `frontend/index.html`); `dvh` follows it.
- iOS Safari and older browsers only shrink `window.visualViewport`; `vh`, `dvh` and `fixed` boxes keep the full height.

So, in `frontend/`:

- Size anything that must stay in sight with `var(--vvh)` (visible height) and `var(--vv-top)` (its offset), published by
  `src/shell/viewport.ts`, not with `vh`/`dvh`/`window.innerHeight`. `ModalDialog` already does: it is as tall as the
  visible area and scrolls inside itself, so use it for every dialog.
- A list or popover that opens beside a field measures against `readViewport()` and measures again while it is open
  (the keyboard usually comes up after the focus has opened the list); see `SheetTypeCombobox`.
- Check a new dialog, combobox or search field in `e2e/short-viewport.spec.ts`: it runs at 1280x500 and 390x400 and with
  a keyboard that only covers the visual viewport, and asserts that the field, the first option and the main buttons lie
  inside the visible area.

### Web UI: screenshots

The README shows generated screenshots (`docs/screenshots/`, one light and one dark file per view). A new UI feature gets
its screenshot in the same PR; an essential UI change updates the affected ones. To render them, run from `frontend/`:

```bash
pnpm screenshots
```

It builds the web UI, starts the e2e hub (`backend/tests/e2e_app.py`) on its fixtures and writes the PNGs; two runs on the
same sources give identical files. Set `E2E_PYTHON` to the backend interpreter (default `.venv/bin/python` in `backend/`).
The views and their file names are listed at the top of `frontend/e2e/readme-screenshots.spec.ts`; add a view there.
The files are not recompressed (so regeneration stays byte-identical); `scripts/check-screenshot-sizes.mjs`, run by
`pnpm screenshots`, fails when a file is over 300 KB.
The Screenshots workflow renders them on demand and opens a PR when they changed. It opens that PR with `GITHUB_TOKEN`,
and GitHub does not start other workflows for it: close and reopen the PR to run the checks.

## Dependencies and licences

Every dependency that ships in the container image has to carry a licence the project can redistribute. One file decides: [`licence-policy.yml`](licence-policy.yml) (JSON, which is valid YAML). It holds the allow list (`allow-licenses`) and the reviewed exceptions (`x-licence-exceptions`). Every check reads this file.

| Check | What it judges | Required to merge |
|---|---|---|
| `Dependency review` (workflow *Licence gate*) | Dependencies a pull request **adds or changes**, against the allow list (`actions/dependency-review-action`) | Yes, once the repository ruleset is in place |
| *Licences — backend runtime* | The Python packages `pip install ./backend` resolves. Runs only when `backend/pyproject.toml`, the policy or `backend/scripts/licence_report.py` change | No — Python has no lockfile, so the result depends on what PyPI serves that day |
| Image build (`backend/Dockerfile`, `builder` stage) | The packages that are **installed into the image**. A violation fails the build | Part of the image build |

To run the backend check locally:

```bash
python -m venv /tmp/rt && /tmp/rt/bin/pip install ./backend
python -m venv /tmp/tool && /tmp/tool/bin/pip install pip-licenses==5.5.5
cd backend && /tmp/tool/bin/python -m scripts.licence_report \
  --python /tmp/rt/bin/python --policy ../licence-policy.yml
```

It prints every package the policy refuses as `name (licence)` and exits 1.

**A new dependency whose licence is on the list needs nothing.** If a gate refuses a package whose real licence is acceptable (package metadata that is wrong, ambiguous or missing), add an exception to `x-licence-exceptions` in the same pull request:

```json
{"purl": "pkg:pypi/example", "licence": "BSD-3-Clause", "reason": "Metadata says UNKNOWN; the licence file is the BSD 3-clause text."}
```

- `licence` is the SPDX expression the package really carries, taken from its licence file, and it has to pass the allow list. `reason` says what is wrong with the metadata.
- PyPI purls carry no version (there is no lockfile). npm purls carry the exact version. A PyPI exception applies while the package declares no `License-Expression` at all. If the package declares one that cannot be used as it stands (a non-SPDX id, a `LicenseRef-…`), record that exact string as `reviewed_expression` in the exception; the exception then applies only to that string. A release that declares anything else is judged as declared, and the report says "exception reviewed against X, package now declares Y".
- For an npm package that the dependency graph mis-reports, or reports with no licence at all, also add the purl to `allow-dependencies-licenses`. A test requires an exception with a reason for every purl there. `Dependency review` fails on a dependency whose licence cannot be detected, so such a package is never let through unread.

A licence that is **not** on the allow list is not an exception to add quietly: it is a decision about what the project may redistribute. Open an issue first. `GPL-2.0-only` and `LGPL-2.0-only` are left out on purpose (incompatible with AGPL-3.0), as is anything non-free.

## Milestones, branches and releases

Patch releases come from `main`. Minor and major releases come from a **milestone**: an integration branch `milestone/x.y.0` that collects the features of version `x.y.0` and is merged into `main` as one pull request. Releases are still made from `main` only — a milestone ships by merging `milestone/x.y.0` into `main`, never from the milestone branch itself. The decision and its reasons are in [ADR 0025](docs/decisions/0025-milestone-branches-for-minor-and-major-releases.md).

| Change | Branch from | PR targets | Merge style | Released as |
|---|---|---|---|---|
| Feature (`feat`) | `milestone/x.y.0` | `milestone/x.y.0` | squash | part of `x.y.0` |
| Breaking change (`!`, `BREAKING CHANGE:`) | `milestone/x.0.0` | `milestone/x.0.0` | squash | part of `x.0.0` |
| Bug or security fix (`fix`, `perf`) | `main` | `main` | squash | next nightly patch release |
| Docs, CI, chore, refactor, tests | `main` (or the milestone if it belongs to one) | same | squash | not released on its own |
| Milestone | — | `milestone/x.y.0` → `main` | **merge commit** | exactly `x.y.0` |
| Patch milestone | — | `milestone/x.y.x` → `main` | **merge commit** | next free patch `x.y.Z` |
| Sync after a fix | — | `main` → `milestone/x.y.0` | **merge commit** | — |

**Starting a milestone.** A maintainer opens the GitHub milestone `x.y.0` and creates `milestone/x.y.0` from `main`. CI, commitlint, CodeQL and the licence checks run for pull requests into `milestone/**` just as for `main`. Major versions only come through a milestone `x.0.0`.

**Shipping a milestone.** Open one PR `milestone/x.y.0` → `main` and merge it with a **merge commit**, never squash or rebase. A merge commit keeps every feature commit, so semantic-release computes exactly `x.y.0` at the next release run and the changelog lists each entry. After the release, close the GitHub milestone.

**Patch milestones `x.y.x`.** A group of fixes and hardening for a release line is collected in a patch milestone titled `x.y.x` (branch `milestone/x.y.x`). The title covers every patch `x.y.Z` with `Z >= 1`: the milestone PR gets the next free patch number when it is merged, because Dependabot updates and single fixes may already have released `x.y.1`, `x.y.2` on the way. Such a milestone takes only `fix`, `perf`, `refactor`, `test`, `docs`, `ci`, `chore` and `build` commits; a `feat`, `!` or `BREAKING CHANGE:` belongs in a minor milestone `x.y.0` and fails the `release-impact` check here. Dependabot PRs and single fixes go to `main` at any time, no pauses. Only a `fix` or `perf` commit causes a release (Dependabot commits are `chore(deps)` / `ci(deps)` and do not). After every patch release from `main`, merge `main` back into the milestone branch (the sync PR below).

**A release that merges a milestone closes it.** When a release contains the merge of `milestone/<title>`, that GitHub milestone must have no open issue at release time. Close the issues, move them to another milestone, or have a **maintainer** label an issue `release:waived-by-maintainer` to accept that it stays open; the label is never set by a bot or by the author of the change, and every waived issue is named in the release log (`::warning::release proceeds with waived issues: #…`) and the job summary. Open pull requests in the milestone do not count. A release **without** a milestone merge (Dependabot, a single fix) never looks at a milestone. After the release, close the GitHub milestone.

**Fixes while a milestone is open.** Fixes go to `main` and ship as nightly patch releases. When `main` moves, the [Milestone sync](.github/workflows/milestone-sync.yml) workflow opens a PR `main` → `milestone/x.y.0` (`chore: sync main into milestone/x.y.0`) for every milestone branch that does not contain `main` yet. Merge it with a merge commit. The workflow opens these PRs with `GITHUB_TOKEN`, and GitHub does not start other workflows for them: close and reopen the PR to run the checks.

**Preview images.** Before a milestone is released, a maintainer can build a preview image from the milestone branch with the **Preview image** workflow (Actions → Preview image → Run workflow, branch `milestone/x.y.0`, version `x.y.0`). Each run publishes the next tag `x.y.0-rc.N` to GHCR only:

```bash
docker pull ghcr.io/strausmann/label-printer-hub-backend:1.5.0-rc.1
```

A preview is not a release: it gets no Git tag, no GitHub Release, no changelog entry, no `latest` / `x.y` / `x` tags and nothing on Docker Hub. Previews are removed from GHCR once their release exists.

For a patch milestone `x.y.x` use version `x.y.x`: the workflow builds `x.y.<next free patch>-rc.N`. A weekly **GHCR cleanup** run prunes the package to the releases from 1.4.0, their floating tags, `dev` and open previews, and never touches anything younger than a day. It only deletes when the repository variable `GHCR_CLEANUP_ENABLED` is `true`; a manual run defaults to dry-run. Cleanup and preview runs share one concurrency group, so they never overlap, and a newer queued run replaces an older *pending* one: a skipped cleanup or preview run is expected, so re-dispatch it if needed. The rules live in `scripts/ghcr_rules.py` (tests: `scripts/test_ghcr_rules.py`).

**Two guards keep the numbering honest.**

1. The **`release-impact`** check runs on every pull request into `main`. It classifies the PR title (used by a squash merge) and every commit (kept by a merge commit) with the release rules of `.releaserc.json`. From any branch other than `milestone/*` only patch-level or non-releasing changes pass; a `feat`, `!` or `BREAKING CHANGE:` fails and names the milestone branch to target instead. From `milestone/x.y.z` the last release plus the highest impact must equal `x.y.z`, and the GitHub milestone `x.y.z` must be open; from `milestone/x.y.x` it must be a patch `x.y.Z` (a minor or major change fails) and the milestone `x.y.x` must be open. The job summary lists each commit with its impact.
2. The **release guard** runs inside the release itself (`verifyReleaseCmd` in `.releaserc.json`), before anything is tagged or published. The version semantic-release computed must be the next patch of the last release or covered by the title of an open GitHub milestone (`x.y.0` covers itself, `x.y.x` every patch `x.y.Z`, `Z >= 1`). Otherwise the run stops, nothing is released, and an issue `release blocked: computed <version>` is opened. For a minor or major version the guard also checks provenance: the releasing range must contain the merge `Merge pull request #<n> from <owner>/milestone/<version>` on the first-parent line of `main`, and every `feat`, breaking or other above-patch commit must have come in through that merge (a `feat` pushed to `main` and then synced into the milestone does not count). This catches what the PR check cannot see, such as a direct push to `main`. If the releasing range contains a milestone merge (`Merge pull request #<n> from <owner>/milestone/<title>` on the first-parent line), the title must cover the computed version and the milestone must have no open issue except `release:waived-by-maintainer` ones (see above); an API error blocks the release rather than letting it through.

Both use [`scripts/release_impact.py`](scripts/release_impact.py) (tests: `python3 -m unittest discover -s scripts -p 'test_*.py'`).

To see which version semantic-release would compute for a commit message, without publishing anything, run `scripts/release_dry_run.sh "fix: x"` (after `npm ci --ignore-scripts` in `.github/release-tools`); `scripts/release_dry_run.sh --all` replays every sample message of the impact tests and compares the result with `release_impact.py`. The **Release tools** workflow (check `release-tools dry run`) runs `--all` and `--notes` on every PR and push to `main` or `milestone/**`; it does the work only when `.github/release-tools`, `.releaserc.json` or the release scripts changed and otherwise passes at once, so it can be a required check without blocking unrelated PRs.

## Releases

Releases are **scheduled, not on every merge.** Merging to `main` does NOT publish a release — it only bundles changes for the next scheduled release window. Releases are made from `main` only; which changes may reach `main` is described in [Milestones, branches and releases](#milestones-branches-and-releases).

| Trigger | When |
|---|---|
| `cron: '0 4 * * *'` | Nightly at 04:00 UTC. semantic-release analyses commits since the last tag and publishes if there's anything releasable, otherwise skips silently |
| `workflow_dispatch` | Manual button in the Actions tab. Optional `dry-run` input lets a maintainer preview what would be released without publishing |

The release tooling (semantic-release and its plugins, pinned to exact versions with a lockfile) lives only in `.github/release-tools/`; `release.yml` installs it from there. The root `package.json` holds only commitlint.

Behind the scenes, semantic-release reads the Conventional Commit messages on `main` since the previous tag, decides the next semver version, checks it against the release guard (next patch or an open milestone), generates the `CHANGELOG.md` entry, creates the Git tag and GitHub Release, and triggers the Docker image push to GHCR and Docker Hub.

**A scheduled run only skips publishing when there are no releasable commits since the last tag.** semantic-release evaluates the entire history since the previous release, not just "today's" commits. If a `feat`, `fix`, or `perf` commit is already on `main` from an earlier merge, the next scheduled run **will** publish — adding a `chore` or `docs` commit on top doesn't suppress that. To genuinely skip a release window, the only options are: rely on there being no releasable commits, or postpone merges that would bump the version. A milestone is released at the first release run after its PR is merged.

Maintainers do not manually tag releases. If a hotfix needs to ship before the next scheduled window, use the **Run workflow** button on the Release workflow in the Actions tab. The dry-run input lets a maintainer preview which version would be published before committing.

## Trademarks

Please remember Brother trademarks are the property of Brother Industries, Ltd. (see [README](README.md#trademarks-and-disclaimer)). Don't add wording that suggests endorsement, partnership, or affiliation with Brother Industries, Ltd.
