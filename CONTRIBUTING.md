# Contributing to Label Printer Hub

Thanks for your interest in contributing! This document explains how to participate effectively.

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). By participating, you agree to abide by its terms.

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

Frontend: see [`docs/architecture.md`](docs/architecture.md) once finalised.

### 3. Create a branch

Branch naming follows Conventional Commits prefix:

| Prefix | Use for |
|---|---|
| `feat/` | New feature |
| `fix/` | Bug fix |
| `docs/` | Documentation only |
| `refactor/` | Code change without behaviour change |
| `test/` | Test additions/changes |
| `chore/` | Tooling, deps, CI |
| `perf/` | Performance |
| `ci/` | CI changes only |

Example: `git checkout -b feat/ptouch-tape-detection`.

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

We squash-merge by default. The squash commit message **must** follow Conventional Commits — semantic-release will use it.

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

## Releases

Releases are **scheduled, not on every merge.** Merging to `main` does NOT publish a release — it only bundles changes for the next scheduled release window.

| Trigger | When |
|---|---|
| `cron: '0 4 * * *'` | Nightly at 04:00 UTC. semantic-release analyses commits since the last tag and publishes if there's anything releasable, otherwise skips silently |
| `workflow_dispatch` | Manual button in the Actions tab. Optional `dry-run` input lets a maintainer preview what would be released without publishing |

Behind the scenes, semantic-release reads the Conventional Commit messages on `main` since the previous tag, decides the next semver version, generates the `CHANGELOG.md` entry, creates the Git tag and GitHub Release, and triggers the Docker image push to GHCR and Docker Hub.

**A scheduled run only skips publishing when there are no releasable commits since the last tag.** semantic-release evaluates the entire history since the previous release, not just "today's" commits. If a `feat`, `fix`, or `perf` commit is already on `main` from an earlier merge, the next scheduled run **will** publish — adding a `chore` or `docs` commit on top doesn't suppress that. To genuinely skip a release window, the only options are: rely on there being no releasable commits, or postpone merges that would bump the version.

Maintainers do not manually tag releases. If a hotfix needs to ship before the next scheduled window, use the **Run workflow** button on the Release workflow in the Actions tab. The dry-run input lets a maintainer preview which version would be published before committing.

## Trademarks

Please remember Brother trademarks are the property of Brother Industries, Ltd. (see [README](README.md#trademarks-and-disclaimer)). Don't add wording that suggests endorsement, partnership, or affiliation with Brother Industries, Ltd.
