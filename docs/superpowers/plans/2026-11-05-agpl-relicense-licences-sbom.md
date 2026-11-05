# AGPL Relicensing, Licence Gate, Licence List and SBOM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The hub is licensed AGPL-3.0-or-later from release 1.1.0 on, links every user to the source of the running build, blocks new dependencies with incompatible licences, shows every shipped third-party licence in the product and publishes a complete SBOM with every image.

**Architecture:** Two parts, two releases. **Part A** (release 1.1.0) fixes the release image build (#183), adds the licence gate, extends `GET /api/info` with licence and source URL, adds an About page and source links, and swaps the licence in one `chore(license)` commit. **Part B** (release 1.2.0) generates the backend and frontend licence lists from what the image really ships, shows them on the About page, embeds a CycloneDX SBOM of the web bundle, turns provenance to `mode=max`, checks the image in CI and attaches a CycloneDX SBOM to each GitHub release.

**Tech Stack:** FastAPI/Pydantic (backend), React 19 + TanStack Router/Query + Lingui (web), Vite 8 + `rollup-license-plugin` 3.2.1, `pip-licenses` 5.5.5 (build-time tool venv only), Docker Buildx/BuildKit attestations, Syft (`anchore/sbom-action/download-syft@v0.24.3`), `actions/dependency-review-action@v5`, semantic-release.

**Spec:** https://github.com/strausmann/Label-Printer-Hub/issues/154 (plus #183 for the release image build). Not legal advice; the plan implements the issue, it does not re-litigate it.

## Findings that shaped the plan (checked 2026-11-05)

- **CLA — no blocker.** `CLA.md` §1 grants the Maintainer a perpetual, irrevocable licence to "sublicense, and distribute Your Contributions", §5 says the Maintainer "may license the Contribution under any license … at the Maintainer's discretion". Authors in `git log`: the Maintainer (209 commits), `semantic-release-bot` (21, release commits), `dependabot[bot]` (16, lockfile/version bumps). `Co-authored-by` trailers name no other human. GitHub's contributor list and all 84 merged PRs show no other human. Nothing needs consent; §5's example sentence ("the MIT License under which the Project is currently distributed") is updated in Task A5.
- **No branch protection, no rulesets** on `main` today (`gh api …/branches/main/protection` → 404, `…/rulesets` → empty). A "required" check therefore needs a new ruleset (Task A7).
- **`docker-publish.yml` already sets `sbom: true` and `provenance: true`.** Part B changes provenance to `mode=max` and verifies what the attestation actually contains.
- **Brother PDFs:** no PDF has ever been committed (`git log --all -- '*.pdf'` is empty) and none is in the image. The README sentence about "fair use" describes files that do not exist; it is deleted and the existing links to Brother's download pages (README line 18) stay. Nothing else to do.
- **`.dockerignore` excludes `.github/`**, so a licence policy the Docker build reads cannot live there (→ `licence-policy.yml` at the repo root).
- **Squash merge is the default** (`CONTRIBUTING.md`), rebase merge is enabled. The Part A release PR must land as individual commits (Orchestrator's call 3).
- **Called workflows see the caller's `github.sha`.** When `release.yml` calls the image build, `github.sha` is the commit *before* semantic-release's `chore(release)` commit and tag. The build must check out the tag.

## Orchestrator's calls

1. **No major release (coordinator ruling after the operator's question).** The licence change is not a breaking change for operators: no API, configuration or data change. The relicensing commit is `chore(license): relicense to AGPL-3.0-or-later` **without** `!` and **without** a `BREAKING CHANGE` footer; it ships together with the `feat(api)`/`feat(ui)` commits of Tasks A3/A4, which trigger a **minor** release (1.1.0). README and CHANGELOG state: "Releases up to and including 1.0.2 are MIT; from 1.1.0 on AGPL-3.0-or-later." `.releaserc.json` maps `chore` → no release, `feat` → minor, `breaking` → major; Task A6 proves the computed version before the nightly run.
2. **#183 is fixed in this plan (Task A1), not worked around by hand.** 1.1.0 is the first AGPL release; it must have images, and from Part B on the release SBOM asset is produced by the same run. `release.yml` calls `docker-publish.yml` via `workflow_call` with the version; no extra secret (the issue's preferred option).
3. **The Part A release PR (Tasks A3–A5) is merged with "Rebase and merge"**, so `chore(license)` stays its own commit and the `feat` commits land beside it in one push. All other PRs keep squash merge.
4. **Licence policy lives in `licence-policy.yml` at the repo root** (dependency-review `config-file`, read by the backend licence script and copied into the Docker build). One list, three consumers.
5. **Allowed licences (SPDX):** `0BSD`, `AGPL-3.0-only`, `AGPL-3.0-or-later`, `Apache-2.0`, `BlueOak-1.0.0`, `BSD-2-Clause`, `BSD-3-Clause`, `BSL-1.0`, `CC-BY-4.0`, `CC0-1.0`, `GPL-2.0-or-later`, `GPL-3.0-only`, `GPL-3.0-or-later`, `HPND`, `ISC`, `LGPL-2.0-or-later`, `LGPL-2.1-only`, `LGPL-2.1-or-later`, `LGPL-3.0-only`, `LGPL-3.0-or-later`, `MIT`, `MIT-CMU`, `MPL-2.0`, `OFL-1.1`, `PSF-2.0`, `Python-2.0`, `Unlicense`, `Zlib`. Deliberately absent: `GPL-2.0-only` and `LGPL-2.0-only` (incompatible with AGPL-3.0), anything non-free (`BUSL-1.1`, `SSPL-1.0`, `Elastic-2.0`, `CC-BY-NC-*`, Commons Clause).
6. **Dependency review checks runtime scope only and no vulnerabilities** (`fail-on-scopes: [runtime]`, `vulnerability-check: false`). The gate is about licences; vulnerabilities have Dependabot/CodeQL. A gate that turns red on a second topic gets overridden.
7. **Python has no lockfile**, so dependency review sees only direct `pyproject.toml` deps. A second job, `Licences — backend runtime`, installs the runtime deps into a clean venv and checks every installed distribution (transitive included) against the same policy.
8. **Ruleset bypass:** repository admins (`RepositoryRole` 5) and the GitHub Actions app (`Integration` 15368, checked with `gh api /apps/github-actions`) bypass with `always`. Without the app bypass, semantic-release's direct push of `chore(release)` would be blocked; without the admin bypass, the Maintainer's direct pushes of docs commits to `main` would be blocked. Dependabot and external PRs are blocked. (Open question 1 to the operator.)
9. **The ruleset is created last (Task A7), after 1.1.0 is published**, so the release that proves #183 cannot be blocked by a misconfigured ruleset; the release after it proves the bypass.
10. **No SPDX headers in source files now.** The issue marks them optional; 300+ touched files would collide with the running sheet-archive branches. `LICENSE`, metadata and labels carry the licence.
11. **The §13 source link points at the exact build:** semver release → `<repo>/tree/v<version>`, otherwise a commit SHA → `<repo>/tree/<sha>`, otherwise the repo root. `HUB_REPO_URL` stays overridable so a modified, self-hosted fork can point at its own source (README says so). Only `http`/`https` URLs are accepted; anything else falls back to the canonical repo.
12. **The About page is a top-level route `/about` for every signed-in user**, not a settings section: settings are admin-only, but §13 covers every user. Links: sidebar footer (desktop), an icon link in the top bar (all widths, so phones reach it), the System settings page, and a plain "Source code" link on the sign-in screen (`/api/info` is public).
13. **Release SBOM asset is produced by the image workflow, not by semantic-release's `assets`.** semantic-release publishes the release *before* the image exists; an SBOM must describe the published image. The asset is `label-printer-hub-<version>.cdx.json`, made by Syft with `+sbom-cataloger` from the pushed multi-arch tag.
14. **Frontend CycloneDX is generated from the licence plugin's package list** (its `additionalFiles` hook), not with a second tool: same package set as the bundle, no dev tooling, no extra dependency. `@cyclonedx/cyclonedx-npm` needs npm's tree, the web app uses pnpm.
15. **`BUILDKIT_SBOM_SCAN_STAGE` is not enabled.** It would scan `web-builder` with its full `node_modules` (dev tooling) and `builder` with `build-essential` — an inventory of things the image does not ship. The embedded `frontend.cdx.json` plus the Syft release asset cover the web bundle; Spike S2 records what the BuildKit attestation contains, and the README says it plainly.
16. **Decision labels:** `D20` (AGPL-3.0-or-later, source link of the running build) in Task A3, `D21` (licence lists and SBOM come from the shipped artefacts) in Task B1. The sheet-archive branches use D13–D19; their next free label is D22.
17. **Specs carrying "MIT project" are corrected in the relicensing commit** (`docs/superpowers/specs/2026-11-05-sheet-archive-design.md` line 67, `docs/superpowers/specs/2026-11-03-web-ui-redesign-design.md` lines 34 and 235). `feat/sheet-archive-1` does not touch the spec (`git diff --stat origin/main...origin/feat/sheet-archive-1`), so no conflict. The sheet-archive **plans** only name MIT/BSD licences of dependencies (gLabels-qt, reportlab, charset-normalizer) — correct under AGPL, left alone; their new dependencies are on the allow list.
18. **CHANGELOG note after the release** (Task A6): semantic-release owns `CHANGELOG.md` and hides `chore` commits, so the licence sentence is added under the 1.1.0 heading by a `docs(release)` commit right after publication, and prepended to the GitHub release notes with `gh release edit`.

## Open questions to the operator (each has a default)

1. **Should the licence gate block you as well?** Default: no — admin bypass (call 8). Otherwise direct pushes to `main` stop working and every docs fix needs a PR.
2. **Merge order with the sheet archive.** If any sheet-archive `feat` PR lands on `main` before the Part A release PR, that `feat` ships as 1.1.0 under MIT and AGPL becomes 1.2.0. Default: hold sheet-archive merges until 1.1.0 is published (Part A is about a day of work).

## Global Constraints

- Prose in code, docs, commits and PRs: **English**; UI copy in **en and de** (British English: "Licence" as noun, `AGPL-3.0-or-later` as SPDX id).
- Conventional Commits; `license` is added to `scope-enum` in Task A1. **No commit of this series contains `!:` or a `BREAKING CHANGE`/`BREAKING-CHANGE` footer.**
- No AI attribution and no internal infrastructure names in commits, PRs or files (public repo).
- TDD: test first, run it red, implement, run it green, commit. Every new test is checked once against the unfixed code (Gegenversuch) as named in its task.
- No new **runtime** dependency. Build-time only: `rollup-license-plugin@3.2.1` (MIT, exact pin in `frontend/package.json` devDependencies) and `pip-licenses==5.5.5` (MIT, installed into a throwaway tool venv in the Docker `builder` stage and in CI, never into `/opt/venv`). Both are named with their licence in the PR description.
- Image stays non-root UID 1000; no CDN; CSP in `backend/app/web/spa.py` unchanged; licence JSON files are **not** precached by the service worker (`pwa.config.ts` `globPatterns` has no `json` — keep it).
- `GET /api/info` stays public and secret-free: only constants, build info and booleans.
- Actions keep the repo's major-tag convention (`@v5`, `@v7`); `download-syft` pinned to `v0.24.3`, Syft `v1.55.0` (the version the issue tested).
- Coverage gates stay: backend `--cov-fail-under=80`, web 70 %.

## Review Focus

1. **Release image built from the wrong commit.** Under `workflow_call` `github.sha` is the pre-release commit; the image for `v1.1.0` must be built from the tag and its `org.opencontainers.image.revision` must equal `git rev-list -n1 v1.1.0`. → Task A1 Step 4 (dispatch check) and Task A6 Step 4.
2. **Source link that leads nowhere or somewhere unsafe.** Dev/branch images, `0.0.0-dev`, `revision=unknown`, a fork's `HUB_REPO_URL` with `.git`/trailing slash, or a `javascript:` value must give a working `http(s)` link. → Task A3 `test_source_url_*` table.
3. **Licence data missing or hostile.** API-only image, Vite dev server, a 404, a 2 MB list, licence texts containing `<script>`: the About page still shows project licence and source link, shows a message for the missing list, renders texts as text, and mounts a text only when expanded. → Task A4 and Task B3 tests.
4. **Accidental version jump.** A stray `!`, a `BREAKING CHANGE` footer in a commit body, or a squash merge that drops the `feat` type would give 2.0.0 or no release. → Task A6 Steps 1–2 (history grep + release dry run expecting `1.1.0`).
5. **Gate red for a non-defect.** A PR that changes no dependency, a Dependabot bump of an allowed package, or a dependency with a known vulnerability must stay green; the check must run on **every** PR (no `paths:` filter), or the ruleset blocks PRs that never produce it. → Task A2 Step 6 and Task A7 Steps 3–5.

---

## Part A — Release 1.1.0

### Task A1: Release images from the release workflow (#183) and the `license` scope

**Files:**
- Modify: `.github/workflows/docker-publish.yml`, `.github/workflows/release.yml`, `commitlint.config.cjs`

**Interfaces:**
- Produces: `docker-publish.yml` callable with `workflow_call: inputs: tag: {type: string, required: true}`; job outputs unchanged. Later tasks (B6) add a job to this workflow that reads `inputs.tag`.

- [ ] **Step 1: Write the check** — `actionlint` on both workflows must pass (`docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:1.7.7 -color`). Before the change it passes too; the behavioural check is Step 4.
- [ ] **Step 2: Implement**
  - `docker-publish.yml`: add `workflow_call` with input `tag`; remove the `release: published` trigger (it never fires for `GITHUB_TOKEN` releases and would double-build with an app token). In both "Determine flavor and tag" steps the rule becomes: `INPUT_TAG` non-empty → `release` (covers `workflow_dispatch` and `workflow_call`), else default branch → `dev`, else `branch`. For `release` flavor, `actions/checkout@v6` uses `ref: v<tag>` (input without `v`), and `REVISION`/`org.opencontainers.image.revision` come from `git rev-parse HEAD` after checkout, never from `github.sha`.
  - `release.yml`: new job `images` with `needs: release`, `if: needs.release.outputs.new-release-published == 'true'`, `uses: ./.github/workflows/docker-publish.yml`, `with: tag: ${{ needs.release.outputs.new-release-version }}`, `secrets: inherit`, `permissions: {contents: write, packages: write, id-token: write}` (`contents: write` is for Task B6).
  - `commitlint.config.cjs`: add `'license'` to `scope-enum`.
- [ ] **Step 3: Run actionlint** — Expected: no findings.
- [ ] **Step 4: Gegenversuch on the branch** — push the branch, then `gh workflow run docker-publish.yml --ref ci/release-images -f tag=1.0.2`. Expected: run green; `docker buildx imagetools inspect ghcr.io/strausmann/label-printer-hub-backend:1.0.2 --format '{{json .Image}}' | jq -r '.["linux/amd64"].config.Labels["org.opencontainers.image.revision"]'` equals `git rev-list -n1 v1.0.2` (not the branch head). This republishes 1.0.2 from its own tag; `latest` already points at 1.0.2.
- [ ] **Step 5: Commit** — `git add .github/workflows/docker-publish.yml .github/workflows/release.yml commitlint.config.cjs && git commit -m "ci(release): build release images from the release workflow" -m "Refs #183" -m "Refs #154"`; PR, squash merge. #183 is closed in Task A6 once 1.1.0 has images.

### Task A2: Licence gate for new dependencies

**Files:**
- Create: `licence-policy.yml`, `.github/workflows/licence-gate.yml`, `backend/scripts/licence_report.py`, `backend/tests/unit/scripts/__init__.py`, `backend/tests/unit/scripts/test_licence_report.py`
- Modify: `.github/workflows/ci.yml` (new job), `CONTRIBUTING.md` (section "Dependencies and licences")

**Interfaces:**
- Produces (`backend/scripts/licence_report.py`, used again in Task B1):
  - `def load_policy(path: Path) -> frozenset[str]` — the `allow-licenses` list.
  - `def classify(entry: Mapping[str, str]) -> tuple[str, bool]` — one pip-licenses `--from=all` record → (`licence`, `allowed`). Order: a valid SPDX expression in the expression field; else the classifier mapped through `CLASSIFIER_TO_SPDX`; else the metadata string mapped through `METADATA_TO_SPDX`; else `("UNKNOWN", False)`. Expressions: `OR` → allowed if any alternative is allowed; `AND` → allowed if all terms are; `WITH <exception>` is judged by its licence.
  - `OVERRIDES: dict[str, tuple[str, str]]` — `name → (SPDX, reason)` for packages whose metadata is wrong; empty unless Spike S3 finds one.
  - `def check(entries: Sequence[Mapping[str, str]], allowed: frozenset[str]) -> list[str]` — names of disallowed packages, sorted.
  - CLI: `python -m scripts.licence_report --python <interpreter> --policy <file> [--output <json>]` runs `pip-licenses --python <interpreter> --from=all --format=json --with-license-file --no-license-path`, excludes `label-printer-hub-backend`, exits 1 and prints `name (licence)` per line for each disallowed package. `--output` is used in Task B1.
- `licence-policy.yml` keys: `allow-licenses` (call 5), `fail-on-scopes: [runtime]`, `license-check: true`, `vulnerability-check: false`.

- [ ] **Step 1: Write the failing tests** (`test_licence_report.py`, fixtures are hand-written dicts, no network):
  - `test_policy_lists_agpl_gpl_lgpl` — `load_policy(repo_root / "licence-policy.yml")` contains `AGPL-3.0-or-later`, `GPL-3.0-or-later`, `LGPL-2.1-or-later`, `MIT`, `Apache-2.0`, `BSD-3-Clause`, and does **not** contain `GPL-2.0-only`.
  - `test_classify_expression_or` — `"Apache-2.0 OR BSD-3-Clause"` → allowed; `"GPL-2.0-only OR Proprietary"` → not allowed.
  - `test_classify_expression_and` — `"MIT AND PSF-2.0"` → allowed; `"MIT AND SSPL-1.0"` → not.
  - `test_classify_classifier_fallback` — no expression, classifier `License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)` → `("GPL-3.0-or-later", True)`.
  - `test_classify_unknown_is_refused` — metadata `"UNKNOWN"`, no classifier → `("UNKNOWN", False)`; metadata `"Proprietary"` → not allowed.
  - `test_classify_known_shipped_packages` — records shaped like brother-ql (classifier GPLv3+) → `GPL-3.0-or-later`; ptouch (`LGPL-2.1-or-later`) → allowed; pillow (`MIT-CMU`) → allowed.
  - `test_check_lists_offenders_sorted` — two disallowed, one allowed → the two names, sorted.
- [ ] **Step 2: Run** `cd backend && pytest tests/unit/scripts/test_licence_report.py -v` — Expected: FAIL (module missing).
- [ ] **Step 3: Spike S3a (15 min)** — in a scratch venv: `pip install /path/to/backend` then `pipx run pip-licenses==5.5.5 --python <venv>/bin/python --from=all --format=json | jq -r '.[] | keys'` once, and list the distinct licence/classifier strings. Fill `CLASSIFIER_TO_SPDX`/`METADATA_TO_SPDX` with exactly the strings seen plus the ones in the tests; record the field names pip-licenses emits in the module docstring.
- [ ] **Step 4: Implement** `licence_report.py`, `licence-policy.yml`, then:
  - `.github/workflows/licence-gate.yml`: `on: pull_request: branches: [main]` (no `paths:`), `permissions: contents: read`, job `dependency-review` named **`Dependency review`**: checkout, `actions/dependency-review-action@v5` with `config-file: ./licence-policy.yml`.
  - `ci.yml`: job named **`Licences — backend runtime`** (on the existing push + pull_request triggers): setup-python 3.12, `python -m venv /tmp/rt && /tmp/rt/bin/pip install ./backend`, `python -m venv /tmp/tool && /tmp/tool/bin/pip install pip-licenses==5.5.5 pyyaml`, then `cd backend && /tmp/tool/bin/python -m scripts.licence_report --python /tmp/rt/bin/python --policy ../licence-policy.yml`.
  - `CONTRIBUTING.md`: the allow list lives in `licence-policy.yml`; a dependency outside it needs a policy change with a reason in the PR.
- [ ] **Step 5: Run** the unit tests (PASS) and the CLI locally against a venv with the backend installed. Expected: exit 0, no output. Gegenversuch: run it with a policy copy that lacks `GPL-3.0-or-later` → exit 1, prints `brother-ql (GPL-3.0-or-later)`.
- [ ] **Step 6: Verify on the PR** — the PR's own checks show `Dependency review` and `Licences — backend runtime` green. Gegenversuch: a throwaway draft PR from a branch that adds one **runtime** npm dependency whose licence deps.dev reports outside the list (the implementer picks it and records name and licence in the Task A7 notes) → `Dependency review` red naming that package; a second throwaway PR that only edits a Markdown file → `Dependency review` green. Close both, delete the branches.
- [ ] **Step 7: Commit** — `git add licence-policy.yml .github/workflows/licence-gate.yml .github/workflows/ci.yml backend/scripts/licence_report.py backend/tests/unit/scripts CONTRIBUTING.md && git commit -m "ci(security): licence gate for new dependencies" -m "Refs #154"`; PR, squash merge.

### Task A3: Licence and source link in `GET /api/info`

**Files:**
- Create: `backend/app/build_info.py`, `backend/tests/unit/test_build_info.py`
- Modify: `backend/app/schemas/info.py`, `backend/app/api/routes/info.py`, `backend/tests/integration/api/test_info.py`, `frontend/src/api/schema.gen.ts` (regenerated), `docs/decisions/register.md` (row `D20` "The hub is AGPL-3.0-or-later and links to the source of the running build", 2026-11-05, Accepted, ADR —)

**Interfaces:**
- Produces:
  - `PROJECT_LICENSE: Final = "AGPL-3.0-or-later"`, `CANONICAL_REPO_URL: Final = "https://github.com/strausmann/label-printer-hub"` in `build_info.py`.
  - `def source_url(repo_url: str, version: str, revision: str) -> str  # D20` — `repo_url` with scheme other than `http`/`https` or without host → `CANONICAL_REPO_URL`; strip a trailing `/` and `.git`; `version` matching `^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$` and not starting with `0.0.0-` → `<repo>/tree/v<version>`; else `revision` matching `^[0-9a-f]{7,40}$` → `<repo>/tree/<revision>`; else `<repo>`.
  - `Info` gains `license: str` and `source_url: str`. Task A4 reads `info.license` and `info.source_url`.

- [ ] **Step 1: Write the failing tests**
  - `test_build_info.py::test_source_url` (parametrised; `R` = canonical URL, `SHA` = `"0123456789abcdef0123456789abcdef01234567"`):
    - `(R, "1.1.0", SHA)` → `R + "/tree/v1.1.0"`; `(R, "1.1.0-rc.1", SHA)` → `R + "/tree/v1.1.0-rc.1"`
    - `(R, "dev", SHA)` → `R + "/tree/" + SHA`; `(R, "feat-sheets", SHA)` → same
    - `(R, "0.0.0-dev", "unknown")` → `R`; `(R, "0.0.0-dev", SHA)` → `R + "/tree/" + SHA`
    - `("https://example.invalid/fork.git/", "1.1.0", SHA)` → `"https://example.invalid/fork/tree/v1.1.0"`
    - `("javascript:alert(1)", "1.1.0", SHA)` → `R + "/tree/v1.1.0"`; `("", "dev", "unknown")` → `R`
  - `test_info.py::test_info_shape` — key set gains `"license"` and `"source_url"`.
  - `test_info.py::test_info_license_and_source` — with `HUB_VERSION`-equivalent patched to `1.1.0` (patch `app.main.HUB_VERSION`, `HUB_REVISION`, `HUB_REPO_URL`): `license == "AGPL-3.0-or-later"`, `source_url == R + "/tree/v1.1.0"`; the response is served without a session (public).
- [ ] **Step 2: Run** `pytest tests/unit/test_build_info.py tests/integration/api/test_info.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** `build_info.py`; `get_info` imports `HUB_REPO_URL` lazily next to the others and fills both fields; add the `D20` row; `cd frontend && pnpm gen:api`.
- [ ] **Step 4: Run** the tests plus `pytest tests/unit/test_decision_register.py tests/api/test_openapi_completeness.py` — PASS. Gegenversuch: drop the scheme check → the `javascript:` case fails; drop the `0.0.0-` exclusion → the `0.0.0-dev` cases fail.
- [ ] **Step 5: Commit** — `git add backend/app/build_info.py backend/app/schemas/info.py backend/app/api/routes/info.py backend/tests/unit/test_build_info.py backend/tests/integration/api/test_info.py frontend/src/api/schema.gen.ts docs/decisions/register.md && git commit -m "feat(api): project licence and source link of the running build in /api/info" -m "Refs #154"`

### Task A4: About page and source links

Load the design skills first (`emil-design-eng`, `taste-skill:design-taste-frontend` in app-screen mode); match the existing settings/System look (`PANEL`, `Row`, `Section`), no new visual language.

**Files:**
- Create: `frontend/src/features/about/AboutPage.tsx`, `frontend/src/features/about/AboutPage.test.tsx`, `frontend/e2e/about.spec.ts`
- Modify: `frontend/src/app/router.tsx` (`page("/about", AboutPage)`), `frontend/src/shell/Sidebar.tsx` (+test), `frontend/src/shell/TopBar.tsx`, `frontend/src/shell/SignIn.tsx` (+test), `frontend/src/shell/icons.tsx` (an info icon), `frontend/src/features/settings/System.tsx` (link "About and licences"), `frontend/src/i18n/locales/{en,de}/messages.po`

**Interfaces:**
- Consumes: `useInfo().data.license`, `.source_url`, `.version`, `.revision` (Task A3).
- Produces: `export function AboutPage(): React.JSX.Element` with a section element `data-section="dependencies"` left empty here; Task B3 fills it. `export const AGPL_TEXT_URL = "https://www.gnu.org/licenses/agpl-3.0.html"`.

**Copy (en → de)**, every message with a `context` so a noun and an action never share an id: "About" (`context: "page title"`) → "Über"; "About and licences" (`context: "link to the about page"`) → "Über und Lizenzen"; "Licence" (`context: "heading"`) → "Lizenz"; "Source code" (`context: "link to the source of the running version"`) → "Quellcode" — never reuse the existing log-table "Source" message; "This hub is free software under the GNU Affero General Public License, version 3 or later. You can get the source of exactly this version at any time." → "Dieser Hub ist freie Software unter der GNU Affero General Public License, Version 3 oder neuer. Den Quellcode genau dieser Version erhalten Sie jederzeit."; "Read the licence" (`context: "action"`) → "Lizenz lesen".

- [ ] **Step 1: Write the failing tests**
  - `AboutPage.test.tsx::shows licence, version and source` — with info `{license: "AGPL-3.0-or-later", version: "1.1.0", revision: SHA, source_url: "https://github.com/strausmann/label-printer-hub/tree/v1.1.0"}`: text `AGPL-3.0-or-later`, `1.1.0`; link named "Source code" with that `href`, `rel` containing `noopener` and `noreferrer`; link "Read the licence" → `AGPL_TEXT_URL`.
  - `AboutPage.test.tsx::renders while info is loading` — no info yet → page renders with `…` placeholders and no link with an empty `href`.
  - `Sidebar.test.tsx::footer links to about and source` — link "About and licences" → `/about`; link "Source code" → `info.source_url`.
  - `SignIn.test.tsx::source link before sign-in` — "Source code" link present on the sign-in screen with `info.source_url`.
  - `e2e/about.spec.ts` — desktop: sign in, footer link opens `/about`, heading "About"; phone viewport (390×844): top-bar link "About and licences" opens `/about`.
- [ ] **Step 2: Run** `pnpm test src/features/about src/shell` — Expected: FAIL.
- [ ] **Step 3: Implement** the page, the route, the links (`// D20` on each source link), the System link, the messages; `pnpm i18n:extract`, translate de, `pnpm i18n:compile`.
- [ ] **Step 4: Run** `pnpm typecheck && pnpm lint && pnpm test:coverage && pnpm build && pnpm e2e` — PASS. Gegenversuch: give the source link a static `href` of the repo root → the About test fails on the `href`.
- [ ] **Step 5: Commit** — `git add frontend/src frontend/e2e/about.spec.ts && git commit -m "feat(ui): about page with licence and a link to the running version's source" -m "Refs #154"`

### Task A5: Relicense to AGPL-3.0-or-later

**Files:**
- Create: `backend/tests/unit/test_licence_metadata.py`
- Modify: `LICENSE`, `README.md`, `backend/README.md`, `CLA.md` (§5 example sentence), `backend/pyproject.toml`, `package.json`, `frontend/package.json`, `backend/Dockerfile` (label), `.github/workflows/docker-publish.yml` (labels + annotations, 2 places), `THIRD_PARTY_NOTICES.md` (line 3 only), `docs/superpowers/specs/2026-11-05-sheet-archive-design.md` (line 67), `docs/superpowers/specs/2026-11-03-web-ui-redesign-design.md` (lines 34, 235)

- [ ] **Step 1: Write the failing test** `test_licence_metadata.py` (reads repo files relative to the repo root):
  - `test_license_file_is_agpl` — sha256 of `LICENSE` is `0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0` (verbatim `https://www.gnu.org/licenses/agpl-3.0.txt`, 661 lines).
  - `test_package_metadata` — `backend/pyproject.toml` `project.license == "AGPL-3.0-or-later"` and no `License ::` classifier (hatchling rejects both together under PEP 639); both `package.json` files `license == "AGPL-3.0-or-later"`.
  - `test_image_labels` — `backend/Dockerfile` contains `org.opencontainers.image.licenses="AGPL-3.0-or-later"`; `docker-publish.yml` contains `org.opencontainers.image.licenses=AGPL-3.0-or-later` exactly twice and no `licenses=MIT`.
  - `test_readme_states_licence_history` — README contains `AGPL-3.0-or-later`, `Releases up to and including 1.0.2 are MIT`, `HUB_REPO_URL`, and not `fair use`.
- [ ] **Step 2: Run** `pytest tests/unit/test_licence_metadata.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement**
  - `LICENSE` = the downloaded text, unchanged. README: badge `License: AGPL v3` → `https://www.gnu.org/licenses/agpl-3.0`; "License" section: AGPL-3.0-or-later; "Releases up to and including 1.0.2 are MIT; from 1.1.0 on AGPL-3.0-or-later."; why (brother_ql GPL-3.0-or-later, network service, §13); "If you run a modified version for others, set `HUB_REPO_URL` to where its source is published — the About page links there." Delete the Brother-PDF "fair use" paragraph. Before committing, confirm 1.0.2 is still the last release (`gh release list --limit 1`); if not, use that version and tell the coordinator.
  - `CLA.md` §5: "(e.g., the GNU Affero General Public License v3.0 or later under which the Project is distributed)".
  - pyproject: `license = "AGPL-3.0-or-later"`, remove the MIT classifier. Both `package.json`, `backend/README.md`, Dockerfile label, workflow labels/annotations, notices line 3 ("Label Printer Hub is licensed AGPL-3.0-or-later"), the three spec lines ("AGPL-3.0-or-later project").
- [ ] **Step 4: Run** the full backend suite and `pip install ./backend` in a scratch venv (hatchling accepts the metadata). PASS. Gegenversuch: restore the MIT classifier → `test_package_metadata` fails.
- [ ] **Step 5: Commit** — exactly this message, no `!`, no footer other than refs: `git add <files above> && git commit -m "chore(license): relicense to AGPL-3.0-or-later" -m "Releases up to and including 1.0.2 stay MIT." -m "Refs #154"`

### Task A6: Merge, release 1.1.0, verify

- [ ] **Step 1: History check before merging** — on the PR branch with A3–A5: `git log origin/main..HEAD --format='%s%n%b' | grep -nE '^[a-z]+(\([^)]*\))?!:|BREAKING[ -]CHANGE'` → no output. `gh pr checks` all green (Dependency review, Licences — backend runtime, CI, CodeQL); AI reviewers answered (CONTRIBUTING).
- [ ] **Step 2: Merge with "Rebase and merge"** (`gh pr merge --rebase`). Then `gh workflow run release.yml -f dry_run=true` → log says `The next release version is 1.1.0`. If it says 2.0.0 or nothing: stop, report.
- [ ] **Step 3: Release** — wait for the 04:00 UTC run or `gh workflow run release.yml`. Expected: tag `v1.1.0`, and the `images` job green.
- [ ] **Step 4: Verify the image** — `docker buildx imagetools inspect ghcr.io/strausmann/label-printer-hub-backend:1.1.0 --format '{{json .Image}}'`: label `licenses` = `AGPL-3.0-or-later`, `revision` = `git rev-list -n1 v1.1.0`, both platforms present. `docker run --rm -e PRINTER_HUB_SECRET_KEY=<fake 32-byte key> -p 8000:8000 …:1.1.0` → `curl -s localhost:8000/api/info | jq -r .license,.source_url` → `AGPL-3.0-or-later`, `https://github.com/strausmann/label-printer-hub/tree/v1.1.0`, and that URL answers 200.
- [ ] **Step 5: Licence note** — insert under the `1.1.0` heading of `CHANGELOG.md`: "**Licence:** Releases up to and including 1.0.2 are MIT; from 1.1.0 on AGPL-3.0-or-later." Commit `docs(release): note the licence change in the 1.1.0 changelog` (`Refs #154`), push to `main`. Prepend the same line to the release: `gh release edit v1.1.0 --notes-file <file with the line + the current notes>`.
- [ ] **Step 6:** Close #183 with a comment naming the run; tick the Part A boxes in #154.

### Task A7: Make the gate required (repository setting, run by the orchestrator)

- [ ] **Step 1: Confirm the check names** — `gh api repos/strausmann/Label-Printer-Hub/commits/$(git rev-parse origin/main)/check-runs --jq '.check_runs[].name'` lists `Licences — backend runtime`; the A2 PR's runs list `Dependency review`. Use the names exactly as printed.
- [ ] **Step 2: Create the ruleset**

```bash
gh api -X POST repos/strausmann/Label-Printer-Hub/rulesets --input - <<'JSON'
{"name": "main: licence gate", "target": "branch", "enforcement": "active",
 "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
 "bypass_actors": [
   {"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"},
   {"actor_id": 15368, "actor_type": "Integration", "bypass_mode": "always"}],
 "rules": [{"type": "required_status_checks", "parameters": {
   "strict_required_status_checks_policy": false, "do_not_enforce_on_create": false,
   "required_status_checks": [
     {"context": "Dependency review", "integration_id": 15368},
     {"context": "Licences — backend runtime", "integration_id": 15368}]}}]}
JSON
```

- [ ] **Step 3: Gegenversuch** — reopen the throwaway "disallowed licence" PR from Task A2 (or recreate it): `gh pr view <n> --json mergeStateStatus` → `BLOCKED`. The Markdown-only PR → `CLEAN` (or `UNSTABLE` only for unrelated optional checks). Close both.
- [ ] **Step 4: Dependabot still merges** — the next Dependabot patch PR auto-merges after its checks (watch one).
- [ ] **Step 5: Bypass proof** — the next real semantic-release run pushes `chore(release)` and the tag without error. If it fails with a rule violation: `gh api -X DELETE repos/strausmann/Label-Printer-Hub/rulesets/<id>`, re-run the release, report.
- [ ] **Step 6:** Tick the section B boxes of #154 (licence gate + required check).

---

## Part B — Release 1.2.0

### Task B1: Backend licence list in the image

**Files:**
- Modify: `backend/scripts/licence_report.py` (output), `backend/tests/unit/scripts/test_licence_report.py`, `backend/Dockerfile`, `docs/decisions/register.md` (row `D21` "Licence lists and SBOMs are generated from what the image ships", 2026-11-05, Accepted, ADR —)

**Interfaces:**
- Produces: `def to_records(entries: Sequence[Mapping[str, str]]) -> list[LicenceRecord]` where `LicenceRecord = TypedDict(name: str, version: str, license: str, licenseText: str | None, repository: str | None)` — **the same field names `rollup-license-plugin` writes** (Task B3 parses both with one function). Sorted by `name.lower()`. `--output <path>` writes `json.dumps(records, ensure_ascii=False, indent=None)`.
- Image path: `/opt/app/web/licenses/backend.json` → served at `/licenses/backend.json` by the existing SPA static route (no backend change). Not served in the API-only (`web-stub`) image; the file is still in the image.

- [ ] **Step 1: Write the failing tests** — `test_to_records_shape` (keys exactly the five above; licence from `classify`), `test_to_records_sorted`, `test_to_records_excludes_own_package`, `test_output_is_valid_json_with_text` (a text containing `<script>` and non-ASCII survives a round trip unchanged).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Spike S3b (15 min)** — in a local `docker build -f backend/Dockerfile --target builder .`: `ls /opt/venv/lib/python3.12/site-packages/brother_ql/*.py /opt/venv/lib/python3.12/site-packages/ptouch*/*.py` (sources present → GPLv3 §6 source is in the image) and whether pip-licenses finds a licence file for both. Record both results in the B4 notices text.
- [ ] **Step 4: Implement** `to_records`/`--output`; Dockerfile `builder` stage after the final `pip install`: `COPY licence-policy.yml backend/scripts/licence_report.py`, a tool venv `/opt/licence-tool` with `pip-licenses==5.5.5 pyyaml`, run the script with `--python /opt/venv/bin/python --output /build/backend-licences.json` (a disallowed licence fails the build); `runtime` stage: `COPY --from=builder --chown=hub:hub /build/backend-licences.json /opt/app/web/licenses/backend.json` after the web copy. The tool venv never reaches `runtime`. `# D21` on the script's `to_records`.
- [ ] **Step 5: Run** unit tests (PASS); `docker build -f backend/Dockerfile -t lph:b1 . && docker run --rm --entrypoint python lph:b1 -c "import json;d=json.load(open('/opt/app/web/licenses/backend.json'));print(len(d), {r['name']:r['license'] for r in d}['brother-ql'])"` → a count > 30 and `GPL-3.0-or-later`; `docker run --rm --entrypoint sh lph:b1 -c 'test ! -e /opt/licence-tool && ! /opt/venv/bin/pip show pip-licenses'` → exit 0.
- [ ] **Step 6: Commit** — `build(docker): ship the backend licence list generated from the runtime venv` (`Refs #154`).

### Task B2: Frontend licence list and CycloneDX of the bundle

**Files:**
- Create: `frontend/src/licences/build.ts`, `frontend/src/licences/build.test.ts`
- Modify: `frontend/package.json` (devDependency `rollup-license-plugin: "3.2.1"`), `frontend/pnpm-lock.yaml`, `frontend/vite.config.ts`, `frontend/src/build.test.ts`, `backend/Dockerfile` (`ARG VERSION` passed into `web-builder` as `HUB_VERSION`)

**Interfaces:**
- Produces (`build.ts`):
  - `export function isUnacceptableLicence(id: string): boolean` — true for `""`, `UNLICENSED`, `UNKNOWN`, values starting `SEE LICENSE IN`, any id containing `BUSL`, `SSPL`, `Elastic`, `Commons-Clause`, `CC-BY-NC`, `Proprietary` (case-insensitive). GPL/AGPL/LGPL are acceptable.
  - `export function toCycloneDx(packages: readonly PluginPackage[], version: string): string` — CycloneDX **1.6** JSON: `bomFormat: "CycloneDX"`, `specVersion: "1.6"`, `version: 1`, `metadata.component = {type: "application", name: "label-printer-hub-web", version}`, `components[] = {type: "library", name, version, purl, licenses}`, purl `pkg:npm/<name with "@" encoded as "%40">@<version>`, `licenses: [{expression: license}]`. No `serialNumber`, no timestamp (reproducible). Components sorted by purl.
  - `PluginPackage` = `{name: string; version: string; license: string; licenseText?: string | null; repository?: string | null}`.
- vite plugin options: `outputFilename: "licenses/frontend.json"`, `additionalFiles: {"frontend.cdx.json": (p) => toCycloneDx(p, process.env.HUB_VERSION ?? "0.0.0-dev")}`, `unacceptableLicenseTest: isUnacceptableLicence`, `excludedPackageTest: (name) => name === "label-printer-hub-web"`. Image paths: `/opt/app/web/licenses/frontend.json`, `/opt/app/web/frontend.cdx.json`.

- [ ] **Step 1: Write the failing tests**
  - `build.test.ts` (licences): `isUnacceptableLicence` true for `"UNLICENSED"`, `"SEE LICENSE IN LICENSE.md"`, `"BUSL-1.1"`, `""`; false for `"MIT"`, `"GPL-3.0-or-later"`, `"AGPL-3.0-only"`, `"(MIT OR Apache-2.0)"`. `toCycloneDx([{name: "@tanstack/react-query", version: "5.105.3", license: "MIT"}, {name: "react", version: "19.3.1", license: "MIT"}], "1.2.0")` parses; `components[0].purl === "pkg:npm/%40tanstack/react-query@5.105.3"`; two calls give identical strings.
  - `src/build.test.ts` (built output): `dist/licenses/frontend.json` lists `react` and `react-dom` with `licenseText` non-empty, lists no `vite`, `vitest`, `typescript`, `eslint` or `@playwright/test`; `dist/frontend.cdx.json` has a component with purl `pkg:npm/react@19.3.1`; `dist/sw.js` contains neither `frontend.json` nor `frontend.cdx.json`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Spike S1 (20 min)** — with the plugin wired, `pnpm build` once offline (`--network none` container or no network) and once online: does the list include the `@react-aria/*`/`@internationalized/*` packages, `zxing-wasm` and both `@fontsource` packages? Is `licenseText` filled from `node_modules`, or does the plugin fetch tarballs (`node-fetch` is a dependency)? Record the answer in the PR. If it fetches: acceptable in CI and Docker (both have network); note it in the README's build section.
- [ ] **Step 4: Implement** `build.ts`, the plugin, the Dockerfile `ARG VERSION` → `ENV HUB_VERSION` in `web-builder`.
- [ ] **Step 5: Run** `pnpm typecheck && pnpm lint && pnpm test:coverage && pnpm build` — PASS. Gegenversuch: return `false` from `isUnacceptableLicence` for `UNLICENSED` → unit test fails; put `json` into `globPatterns` → the `sw.js` assertion fails.
- [ ] **Step 6: Commit** — `build(web): licence list and CycloneDX SBOM of the bundled packages` (`Refs #154`).

### Task B3: Dependency licences on the About page

Design skills as in Task A4, plus `break-ui` for long names and long texts.

**Files:**
- Create: `frontend/src/features/about/licences.ts`, `frontend/src/features/about/licences.test.ts`, `frontend/src/features/about/DependencyLicences.tsx`, `frontend/src/features/about/DependencyLicences.test.tsx`
- Modify: `frontend/src/features/about/AboutPage.tsx`, `frontend/e2e/about.spec.ts`, `frontend/src/i18n/locales/{en,de}/messages.po`

**Interfaces:**
- Consumes: `/licenses/frontend.json`, `/licenses/backend.json` (Tasks B1, B2; same record shape).
- Produces: `export type LicenceEntry = {name: string; version: string; licence: string; text: string | null; part: "web" | "server"}`; `export function parseLicenceList(raw: unknown, part: LicenceEntry["part"]): LicenceEntry[]` (drops records without `name`/`version`, never throws on a non-array → `[]`); `export function useLicenceLists(): {entries: LicenceEntry[]; missing: LicenceEntry["part"][]; isPending: boolean}` (react-query, `staleTime: Infinity`, fetched only when the About page mounts).

**Copy (en → de):** "Third-party software" (`context: "heading"`) → "Software von Dritten"; "{count} packages" → "{count} Pakete" (Lingui plural); "Show licence text" (`context: "action"`) → "Lizenztext anzeigen"; "Hide licence text" → "Lizenztext ausblenden"; "The licence list of the {part} is not included in this build." → "Die Lizenzliste des {part} ist in diesem Build nicht enthalten." with part labels "web app"/"Web-App" and "server"/"Servers".

- [ ] **Step 1: Write the failing tests**
  - `licences.test.ts`: `parseLicenceList({}, "web")` → `[]`; a record without `version` dropped; `licenseText: ""` → `text: null`.
  - `DependencyLicences.test.tsx`: two lists (mock fetch) → a table with columns package, version, licence, part; rows sorted by name; licence text **not** in the DOM until "Show licence text" is pressed; a text `"<script>alert(1)</script>"` appears as literal text and no `script` element is created; `/licenses/backend.json` 404 → the web rows still render plus the "server … not included" message; both 404 → only the two messages, project licence and source link still shown (from Task A4).
  - `e2e/about.spec.ts`: the table lists `react` and `brother-ql`; expanding `brother-ql` shows text containing `GNU GENERAL PUBLIC LICENSE`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement**; fill the `data-section="dependencies"` slot; the e2e backend serves real files (the e2e app builds the web app; add the backend list fixture the same way the e2e setup provides `dist`).
- [ ] **Step 4: Run** the web gates and `pnpm e2e` — PASS. Gegenversuch: render the text with `dangerouslySetInnerHTML` → the `<script>` test fails.
- [ ] **Step 5: Commit** — `feat(ui): list every shipped third-party licence on the about page` (`Refs #154`).

### Task B4: Third-party notices

**Files:**
- Modify: `THIRD_PARTY_NOTICES.md`, `backend/tests/unit/test_licence_metadata.py`

- [ ] **Step 1: Write the failing test** `test_notices_name_copyleft_dependencies` — the file contains `brother_ql`, `GPL-3.0-or-later`, `ptouch`, `LGPL-2.1-or-later`, `/licenses/backend.json`, `/licenses/frontend.json`, `/frontend.cdx.json`, and no longer says the full list "is tracked in #154".
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** — keep every existing table and section as it is (the sheet-archive branches add rows and a "Sheet type data" section there); change the intro to: complete generated lists ship in the image and on the About page (paths above); add a section "Copyleft dependencies": brother_ql (GPL-3.0-or-later, upstream URL, source as `.py` files in the image per Spike S3b), ptouch (LGPL-2.1-or-later, PyPI URL, same), and that the hub's own source of each version is linked from the About page (GPLv3 §6(d), AGPL §13).
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** — `docs(docs): name the copyleft dependencies and the generated licence lists` (`Refs #154`).

### Task B5: Provenance, attestations and an image check in CI

**Files:**
- Modify: `.github/workflows/docker-publish.yml` (`provenance: mode=max`), `.github/workflows/ci.yml` (`docker-build` job)

- [ ] **Step 1: Write the check** in the `docker-build` job: build with `load: true` and `tags: label-printer-hub:ci`; then `anchore/sbom-action/download-syft@v0.24.3` (`syft-version: v1.55.0`) and:
  - `syft label-printer-hub:ci --select-catalogers +sbom-cataloger -o json | jq -e '[.artifacts[].name] | index("react") and index("react-dom")'`
  - `syft label-printer-hub:ci -o json | jq -e '[.artifacts[].name] | index("react") | not'` (documents that the default scan misses the bundle — this is why the embedded file exists)
  - `docker run --rm --entrypoint sh label-printer-hub:ci -c 'test -s /opt/app/web/licenses/backend.json && test -s /opt/app/web/licenses/frontend.json && test -s /opt/app/web/frontend.cdx.json && ls /opt/venv/lib/python3.12/site-packages/brother_ql/__init__.py'`
- [ ] **Step 2: Run on the PR** — green. Gegenversuch: on a scratch commit drop `additionalFiles` from the vite config → the first `jq -e` fails; revert.
- [ ] **Step 3: Implement** `provenance: mode=max` (keep `sbom: true`). Check that no build arg carries a secret (only `VERSION`, `REVISION`, `BUILD_DATE`) — `mode=max` records them.
- [ ] **Step 4: Spike S2 (20 min)** — after the branch image is pushed: `docker buildx imagetools inspect ghcr.io/strausmann/label-printer-hub-backend:<branch-slug> --format '{{json .SBOM}}'` returns an SPDX document for `linux/amd64` and `linux/arm64` (the `imagetools create` merge kept the attestation manifests); `--format '{{json .Provenance}}'` shows `mode=max` content; `jq` whether the SPDX lists `react`. Record the three answers in the README text of Task B7. If the SBOM is missing after the merge: report (do not switch on `BUILDKIT_SBOM_SCAN_STAGE`, call 15).
- [ ] **Step 5: Commit** — `ci(docker): max provenance and an image check for the embedded SBOM and licence lists` (`Refs #154`).

### Task B6: CycloneDX SBOM as release asset

**Files:**
- Modify: `.github/workflows/docker-publish.yml` (new job `release-sbom`)

**Interfaces:**
- Consumes: `inputs.tag` (Task A1), the merged multi-arch tag from the `merge` job.

- [ ] **Step 1: Implement** job `release-sbom`: `needs: merge`, runs only for `release` flavor (non-empty `inputs.tag`), `permissions: {contents: write, packages: read}`; download Syft as in B5; `syft ghcr.io/strausmann/label-printer-hub-backend:<tag> --platform linux/amd64 --select-catalogers +sbom-cataloger -o cyclonedx-json=label-printer-hub-<tag>.cdx.json`; `jq -e '.components | map(.name) | index("react") and index("brother-ql")'` on the file; `gh release upload v<tag> label-printer-hub-<tag>.cdx.json --clobber` with `GH_TOKEN: ${{ github.token }}`.
- [ ] **Step 2: actionlint** — no findings.
- [ ] **Step 3: Verify** — on the branch, `gh workflow run docker-publish.yml --ref <branch> -f tag=1.1.0` (republishes 1.1.0 from its tag, Task A1 logic) → `gh release view v1.1.0 --json assets --jq '.assets[].name'` lists `label-printer-hub-1.1.0.cdx.json`. This gives 1.1.0 its SBOM too.
- [ ] **Step 4: Commit** — `ci(release): attach a CycloneDX SBOM of the image to each release` (`Refs #154`).

### Task B7: Documentation and closing

**Files:**
- Modify: `README.md` (section "Supply chain: SBOM and provenance"), `backend/tests/unit/test_licence_metadata.py`

- [ ] **Step 1: Write the failing test** `test_readme_supply_chain` — README contains `imagetools inspect`, `{{ json .SBOM.SPDX }}`, `--select-catalogers +sbom-cataloger`, `frontend.cdx.json` and `.cdx.json` release asset wording.
- [ ] **Step 2: Implement** the README section: get the SBOM without pulling (`docker buildx imagetools inspect ghcr.io/strausmann/label-printer-hub-backend:<tag> --format "{{ json .SBOM.SPDX }}"`), provenance (`--format "{{ json .Provenance }}"`), the release asset, the embedded `frontend.cdx.json` and why scanners need `+sbom-cataloger` (Spike S2 result stated as measured); licence lists at `/about`; VEX is not provided (optional later, issue's last box stays open as a follow-up).
- [ ] **Step 3: Run** — PASS.
- [ ] **Step 4: Commit** — `docs(docs): how to get the SBOM, provenance and licence lists of an image` (`Refs #154`).
- [ ] **Step 5: Close-out** — after the 1.2.0 release: acceptance criteria of #154 checked one by one (`imagetools inspect` SBOM + provenance for 1.2.0; `syft ghcr.io/…:1.2.0 --select-catalogers +sbom-cataloger` lists `react`, `react-dom`; release 1.2.0 has the `.cdx.json` asset; About page of 1.2.0 shows both lists). Tick the boxes; open a follow-up issue for VEX; close #154 with a summary comment.

---

## Files shared with the sheet-archive work and merge order

| File | This plan | Sheet archive | Rule |
|---|---|---|---|
| `THIRD_PARTY_NOTICES.md` | A5 line 3; B4 intro + new section | plan 1 "Sheet type data" section; plan 2 reportlab rows | never reorder or rewrite existing tables; on conflict keep both |
| `docs/decisions/register.md` | A3 `D20`, B1 `D21` (append) | `D13`–`D19`, `V1`–`V4` | append-only; sheet archive's next label is `D22` |
| `backend/app/api/routes/info.py`, `backend/tests/integration/api/test_info.py` | A3 fields | plan 4 flips `sheets`/`calibration` flags | different lines; `test_info_shape` key set takes both |
| `backend/app/schemas/info.py`, `frontend/src/api/schema.gen.ts` | A3 | every API task | resolve `schema.gen.ts` by re-running `pnpm gen:api`, never by hand |
| `frontend/src/app/router.tsx` | A4 `/about` | plan 4 sheet routes | both lines kept |
| `backend/pyproject.toml` | A5 licence lines | plan 2 `reportlab` | different hunks |
| `backend/Dockerfile` | A5 label, B1 builder step, B2 `ARG` | plan 4 test reads it | — |
| `docs/superpowers/specs/2026-11-05-sheet-archive-design.md` | A5 line 67 | not changed on `feat/sheet-archive-1` | — |

**Order:** A1 and A2 any time (no release). The A3–A5 PR lands before any sheet-archive `feat` merge (open question 2), then A6, A7. Part B after 1.1.0, independent of the sheet archive; B3 is the `feat` that makes 1.2.0.
