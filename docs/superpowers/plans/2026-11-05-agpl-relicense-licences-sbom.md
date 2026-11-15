<!--
SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# AGPL Relicensing, Licence Gate, Licence List and SBOM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From release 1.1.0 on the hub is licensed AGPL-3.0-or-later, links every user to the source of the running build and blocks new dependencies with incompatible licences. From 1.2.0 on it shows every shipped third-party licence in the product and publishes a complete SBOM with every image.

**Architecture:** Two parts, two releases. **Part A** (release 1.1.0) fixes the release image build (#183) and moves semantic-release to a deploy key. It adds the licence policy and its gates, extends `GET /api/info` with licence and source URL, and adds an About page with source links. The licence itself is swapped in one `chore(license)` commit. **Part B** (release 1.2.0) generates the backend and frontend licence lists from what the image ships and shows them on the About page. It also embeds a CycloneDX SBOM of the web bundle, turns provenance to `mode=max`, checks the image in CI and attaches a CycloneDX SBOM to each GitHub release.

**Tech Stack:** FastAPI/Pydantic, React 19 + TanStack Router/Query + Lingui, Vite 8 + `rollup-license-plugin` 3.2.1, `pip-licenses` 5.5.5 (build-time tool venv only), Docker Buildx/BuildKit attestations, Syft v1.55.0 via `anchore/sbom-action/download-syft@v0.24.3`, `actions/dependency-review-action@v5`, semantic-release with an SSH deploy key.

**Spec:** https://github.com/strausmann/Label-Printer-Hub/issues/154 (plus #183 for the release image build). The plan departs from #154 in three places: no major version, the release SBOM is produced by the image workflow, and the backend list is generated in the builder stage from the venv the runtime stage receives. Each departure is decided below and posted on #154 in Task A1 Step 0. Not legal advice.

**Revision 2 (2026-11-05):** All findings of the external review (B1–B2, M1–M13, Minor 1–13) and the orchestrator's rulings 1–8 are worked in. Each one is traced in the last section.

## Findings that shaped the plan (checked 2026-11-05)

- **CLA — no blocker.**
  - `CLA.md` §1 grants the Maintainer a perpetual, irrevocable licence to "sublicense, and distribute Your Contributions". §5 says the Maintainer "may license the Contribution under any license … at the Maintainer's discretion".
  - Commit authors: the Maintainer (209), `semantic-release-bot` (21 release commits) and `dependabot[bot]` (16).
  - `Co-authored-by` trailers, GitHub's contributor list and all 84 merged PRs show no other human.
  - Nothing needs consent. Task A5 updates §5's example sentence ("the MIT License under which the Project is currently distributed").
- **`fix(queue)` (#187) is on `main` since v1.0.2.** The nightly release will most likely publish **1.0.3 under MIT** before this plan lands. The plan never assumes `latest` = 1.0.2.
  - The last MIT release is read at execution time as `LAST_MIT=$(gh release list --limit 1 --json tagName -q '.[0].tagName' | sed 's/^v//')`.
  - Wherever this plan writes `<LAST_MIT>`, that value is meant.
  - With a `feat` on top of 1.0.2 or 1.0.3, the next version is **1.1.0** in both cases. The review confirmed this against `.releaserc.json`.
- **No branch protection, no rulesets** on `main` today. A required check needs a new ruleset (Task A7).
- **semantic-release pushes with `GITHUB_TOKEN`** (`release.yml`: `persist-credentials: false`, no `repositoryUrl`). On a user-owned repo a ruleset accepts only repository roles and deploy keys as bypass actors, not the GitHub Actions app. So the push moves to a deploy key (Task A1).
- **`docker-publish.yml`:**
  - It already has `sbom: true` and `provenance: true`.
  - Release flavor sets `{{major}}.{{minor}}`, `{{major}}` and `latest` only when the tag has no `-`. But it publishes **any** release-flavor tag to Docker Hub, pre-releases included.
  - The `merge` job sets the index annotation `revision` from `github.sha` and checks nothing out.
  - The concurrency group is `docker-publish-${{ github.ref }}`. Under `workflow_call` that is `refs/heads/main`, shared with dev pushes that cancel in progress.
- **`cycjimmy/semantic-release-action`** sets `new_release_published=true` whenever `nextRelease.version` exists, **also in a dry run** (`src/windUpJob.task.js`).
- **Measured runtime licences (review clone):**
  - Backend: `cffi` declares `MIT-0`.
  - Wrong or ambiguous Python metadata: `pysnmp` (`UNKNOWN` in all three fields), `qrcode` (`BSD License; Other/Proprietary License`), `Jinja2` and `pyusb` (bare `BSD License`), `ptouch` (classifier `LGPLv2+`, text LGPL 2.1).
  - Some packages carry joined classifiers, e.g. `uvloop`: `Apache Software License; MIT License`.
  - Frontend `pnpm licenses list --prod`: 378 packages, all within the list.
  - GitHub's dependency graph reports `json-schema@0.4.0` as `AFL-2.1 AND AFL-3.0 AND BSD-3-Clause` (package.json: `(AFL-2.1 OR BSD-3-Clause)`).
- **Licence texts:** `brother_ql-0.9.4.dist-info` has no licence file (checked in the wheel), and neither has `packbits`. The image does not contain the project's own `LICENSE` either.
- **Not in the Rollup module graph:**
  - Scalar (`@scalar/api-reference/dist/browser/standalone.js`, copied as an asset).
  - The scan worker's `zxing-wasm` (separate worker build).
  - The Workbox runtime inside `sw.js`.
- **SPA catch-all:** a missing file outside `assets/` is answered with `index.html` and **200** (`backend/app/web/spa.py:114-131`).
- **Brother PDFs:** never committed (`git log --all -- '*.pdf'` is empty), not in the image. The README "fair use" paragraph and the same sentence in `docs/policies/trademarks.md` are removed. The links to Brother's download pages stay.
- **`.dockerignore` excludes `.github/`.** The policy lives at the repo root and is copied into both build stages.
- **Squash merge is the default.** Rebase merge is enabled (`allow_rebase_merge: true`).

## Orchestrator's calls

1. **No major release (coordinator ruling).** The licence change is not a breaking change for operators: no API, configuration or data change.
   - `chore(license): relicense to AGPL-3.0-or-later` carries no `!` and no `BREAKING CHANGE` footer.
   - It ships with the `feat(api)`/`feat(ui)` commits of A3/A4 as **1.1.0**.
   - README and CHANGELOG say: "Releases up to and including `<LAST_MIT>` are MIT; from 1.1.0 on AGPL-3.0-or-later."
2. **#183 is fixed here (Task A1).** `release.yml` calls `docker-publish.yml` via `workflow_call`, never in a dry run. The build checks out the tag and takes `REVISION` and the index annotation from it. Release builds get their own concurrency group that is never cancelled.
3. **Never rebuild or push a version that is already published (ruling 1).** Every live test of the image workflow uses a throwaway pre-release tag `v0.0.0-ci.<n>`. Such tags:
   - create no `latest`, major or minor tag;
   - go to GHCR only, never Docker Hub;
   - are deleted after the test (git tag, release, GHCR version).
4. **semantic-release pushes through an SSH deploy key (ruling 4).**
   - The ruleset bypass is limited to the admin role and deploy keys. The GitHub Actions app gets no bypass.
   - Mechanics (deploy key, `ssh-key` checkout, SSH `repositoryUrl`) follow the proven pattern of the project's other repos.
5. **The Part A release PR (A3–A5) is merged with "Rebase and merge"**, after review fix-ups are folded in with `git rebase -i --autosquash`. `chore(license)` stays its own commit; all other PRs keep squash merge.
6. **One policy file, `licence-policy.yml`, for every gate (ruling 2).** It is written as JSON, which is valid YAML: dependency-review reads it as YAML, the backend script and the Vite plugin read it with `json`/`JSON.parse`. It holds:
   - `allow-licenses`;
   - dependency-review's `allow-dependencies-licenses` (npm purls);
   - the project's `x-licence-exceptions` (one entry per package, each with the licence it really carries and a reason).

   A test asserts that every purl in `allow-dependencies-licenses` has an exception entry with a reason.
7. **Allowed licences (SPDX, measured against the shipped packages):** `0BSD`, `AFL-2.1`, `AGPL-3.0-only`, `AGPL-3.0-or-later`, `Apache-2.0`, `BlueOak-1.0.0`, `BSD-2-Clause`, `BSD-3-Clause`, `BSL-1.0`, `CC-BY-4.0`, `CC0-1.0`, `GPL-2.0-or-later`, `GPL-3.0-only`, `GPL-3.0-or-later`, `HPND`, `ISC`, `LGPL-2.0-or-later`, `LGPL-2.1-only`, `LGPL-2.1-or-later`, `LGPL-3.0-only`, `LGPL-3.0-or-later`, `MIT`, `MIT-0`, `MIT-CMU`, `MPL-2.0`, `OFL-1.1`, `PSF-2.0`, `Python-2.0`, `Unlicense`, `Zlib`.
   - Deliberately absent: `GPL-2.0-only` and `LGPL-2.0-only` (incompatible with AGPL-3.0), and anything non-free (`BUSL-1.1`, `SSPL-1.0`, `Elastic-2.0`, `CC-BY-NC-*`, `LicenseRef-*`, Commons Clause).
   - `AFL-2.1` is on the list because `json-schema` is offered under `AFL-2.1 OR BSD-3-Clause`. An `OR` expression passes if one branch passes.
8. **The only required check is `Dependency review` (ruling 3).** It is diff-based: only dependencies changed by the PR are judged.
   - The backend licence check runs where the result is deterministic: in the Docker `builder` stage, against the packages installed into the image. A violation fails the image build.
   - On PRs it runs only when `backend/pyproject.toml`, `licence-policy.yml` or the script change (workflow `paths:`), never as a required check.
   - Python has no lockfile, so a PR-level check would judge whatever PyPI serves that day.
9. **Dependency review:** `fail-on-scopes: [runtime, unknown]` (pnpm packages may arrive with scope `unknown`, Minor 10), `vulnerability-check: false` (the gate is about licences; Dependabot and CodeQL cover vulnerabilities).
10. **The ruleset is created last (Task A7).** The 1.1.0 release proves the deploy-key push first.
11. **No SPDX headers in source files now.** The issue marks them optional, and they would touch 300+ files that collide with the running sheet-archive branches.
12. **The §13 source link points at the exact build.**
    - A semver release links `<repo>/tree/v<version>`. Otherwise a commit SHA links `<repo>/tree/<sha>`. Otherwise the repo root.
    - `HUB_REPO_URL` stays overridable for modified forks.
    - Only `http`/`https` without user info is accepted; anything else falls back to the canonical repo. The same sanitising applies to `/healthz`'s `repository` field.
    - OpenAPI `info.license` also names the licence, so `/docs` shows it in the API-only image.
13. **`/about` is a top-level route for every signed-in user**, because settings are admin-only and §13 covers every user. It is linked from:
    - the sidebar footer;
    - a top-bar icon on all widths;
    - the System settings page;
    - the sign-in screen and the bootstrap-key screen ("Source code").
14. **The release SBOM asset is produced by the image workflow**, because semantic-release publishes the release before the image exists. Syft runs with `+sbom-cataloger` on the pushed tag.
15. **Frontend list and CycloneDX come from the licence plugin** (`outputFilename: false`, both files written through `additionalFiles`).
    - Packages outside the Rollup graph are added with `includePackages`: Scalar's production subtree, `zxing-wasm`, and the Workbox runtime packages inlined into `sw.js`.
    - One fixed extra record covers zxing-cpp (Apache-2.0) inside the WebAssembly.
    - Scalar's subtree is an over-approximation (the standalone bundle may not use every dependency it declares). Listing too much is the safe side; the README says so.
16. **`BUILDKIT_SBOM_SCAN_STAGE` is not enabled.** It would add dev tooling and build tools the image does not ship. Spike S2 records what the BuildKit attestation contains.
17. **Missing licence texts are filled from checked-in canonical texts** (`backend/licences/<SPDX>.txt`, at least `GPL-3.0-or-later`; more if S3 finds other gaps). Every shipped record has a text. The project's own `LICENSE` goes into the image (`/opt/app/LICENSE` and `/opt/app/web/licenses/agpl-3.0.txt`).
18. **`/licenses/*` misses are 404, not the app shell.** `spa.py` treats `licenses/` like `assets/`, and the About page treats any non-JSON answer as "missing".
19. **Decision labels:** `D20` (AGPL-3.0-or-later, source link of the running build) in A3, `D21` (licence lists and SBOM come from the shipped artefacts) in B1. The sheet archive uses D13–D19; its next free label is D22.
20. **"MIT project" in specs and policies is corrected in the relicensing commit:**
    - `docs/superpowers/specs/2026-11-05-sheet-archive-design.md:67`;
    - `docs/superpowers/specs/2026-11-03-web-ui-redesign-design.md:34,235`;
    - `docs/policies/trademarks.md:25`.

    `feat/sheet-archive-1` touches none of them. The sheet-archive **plans** only name the MIT/BSD licences of dependencies, which stays correct and is left alone. Their new dependencies (reportlab BSD-3-Clause, charset-normalizer MIT) are on the list.
21. **CHANGELOG note after the release** (A6): semantic-release owns `CHANGELOG.md` and hides `chore` commits. The sentence is added by a `docs(release)` commit and prepended to the GitHub release notes.

## Open questions to the operator (each has a default)

1. **Should the licence gate block you as well?** Default: no, admin bypass. Otherwise direct pushes to `main` stop working.
2. **Release order.**
   - 1.0.3 (MIT, contains `fix(queue)`) will likely go out tonight; that is fine and expected.
   - If a sheet-archive `feat` lands before the Part A release PR, that `feat` becomes 1.1.0 under MIT and AGPL becomes 1.2.0.
   - Default: hold sheet-archive merges until the AGPL release is published.

## Global Constraints

- Prose in code, docs, commits and PRs is **English**. UI copy is **en and de**, in British English ("Licence" as the noun); the SPDX id stays `AGPL-3.0-or-later`.
- Conventional Commits. Task A1 adds `license` to `scope-enum`. **No commit of this series contains `!:` or a `BREAKING CHANGE`/`BREAKING-CHANGE` footer.**
- No AI attribution and no internal infrastructure names (public repo).
- TDD: test first, red, implement, green, commit. Every new test is run once against the unfixed code (Gegenversuch) as named in its task.
- **Never rebuild or push an already published version.** Live workflow tests use `v0.0.0-ci.<n>` only and clean up after themselves (call 3).
- No new **runtime** dependency. Build-time only, both named with licence in the PR:
  - `rollup-license-plugin@3.2.1` (MIT, exact pin, `frontend` devDependencies);
  - `pip-licenses==5.5.5` (MIT, in throwaway tool venvs in the `builder` stage and in CI, never in `/opt/venv`).
- Image stays non-root UID 1000. No CDN. The CSP in `backend/app/web/spa.py` stays unchanged. The service worker does **not** precache licence JSON (`pwa.config.ts` `globPatterns` has no `json` — keep it).
- `GET /api/info` stays public and secret-free: constants, sanitised build info, booleans.
- Workflow inputs reach `run:` steps only through `env:`, never as inline `${{ inputs.* }}`.
- Actions keep the repo's major-tag convention. `download-syft` is pinned to `v0.24.3`, Syft to `v1.55.0`.
- Coverage gates stay: backend `--cov-fail-under=80`, web 70 %.

## Review Focus

1. **Release image built from the wrong commit.** Under `workflow_call`, `github.sha` is the pre-release commit. For `v1.1.0` both the per-platform label **and** the index annotation `org.opencontainers.image.revision` must equal `git rev-list -n1 v1.1.0`. → A1 Step 5, A6 Step 5.
2. **Source link that leads nowhere or leaks.** These inputs must all give a working, credential-free `http(s)` link:
   - dev/branch images, `0.0.0-dev`, `revision=unknown`;
   - a fork's `HUB_REPO_URL` with `.git`/`/`;
   - `javascript:` or `https://token@host/…`.

   → A3 `test_source_url` table.
3. **Licence data missing or hostile.** The cases: an API-only image, the Vite dev server, a 404, a 200 `text/html` app shell, a 2 MB list, texts containing `<script>`. The About page still shows the project licence and the source link, shows a message for the missing list, renders texts as text, and mounts a text only when expanded. → A4, B1 (`spa.py`), B3.
4. **Accidental version jump.** A stray `!`, a footer, a squash merge or an unfolded review commit could change the version. The computed version is proven **before** the merge on the simulated merge result. → A6 Steps 1–3.
5. **Gate red for a non-defect, or green for a real one.** The cases:
   - a docs-only PR, a Dependabot bump of an allowed package, a known vulnerability, and `json-schema`'s mis-reported graph licence must stay green;
   - a direct **and** a transitive runtime dependency outside the list must turn red.

   → A2 Steps 6–7, A7 Step 3.

---

## Part A — Release 1.1.0

### Task A1: Release images from the release workflow (#183), deploy-key push, `license` scope

Read the project skill `semantic-release` ("Protected `main` + semantic-release: SSH deploy-key bypass") before starting.

**Files:**
- Modify: `.github/workflows/docker-publish.yml`, `.github/workflows/release.yml`, `.releaserc.json`, `commitlint.config.cjs`
- Create: `backend/tests/unit/test_release_workflows.py`

**Interfaces:**
- Produces:
  - `docker-publish.yml` gains `workflow_call: inputs: tag: {type: string, required: true}`. B6 adds a job that reads the same input.
  - Flavor rule: a non-empty `INPUT_TAG` (dispatch or call) means `release`.
  - The input is validated against `^v?[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$`, a leading `v` is stripped, and anything else fails the step.

- [ ] **Step 0: Orchestrator prerequisites** (run before this PR merges, because the nightly release must keep working):
  - Generate the key: `ssh-keygen -t ed25519 -N "" -C semantic-release -f <scratch>/sr_key`.
  - Register it: `gh repo deploy-key add <scratch>/sr_key.pub --repo strausmann/Label-Printer-Hub --allow-write --title "semantic-release"`.
  - Store it: `gh secret set SEMANTIC_RELEASE_SSH_KEY --repo strausmann/Label-Printer-Hub < <scratch>/sr_key`.
  - Delete both local files.
  - Post a comment on #154 that lists calls 1, 8 and 14 as deliberate departures from the issue's checkboxes.
- [ ] **Step 1: Write the failing guard test** `test_release_workflows.py`. It parses the workflow YAML with `yaml.safe_load`. Its docstring states the limit: it checks the text of the workflows, not their run; the run is Step 5. Tests:
  - `test_release_builds_from_tag` — in `docker-publish.yml`, the `build` and `merge` jobs both have an `actions/checkout` step whose `ref` uses the tag input, and neither job references `github.sha` in `REVISION` or in `org.opencontainers.image.revision`.
  - `test_release_concurrency_is_separate` — the workflow `concurrency.group` contains `inputs.tag`.
  - `test_prerelease_never_floats_or_reaches_docker_hub` — the Docker Hub image line and the `{{major}}`, `{{major}}.{{minor}}` and `latest` tag lines all require `!contains(steps.tag.outputs.tag, '-')`.
  - `test_images_job_skips_dry_run` — the `release.yml` job `images` has an `if` that contains `new-release-published == 'true'` and `!inputs.dry_run`.
  - `test_semantic_release_pushes_over_ssh` — `.releaserc.json` `repositoryUrl` is `git@github.com:strausmann/Label-Printer-Hub.git`, and the `release.yml` checkout uses `ssh-key: ${{ secrets.SEMANTIC_RELEASE_SSH_KEY }}` with `persist-credentials: true`.
- [ ] **Step 2: Run** `cd backend && pytest tests/unit/test_release_workflows.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement**
  - `docker-publish.yml`:
    - Add `workflow_call` and remove the `release: published` trigger.
    - Concurrency: `group: docker-publish-${{ inputs.tag && format('release-{0}', inputs.tag) || github.ref }}` and `cancel-in-progress: ${{ github.event_name == 'push' && !inputs.tag }}`.
    - In both jobs, for release flavor, check out `ref: v<tag>` and set `REVISION=$(git rev-parse HEAD)` as a step output. Use it for build-arg, label and index annotation.
    - The Docker Hub image line and the floating tags require no `-` in the tag.
    - Keep the comment "release builds are never cancelled" true.
  - `release.yml`:
    - Checkout `with: {fetch-depth: 0, ssh-key: ${{ secrets.SEMANTIC_RELEASE_SSH_KEY }}, persist-credentials: true}`.
    - New job `images`:

      ```yaml
      needs: release
      if: needs.release.outputs.new-release-published == 'true' && !inputs.dry_run
      uses: ./.github/workflows/docker-publish.yml
      with:
        tag: ${{ needs.release.outputs.new-release-version }}
      secrets: inherit
      permissions: {contents: write, packages: write, id-token: write}
      ```

      `contents: write` is needed by B6.
  - `.releaserc.json`: `"repositoryUrl": "git@github.com:strausmann/Label-Printer-Hub.git"`. `@semantic-release/github` keeps `GITHUB_TOKEN`.
  - `commitlint.config.cjs`: add `'license'` to `scope-enum`.
- [ ] **Step 4: Run** the guard test (PASS) and `docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:1.7.7 -color` (no findings).
- [ ] **Step 5: Live Gegenversuch with a throwaway pre-release (never a published version).**
  - Tag the branch head and push: `git tag v0.0.0-ci.1 && git push origin v0.0.0-ci.1`.
  - Run `gh workflow run docker-publish.yml --ref ci/release-images -f tag=0.0.0-ci.1` and wait until it is green.
  - Then, with `T=ghcr.io/strausmann/label-printer-hub-backend:0.0.0-ci.1` and `SHA=$(git rev-list -n1 v0.0.0-ci.1)`:
    - `docker buildx imagetools inspect $T --format '{{json .Image}}' | jq -r '.["linux/amd64"].config.Labels["org.opencontainers.image.revision"]'` equals `$SHA`.
    - `docker buildx imagetools inspect $T --raw | jq -r '.annotations["org.opencontainers.image.revision"]'` equals `$SHA`.
    - The run log's `tags` list contains only `…:0.0.0-ci.1` (no `latest`, no `0`, no `0.0`, no `docker.io/…`).
    - `docker buildx imagetools inspect ghcr.io/strausmann/label-printer-hub-backend:latest --format '{{json .Image}}' | jq -r '.["linux/amd64"].config.Labels["org.opencontainers.image.version"]'` still shows the last real release.
  - Clean up:
    - Delete the remote tag: `git push origin :refs/tags/v0.0.0-ci.1`.
    - Delete the local tag: `git tag -d v0.0.0-ci.1`.
    - Find the GHCR version id: `gh api /user/packages/container/label-printer-hub-backend/versions --jq '.[] | select(.metadata.container.tags | index("0.0.0-ci.1")) | .id'`.
    - Delete it: `gh api -X DELETE /user/packages/container/label-printer-hub-backend/versions/<id>`.
- [ ] **Step 6: Commit** `git add .github/workflows/docker-publish.yml .github/workflows/release.yml .releaserc.json commitlint.config.cjs backend/tests/unit/test_release_workflows.py && git commit -m "ci(release): build release images from the release workflow and push releases over a deploy key" -m "Refs #183" -m "Refs #154"`. Open the PR and squash merge. The next nightly release (1.0.3 or later) is the first live proof of the SSH push and of `images`. Watch it; if it fails, revert this commit and report.

### Task A2: Licence policy and its gates

**Files:**
- Create:
  - `licence-policy.yml`
  - `.github/workflows/licence-gate.yml`
  - `.github/workflows/licence-backend.yml`
  - `backend/scripts/licence_report.py`
  - `backend/tests/unit/scripts/__init__.py`
  - `backend/tests/unit/scripts/test_licence_report.py`
  - `backend/tests/unit/test_licence_policy.py`
  - `docs/licence-test-vectors.json` (shared with B2)
- Modify: `backend/Dockerfile` (builder check), `CONTRIBUTING.md` (section "Dependencies and licences")

**Interfaces:**
- `licence-policy.yml` (JSON) has these keys:
  - `allow-licenses` (call 7)
  - `allow-dependencies-licenses: ["pkg:npm/json-schema@0.4.0"]`
  - `fail-on-scopes: ["runtime", "unknown"]`
  - `license-check: true`
  - `vulnerability-check: false`
  - `x-licence-exceptions: [{"purl": str, "licence": SPDX, "reason": str}]`

  `x-licence-exceptions` starts with these entries:

  | Package | Licence | Reason |
  |---|---|---|
  | `pkg:npm/json-schema@0.4.0` | `AFL-2.1 OR BSD-3-Clause` | the dependency graph mis-reports the package.json expression |
  | `pkg:pypi/pysnmp` | `BSD-2-Clause` | metadata `UNKNOWN`; the licence file is BSD-2-Clause |
  | `pkg:pypi/qrcode` | per S3a | classifier lists `Other/Proprietary License` next to BSD; the licence file decides |
  | `pkg:pypi/jinja2` | `BSD-3-Clause` | bare `BSD License` classifier |
  | `pkg:pypi/pyusb` | `BSD-3-Clause` | same |
  | `pkg:pypi/ptouch` | `LGPL-2.1-or-later` | classifier `LGPLv2+`; the shipped text is LGPL 2.1 |

  Plus whatever else S3a finds. PyPI purls carry no version because there is no lockfile; npm purls carry the exact version.
- `docs/licence-test-vectors.json` holds `[{"expression": str, "allowed": bool}]` and is evaluated against the real policy by both the Python and the TypeScript evaluator (B2):
  - `"MIT"` → true; `"MIT-0"` → true; `"(MIT OR CC0-1.0)"` → true
  - `"Apache-2.0 OR BSD-3-Clause"` → true; `"GPL-2.0-only OR Proprietary"` → false
  - `"MIT AND PSF-2.0"` → true; `"MIT AND SSPL-1.0"` → false
  - `"GPL-2.0-only"` → false; `"Apache-2.0 WITH LLVM-exception"` → true
  - `"LicenseRef-scancode-unicode AND MIT"` → false; `""` → false; `"UNKNOWN"` → false
- Produces in `backend/scripts/licence_report.py`, reused by B1:
  - `def load_policy(path: Path) -> Policy`, where `Policy = (allowed: frozenset[str], exceptions: dict[str, Exception])`, keyed by normalised purl.
  - `def expression_allowed(expr: str, allowed: frozenset[str]) -> bool` — tokens `AND`/`OR`/`WITH`/parentheses; `OR` means any branch, `AND` means all; `X WITH Y` is judged by `X`; an empty string or an unparseable expression gives false.
  - `def classify(entry: Mapping[str, str], policy: Policy) -> tuple[str, bool]` — takes one pip-licenses `--from=all` record (fields `Name`, `Version`, `License-Expression`, `License-Metadata`, `License-Classifier`, `LicenseText`). The rules are applied in this order:
    1. An exception for `pkg:pypi/<normalised name>` wins.
    2. Otherwise a valid SPDX `License-Expression` is used.
    3. Otherwise the classifiers, split on `"; "`, are mapped one by one through `CLASSIFIER_TO_SPDX` and joined with ` OR `. `Other/Proprietary License` maps to `Proprietary`. A bare `BSD License` is **not** mapped; it yields `UNKNOWN` and needs an exception.
    4. Otherwise `METADATA_TO_SPDX`.
    5. Otherwise `UNKNOWN`.

    `allowed` is `expression_allowed(...)`.
  - `def check(entries, policy) -> list[str]` — the sorted list of `name (licence)` for every disallowed record.
  - CLI: `python -m scripts.licence_report --python <interpreter> --policy <file> [--output <json>]`. It runs `sys.executable -m piplicenses --python <interpreter> --from=all --with-system --format=json --with-license-file --no-license-path`, excludes `label-printer-hub-backend`, and exits 1 after printing the `check` output.

- [ ] **Step 1: Write the failing tests**
  - `test_licence_policy.py`:
    - `test_policy_is_json` — `json.loads` works on the file.
    - `test_policy_contents` — the allow list equals call 7 exactly; `GPL-2.0-only` is absent.
    - `test_every_allowed_purl_has_reason` — every purl in `allow-dependencies-licenses` has an `x-licence-exceptions` entry with a non-empty `reason`.
    - `test_exception_licences_are_allowed` — every exception's `licence` passes `expression_allowed`.
  - `test_licence_report.py` (hand-written records, no network):
    - `test_vectors` — runs every entry of `docs/licence-test-vectors.json`.
    - `test_multi_classifier_is_or` — `Apache Software License; MIT License` gives `("Apache-2.0 OR MIT", True)`.
    - `test_bare_bsd_classifier_needs_exception` — gives `("UNKNOWN", False)` without an exception and `("BSD-3-Clause", True)` with the `jinja2` exception.
    - `test_proprietary_classifier_alone_refused`
    - `test_unknown_everywhere_refused` — `pysnmp`-shaped record without exception is refused, with exception gives `BSD-2-Clause`.
    - `test_ptouch_exception` — gives `LGPL-2.1-or-later`.
    - `test_expression_field_wins` — a `cffi`-shaped record with `License-Expression: MIT-0` gives `("MIT-0", True)`.
    - `test_check_lists_offenders_sorted`
- [ ] **Step 2: Run** `pytest tests/unit/scripts tests/unit/test_licence_policy.py -v`. Expected: FAIL.
- [ ] **Step 3: Spike S3a (15 min, measurement before the list is fixed).**
  - In a scratch venv, `pip install ./backend`.
  - Then run `pipx run pip-licenses==5.5.5 --python <venv>/bin/python --from=all --with-system --format=json`.
  - List every distinct expression, classifier and metadata string, and every record that `classify` (draft) refuses.
  - Fill `CLASSIFIER_TO_SPDX` and `METADATA_TO_SPDX` with exactly the strings seen.
  - Add an exception for every refused package after reading its licence file, with the file's wording as the reason.
  - Record the field names in the module docstring.
  - **Gate:** a licence that is genuinely outside call 7 is a stop-and-report for the coordinator, not a silent addition.
- [ ] **Step 4: Implement.**
  - `licence_report.py` and `licence-policy.yml`.
  - `licence-gate.yml`:
    - `on: pull_request: branches: [main]`, without `paths:`, so the check exists on every PR.
    - `permissions: contents: read`.
    - Job `dependency-review` with name **`Dependency review`**: checkout, then `actions/dependency-review-action@v5` with `config-file: ./licence-policy.yml`.
  - `licence-backend.yml`, named **`Licences — backend runtime`**:
    - Triggers: `pull_request` with `paths: [backend/pyproject.toml, licence-policy.yml, backend/scripts/licence_report.py]`, and `workflow_dispatch`.
    - Steps: `python -m venv /tmp/rt && /tmp/rt/bin/pip install ./backend`, then `python -m venv /tmp/tool && /tmp/tool/bin/pip install pip-licenses==5.5.5`, then `cd backend && /tmp/tool/bin/python -m scripts.licence_report --python /tmp/rt/bin/python --policy ../licence-policy.yml`.
    - Not required by the ruleset.
  - `backend/Dockerfile` `builder` stage, after the final `pip install`:
    - Copy `licence-policy.yml` and `backend/scripts/licence_report.py` (the script imports nothing from `app`).
    - Create the tool venv `/opt/licence-tool` with `pip-licenses==5.5.5`.
    - Run the script in check mode against `/opt/venv/bin/python`; a violation fails the build.
    - The tool venv never reaches `runtime`.
  - `CONTRIBUTING.md`: where the policy lives, how to add an exception (purl + licence + reason), and that the image build enforces the backend list.
- [ ] **Step 5: Run.**
  - Unit tests: PASS.
  - The CLI against the scratch venv: exit 0, no output.
  - `docker build -f backend/Dockerfile .`: succeeds.
  - Gegenversuch: remove the `pysnmp` exception from a policy copy, then run the CLI with it. Expected: exit 1, prints `pysnmp (UNKNOWN)`.
- [ ] **Step 6: Gate on its own PR.** `Dependency review` is green, and `Licences — backend runtime` runs (the policy changed) and is green.
- [ ] **Step 7: Gegenversuch PRs** (throwaway drafts, closed and deleted afterwards; record names and licences for A7):
  - (a) a **direct** runtime npm dependency whose deps.dev licence is outside the list: red, naming it;
  - (b) a **transitive** case, a runtime dependency that pulls a disallowed package: red; if it stays green, `unknown`/`runtime` scoping is wrong — stop and report;
  - (c) a Markdown-only PR: `Dependency review` green, `Licences — backend runtime` not triggered.
- [ ] **Step 8: Commit** `git add licence-policy.yml docs/licence-test-vectors.json .github/workflows/licence-gate.yml .github/workflows/licence-backend.yml backend/Dockerfile backend/scripts/licence_report.py backend/tests/unit/scripts backend/tests/unit/test_licence_policy.py CONTRIBUTING.md && git commit -m "ci(security): licence policy with a dependency review gate and an image build check" -m "Refs #154"`. Open the PR and squash merge.

### Task A3: Licence and source link in `/api/info`, OpenAPI and `/healthz`

**Files:**
- Create: `backend/app/build_info.py`, `backend/tests/unit/test_build_info.py`
- Modify:
  - `backend/app/schemas/info.py`, `backend/app/api/routes/info.py`
  - `backend/app/main.py` (`FastAPI(..., license_info=...)`, `/healthz` `repository` through `public_repo_url`)
  - `backend/tests/integration/api/test_info.py`, plus the existing healthz test file (locate with `grep -rln '"repository"' backend/tests`)
  - `frontend/src/api/schema.gen.ts` (regenerated)
  - `frontend/src/test-utils.tsx` (`INFO` fixture gains both fields), `frontend/src/features/settings/settings.test.tsx` (its typed info fixtures)
  - `docs/decisions/register.md` (row `D20` "The hub is AGPL-3.0-or-later and links to the source of the running build", 2026-11-05, Accepted, ADR —)

**Interfaces:**
- Produces in `build_info.py`:
  - `PROJECT_LICENSE: Final = "AGPL-3.0-or-later"` and `CANONICAL_REPO_URL: Final = "https://github.com/strausmann/label-printer-hub"`.
  - `def public_repo_url(repo_url: str) -> str` — returns `CANONICAL_REPO_URL` for any of these:
    - a scheme other than `http`/`https`;
    - no host;
    - user info present;
    - a query or a fragment.

    Otherwise it strips a trailing `/` and `.git` and returns the result.
  - `def source_url(repo_url: str, version: str, revision: str) -> str  # D20` — base is `public_repo_url(repo_url)`:
    - `version` matches `^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$` and does not start with `0.0.0-` → `<base>/tree/v<version>`;
    - otherwise `revision` matches `^[0-9a-f]{7,40}$` → `<base>/tree/<revision>`;
    - otherwise `<base>`.
- `Info` gains `license: str` and `source_url: str`. `/healthz` `repository` becomes `public_repo_url(HUB_REPO_URL)`. The OpenAPI `info.license` is `{"name": "AGPL-3.0-or-later", "identifier": "AGPL-3.0-or-later"}`.

- [ ] **Step 1: Write the failing tests**
  - `test_build_info.py::test_source_url` (parametrised; `R` = canonical URL, `SHA` = `"0123456789abcdef0123456789abcdef01234567"`):

    | `repo_url` | `version` | `revision` | Result |
    |---|---|---|---|
    | `R` | `1.1.0` | `SHA` | `R/tree/v1.1.0` |
    | `R` | `1.1.0-rc.1` | `SHA` | `R/tree/v1.1.0-rc.1` |
    | `R` | `dev` | `SHA` | `R/tree/<SHA>` |
    | `R` | `feat-sheets` | `SHA` | `R/tree/<SHA>` |
    | `R` | `0.0.0-dev` | `unknown` | `R` |
    | `R` | `0.0.0-dev` | `SHA` | `R/tree/<SHA>` |
    | `https://example.invalid/fork.git/` | `1.1.0` | `SHA` | `https://example.invalid/fork/tree/v1.1.0` |
    | `javascript:alert(1)` | `1.1.0` | `SHA` | `R/tree/v1.1.0` |
    | `https://token@example.invalid/fork` | `1.1.0` | `SHA` | `R/tree/v1.1.0` |
    | `""` | `dev` | `unknown` | `R` |
  - `test_build_info.py::test_public_repo_url_strips_and_rejects` — covers the same inputs for the helper.
  - `test_info.py::test_info_shape` — the key set gains `"license"` and `"source_url"`.
  - `test_info.py::test_info_license_and_source` — patch `app.main.HUB_VERSION="1.1.0"`, `HUB_REVISION=SHA`, `HUB_REPO_URL=R`. Expect `license == "AGPL-3.0-or-later"` and `source_url == R + "/tree/v1.1.0"`, served without a session.
  - Healthz test `test_healthz_repository_has_no_credentials` — with `HUB_REPO_URL="https://token@example.invalid/x"`, `repository == R`.
  - `test_openapi_license` — `/openapi.json` `info.license.identifier == "AGPL-3.0-or-later"`.
- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `build_info.py`.
  - `get_info` imports `HUB_REPO_URL` lazily next to the other build values.
  - `main.py`: `license_info` and the healthz value.
  - The `D20` row in the register.
  - `cd frontend && pnpm gen:api`, then the two fixtures.
- [ ] **Step 4: Run** the backend suite, plus `pytest tests/unit/test_decision_register.py tests/api/test_openapi_completeness.py`, plus `cd frontend && pnpm typecheck && pnpm test`. Expected: PASS. Gegenversuch:
  - Drop the user-info check → the `token@` case fails.
  - Drop the `0.0.0-` exclusion → the `0.0.0-dev` cases fail.
- [ ] **Step 5: Commit** `git add backend/app/build_info.py backend/app/schemas/info.py backend/app/api/routes/info.py backend/app/main.py backend/tests frontend/src/api/schema.gen.ts frontend/src/test-utils.tsx frontend/src/features/settings/settings.test.tsx docs/decisions/register.md && git commit -m "feat(api): project licence and source link of the running build" -m "Refs #154"`. Every commit of the A3–A5 PR must pass `typecheck` on its own, because rebase merge keeps them.

### Task A4: About page and source links

Load the design skills first: `emil-design-eng`, and `taste-skill:design-taste-frontend` in app-screen mode. Match the existing System look (`PANEL`, `Row`, `Section`).

**Files:**
- Create: `frontend/src/features/about/AboutPage.tsx`, `frontend/src/features/about/AboutPage.test.tsx`, `frontend/e2e/about.spec.ts`
- Modify:
  - `frontend/src/app/router.tsx` (`page("/about", AboutPage)`)
  - `frontend/src/shell/Sidebar.tsx` (+test), `TopBar.tsx`, `SignIn.tsx` (+test), `BootstrapKeyCreated.tsx` (+test), `icons.tsx` (info icon)
  - `frontend/src/features/settings/System.tsx`
  - `frontend/src/i18n/locales/{en,de}/messages.po`

**Interfaces:**
- Consumes: `useInfo().data.license`, `.source_url`, `.version`, `.revision` (A3).
- Produces:
  - `export function AboutPage(): React.JSX.Element` with an empty `<section data-section="dependencies">`; B3 fills it.
  - `export const PROJECT_LICENCE_TEXT_URL = "/licenses/agpl-3.0.txt"`, shipped by A5.
  - `export const AGPL_INFO_URL = "https://www.gnu.org/licenses/agpl-3.0.html"`.

**Copy (en → de).** Every message gets a `context` so a noun and an action never share an id.

| English | Context | German |
|---|---|---|
| "About" | `"page title"` | "Über" |
| "About and licences" | `"link to the about page"` | "Über und Lizenzen" |
| "Licence" | `"heading"` | "Lizenz" |
| "Source code" | `"link to the source of the running version"` | "Quellcode" |
| "Read the licence" | `"action"` | "Lizenz lesen" |
| "About the GNU AGPL" | `"link"` | "Über die GNU AGPL" |
| "This hub is free software under the GNU Affero General Public License, version 3 or later. You can get the source of exactly this version at any time." | — | "Dieser Hub ist freie Software unter der GNU Affero General Public License, Version 3 oder neuer. Den Quellcode genau dieser Version erhalten Sie jederzeit." |

"Source code" must never reuse the log table's existing "Source" message.

- [ ] **Step 1: Write the failing tests**
  - `AboutPage.test.tsx::shows licence, version and source` — fixture with `license`, `version: "1.1.0"`, `revision`, `source_url`. Expect:
    - the texts `AGPL-3.0-or-later` and `1.1.0`;
    - link "Source code" with `href` = `source_url` and a `rel` containing `noopener` and `noreferrer`;
    - link "Read the licence" → `PROJECT_LICENCE_TEXT_URL`;
    - link "About the GNU AGPL" → `AGPL_INFO_URL`.
  - `AboutPage.test.tsx::renders while info is loading` — shows `…` placeholders and no link with an empty `href`.
  - `Sidebar.test.tsx::footer links to about and source`
  - `SignIn.test.tsx::source link before sign-in`
  - `BootstrapKeyCreated.test.tsx::source link`
  - `e2e/about.spec.ts`:
    - desktop: the footer link opens `/about`, heading "About";
    - phone (390×844): the top-bar link "About and licences" opens `/about`.
- [ ] **Step 2: Run** `pnpm test src/features/about src/shell`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - The page, the route, and the links (`// D20` on each source link).
  - The messages: run `pnpm i18n:extract`, translate de, run `pnpm i18n:compile`.
- [ ] **Step 4: Run** `pnpm typecheck && pnpm lint && pnpm test:coverage && pnpm build && pnpm e2e`. Expected: PASS. Gegenversuch: a static `href` to the repo root → the About test fails on `href`.
- [ ] **Step 5: Commit** `git add frontend/src frontend/e2e/about.spec.ts && git commit -m "feat(ui): about page with licence and a link to the running version's source" -m "Refs #154"`

### Task A5: Relicense to AGPL-3.0-or-later

**Files:**
- Create: `backend/tests/unit/test_licence_metadata.py`
- Modify:
  - `LICENSE`, `README.md`, `backend/README.md`, `CLA.md` (§5)
  - `backend/pyproject.toml`, `package.json`, `frontend/package.json`
  - `backend/Dockerfile` (label, plus `COPY LICENSE /opt/app/LICENSE` and `COPY LICENSE /opt/app/web/licenses/agpl-3.0.txt` after the web copy)
  - `.github/workflows/docker-publish.yml` (labels and annotations, two places)
  - `THIRD_PARTY_NOTICES.md` (line 3 only), `docs/policies/trademarks.md:25`
  - the spec lines named in call 20

- [ ] **Step 1: Write the failing test** `test_licence_metadata.py`, reading files relative to the repo root:
  - `test_license_file_is_agpl` — the sha256 of `LICENSE` is `0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0`: the verbatim `https://www.gnu.org/licenses/agpl-3.0.txt`, 661 lines.
  - `test_package_metadata` — `project.license == "AGPL-3.0-or-later"` with no `License ::` classifier (a stale classifier would contradict the expression; hatchling itself accepts both, so this guards consistency, not the build); both `package.json` files carry `license == "AGPL-3.0-or-later"`.
  - `test_image_labels_and_licence_file` — the Dockerfile has `org.opencontainers.image.licenses="AGPL-3.0-or-later"` and copies `LICENSE` to both paths. `docker-publish.yml` contains `licenses=AGPL-3.0-or-later` exactly twice and no `licenses=MIT`.
  - `test_readme_states_licence_history` — the README contains `AGPL-3.0-or-later`, matches `Releases up to and including \d+\.\d+\.\d+ are MIT; from 1\.1\.0 on AGPL-3\.0-or-later`, and contains `HUB_REPO_URL`. Neither the README nor `docs/policies/trademarks.md` contains `fair use` or `MIT license`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** with `LAST_MIT` read just before editing (see Findings):
  - `LICENSE`: the downloaded text, unchanged.
  - README:
    - badge "License: AGPL v3" → `https://www.gnu.org/licenses/agpl-3.0`;
    - License section with the history sentence above, the reasons (brother_ql GPL-3.0-or-later, network service, §13), and "If you run a modified version for others, set `HUB_REPO_URL` to where its source is published — the About page links there";
    - delete the "fair use" paragraph.
  - `trademarks.md:25`: drop the PDF sentence's licence clause.
  - `CLA.md` §5: "(e.g., the GNU Affero General Public License v3.0 or later under which the Project is distributed)".
  - pyproject: `license = "AGPL-3.0-or-later"`, remove the MIT classifier.
  - The other files as listed.
- [ ] **Step 4: Run** the full backend suite and `pip install ./backend` in a scratch venv. Expected: PASS. Gegenversuch: restore the MIT classifier → `test_package_metadata` fails.
- [ ] **Step 5: Commit**, exactly like this: `git add <files above> && git commit -m "chore(license): relicense to AGPL-3.0-or-later" -m "Releases up to and including <LAST_MIT> stay MIT." -m "Refs #154"`. No `!`, no footer except the refs.

### Task A6: Prove the version, merge, release 1.1.0, verify

- [ ] **Step 1: Fold review fix-ups.** After the reviews (CONTRIBUTING: AI reviewers answered, all checks green), run `git rebase -i --autosquash origin/main` locally so the branch is exactly the A3, A4 and A5 commits. Force-push the PR branch.
- [ ] **Step 2: History check.**
  - `git log origin/main..HEAD --format='%s%n%b' | grep -nE '^[a-z]+(\([^)]*\))?!:|BREAKING[ -]CHANGE'` prints nothing.
  - `git log origin/main..HEAD --format=%s` lists exactly three subjects: `feat(api)`, `feat(ui)`, `chore(license)`.
- [ ] **Step 3: Simulated merge + semantic-release dry run (before merging, ruling 5).**
  - Fresh clone `/opt/repos/printhub-agpl-dryrun`; `git fetch origin <pr-branch>`.
  - `git checkout -B main origin/main && git rebase FETCH_HEAD`. This gives the exact rebase-merge result, a fast-forward of `origin/main`.
  - `npm ci`.
  - `GITHUB_TOKEN=$(gh auth token) npx semantic-release --dry-run --no-ci --repository-url https://github.com/strausmann/Label-Printer-Hub.git`.
  - Expected log lines: `Analysis of N commits complete: minor release` and `The next release version is 1.1.0`.
  - Any other result: do not merge; report.
  - Remove the clone afterwards.
- [ ] **Step 4: Merge with "Rebase and merge"** (`gh pr merge --rebase`). Then release: the 04:00 UTC run or `gh workflow run release.yml`. Expected: tag `v1.1.0`, job `images` green.
- [ ] **Step 5: Verify**, with `T=ghcr.io/strausmann/label-printer-hub-backend:1.1.0` and `SHA=$(git rev-list -n1 v1.1.0)`:
  - `docker buildx imagetools inspect $T --format '{{json .Image}}'`: label `licenses` = `AGPL-3.0-or-later`, `revision` = `$SHA`, both platforms present.
  - `docker buildx imagetools inspect $T --raw | jq -r '.annotations["org.opencontainers.image.revision"]'` = `$SHA`.
  - `latest`, `1` and `1.1` point to 1.1.0.
  - The `chore(release)` commit on `main` was pushed by the deploy key: the release run log shows the SSH push.
  - Start the image: `docker run --rm -e PRINTER_HUB_SECRET_KEY=$(python3 -c 'import base64;print(base64.urlsafe_b64encode(b"k"*32).decode())') -e PRINTER_HUB_PUBLIC_URL=http://localhost:8000 -p 8000:8000 $T`.
    - `curl -s localhost:8000/api/info | jq -r .license,.source_url` gives `AGPL-3.0-or-later` and `…/tree/v1.1.0`, and that URL answers 200.
    - `curl -s localhost:8000/licenses/agpl-3.0.txt | head -1` contains `GNU AFFERO GENERAL PUBLIC LICENSE`.
- [ ] **Step 6: Licence note.**
  - Insert under the 1.1.0 heading of `CHANGELOG.md`: "**Licence:** Releases up to and including `<LAST_MIT>` are MIT; from 1.1.0 on AGPL-3.0-or-later."
  - Commit `docs(release): note the licence change in the 1.1.0 changelog` (`Refs #154`) and push.
  - Run `gh release edit v1.1.0 --notes-file <line + current notes>`.
- [ ] **Step 7:** Close #183 with the run link and tick the Part A boxes in #154.

### Task A7: Make the gate required (repository setting, run by the orchestrator)

- [ ] **Step 1: Confirm the check name.** `gh api repos/strausmann/Label-Printer-Hub/commits/<A2 PR head>/check-runs --jq '.check_runs[].name'` lists `Dependency review`.
- [ ] **Step 2: Create the ruleset.** Only the admin role and deploy keys bypass (ruling 4):

```bash
gh api -X POST repos/strausmann/Label-Printer-Hub/rulesets --input - <<'JSON'
{"name": "main: licence gate", "target": "branch", "enforcement": "active",
 "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
 "bypass_actors": [
   {"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"},
   {"actor_type": "DeployKey", "bypass_mode": "always"}],
 "rules": [{"type": "required_status_checks", "parameters": {
   "strict_required_status_checks_policy": false, "do_not_enforce_on_create": false,
   "required_status_checks": [{"context": "Dependency review", "integration_id": 15368}]}}]}
JSON
```

- [ ] **Step 3: Gegenversuch.**
  - Recreate the disallowed-licence draft PR from A2 Step 7a: `gh pr view <n> --json mergeStateStatus` gives `BLOCKED`.
  - The Markdown-only PR is not blocked.
  - Close both and delete the branches.
- [ ] **Step 4: Dependabot.** The next Dependabot patch PR auto-merges after its checks; watch one. `dependabot-auto-merge.yml` gets no bypass, so it must wait for `Dependency review`.
- [ ] **Step 5: Bypass proof.** The next real semantic-release run pushes `chore(release)` and the tag over the deploy key without a rule violation. If it fails, delete the ruleset (`gh api -X DELETE repos/strausmann/Label-Printer-Hub/rulesets/<id>`), re-run the release, and report.
- [ ] **Step 6:** Tick the gate boxes (section B) of #154.

---

## Part B — Release 1.2.0

> Superseded for release 1.6.0 by `docs/superpowers/plans/2026-11-11-licence-part-b.md`; this part stays as history and is not executed.

### Task B1: Backend licence list in the image, `licenses/` misses are 404

**Files:**
- Create: `backend/licences/GPL-3.0-or-later.txt` (verbatim `https://www.gnu.org/licenses/gpl-3.0.txt`, sha256 `3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986`), plus texts for any further SPDX id S3b finds without text
- Modify:
  - `backend/scripts/licence_report.py`, `backend/tests/unit/scripts/test_licence_report.py`
  - `backend/Dockerfile`
  - `backend/app/web/spa.py`, `backend/tests/integration/api/test_spa_serving.py`
  - `docs/decisions/register.md` (row `D21` "Licence lists and SBOMs are generated from what the image ships", 2026-11-05, Accepted, ADR —)

**Interfaces:**
- Produces:
  - `LicenceRecord = TypedDict(name: str, version: str, license: str, licenseText: str | None, repository: str | None)`. These are the field names `rollup-license-plugin` uses, so B3 parses both lists with one function.
  - `def to_records(entries, policy, fallback_dir: Path) -> list[LicenceRecord]  # D21`:
    - the licence comes from `classify`;
    - `licenseText` is the package's own file, else `fallback_dir/<SPDX>.txt` for a single-id licence, else `None`;
    - records are sorted by `name.lower()`.
  - `--output <path>` writes JSON with `ensure_ascii=False`.
  - The CLI fails when any record has `licenseText is None` (`--require-texts`, used in the Docker build).
- Image: `/opt/app/web/licenses/backend.json`, served at `/licenses/backend.json`.

- [ ] **Step 1: Write the failing tests.**
  - `test_to_records_shape` — the five keys exactly.
  - `test_to_records_sorted`
  - `test_to_records_excludes_own_package`
  - `test_text_fallback_for_brother_ql` — a record without `LicenseText` and with a GPLv3+ classifier gets the fallback file's text, which starts with `GNU GENERAL PUBLIC LICENSE`.
  - `test_require_texts_fails_without_text`
  - `test_output_round_trip` — `<script>` and non-ASCII survive unchanged.
  - `test_spa_serving.py::test_missing_licence_file_is_404` — `GET /licenses/nope.json` gives 404, not `text/html`.
  - `test_spa_serving.py::test_existing_licence_file_served`
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Spike S3b (15 min)** in `docker build --target builder`:
  - `ls` the `.py` files of `brother_ql` and `ptouch` in `/opt/venv/lib/python3.12/site-packages`. This is the GPLv3 §6 source in the image.
  - Note every package without a licence text (`brother-ql`, `packbits`, …) and check in a canonical text for each SPDX id needed.
- [ ] **Step 4: Implement.**
  - `to_records`, `--output` and `--require-texts`.
  - `spa.py`: `full_path.startswith(("assets/", "licenses/"))` gives 404.
  - Dockerfile `builder`: run the script with `--output /build/backend-licences.json --require-texts` and `COPY backend/licences`.
  - Dockerfile `runtime`: `COPY --from=builder --chown=hub:hub /build/backend-licences.json /opt/app/web/licenses/backend.json`.
  - The `D21` row.
- [ ] **Step 5: Run** the unit and integration tests (PASS), then check the image:
  - `docker build -f backend/Dockerfile -t lph:b1 .`
  - `docker run --rm --entrypoint python lph:b1 -c "import json;d=json.load(open('/opt/app/web/licenses/backend.json'));m={r['name']:r for r in d};print(len(d), m['brother-ql']['license'], bool(m['brother-ql']['licenseText']), 'pip' in m)"` prints a count above 30, `GPL-3.0-or-later`, `True`, `True`.
  - `docker run --rm --entrypoint sh lph:b1 -c 'test ! -e /opt/licence-tool && ! /opt/venv/bin/pip show pip-licenses'` exits 0.
- [ ] **Step 6: Commit** `build(docker): ship the backend licence list generated from the runtime venv` (`Refs #154`).

### Task B2: Frontend licence list and CycloneDX, read from the one policy

**Files:**
- Create: `frontend/src/licences/build.ts`, `frontend/src/licences/build.test.ts`
- Modify:
  - `frontend/package.json` (devDependency `rollup-license-plugin: "3.2.1"`), `frontend/pnpm-lock.yaml`
  - `frontend/vite.config.ts`, `frontend/src/build.test.ts`
  - `backend/Dockerfile` (`web-builder`: `COPY licence-policy.yml /licence-policy.yml`, `ARG VERSION` → `ENV HUB_VERSION`)

**Interfaces:**
- Produces in `build.ts`:
  - `export function loadPolicy(path: string): {allowed: ReadonlySet<string>; exceptions: ReadonlyMap<string, string>}` — `JSON.parse` of `licence-policy.yml`; exceptions are keyed by purl.
  - `export function expressionAllowed(expr: string, allowed: ReadonlySet<string>): boolean` — same grammar and semantics as the Python `expression_allowed` (both run `docs/licence-test-vectors.json`).
  - `export function isUnacceptableLicence(id: string, policy: Policy, purl?: string): boolean` — an exception for the purl wins; otherwise `!expressionAllowed(id, policy.allowed)`. Passed to the plugin as `unacceptableLicenseTest`.
  - `export const EXTRA_RECORDS: readonly PluginPackage[]` — `{name: "zxing-cpp", version: <zxing-wasm's bundled zxing-cpp version per S1>, license: "Apache-2.0", licenseText: <frontend/licenses/zxing-cpp-Apache-2.0.txt>}`.
  - `export function toLicenceList(packages, extra): string` — the merged list, sorted by name.
  - `export function toCycloneDx(packages, extra, version: string): string` — CycloneDX **1.6**:
    - `bomFormat`, `specVersion: "1.6"`, `version: 1`;
    - `metadata.component {type: "application", name: "label-printer-hub-web", version}`;
    - `components[] {type: "library", name, version, purl: "pkg:npm/<name, @ as %40>@<version>" (none for zxing-cpp; it gets `pkg:github/zxing-cpp/zxing-cpp@<version>`), licenses: [{expression}]}`;
    - sorted by purl; no `serialNumber`, no timestamp.
  - `export async function extraPackagePaths(): Promise<string[]>` — absolute paths of:
    - every package in `@scalar/api-reference`'s production dependency tree (`pnpm list @scalar/api-reference --prod --depth Infinity --json`);
    - `zxing-wasm`;
    - the Workbox runtime packages that `workbox-build` inlines into `sw.js`: `workbox-core`, `workbox-precaching`, `workbox-routing` and `workbox-strategies`, each resolved from `workbox-build`.
- Plugin options:
  - `outputFilename: false`
  - `includePackages: extraPackagePaths`
  - `excludedPackageTest: (name) => name === "label-printer-hub-web"`
  - `unacceptableLicenseTest`
  - `additionalFiles: {"licenses/frontend.json": (p) => toLicenceList(p, EXTRA_RECORDS), "frontend.cdx.json": (p) => toCycloneDx(p, EXTRA_RECORDS, process.env.HUB_VERSION ?? "0.0.0-dev")}`
  - The policy path is `process.env.LICENCE_POLICY ?? fileURLToPath(new URL("../licence-policy.yml", import.meta.url))`; in Docker `/licence-policy.yml`.

- [ ] **Step 1: Write the failing tests.**
  - `licences/build.test.ts`:
    - every entry of `docs/licence-test-vectors.json` gives the same result as in Python;
    - `isUnacceptableLicence("GPL-2.0-only", policy)` → true; `("AFL-2.1 AND AFL-3.0 AND BSD-3-Clause", policy, "pkg:npm/json-schema@0.4.0")` → false (exception);
    - `toCycloneDx` purl for `@tanstack/react-query@5.105.3` is `pkg:npm/%40tanstack/react-query@5.105.3`;
    - two calls give identical strings.
  - `src/build.test.ts` (built output):
    - `dist/licenses/frontend.json` lists `react`, `react-dom`, `@scalar/api-reference`, `zxing-wasm`, `workbox-precaching` and `zxing-cpp`, each with a non-empty `licenseText`;
    - it lists none of `vite`, `vitest`, `typescript`, `eslint`, `@playwright/test`;
    - `dist/frontend.cdx.json` has `pkg:npm/react@19.3.1` and `pkg:npm/%40scalar/api-reference@1.77.0`;
    - `dist/sw.js` contains neither `frontend.json` nor `frontend.cdx.json`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Spike S1 (20 min).** Wire the plugin, then run `pnpm build` once offline (`--network none`) and once online. Record in the PR:
  - whether the `@react-aria/*` and `@fontsource/*` packages appear without `includePackages`;
  - whether `licenseText` comes from `node_modules` or from a tarball download (the plugin depends on `node-fetch`);
  - how large the Scalar subtree is;
  - the zxing-cpp version that zxing-wasm 3.1.6 bundles.

  If the plugin fetches over the network, that is acceptable (CI and Docker have network); it goes into the README build note in B7.
- [ ] **Step 4: Implement** `build.ts`, the plugin, and the Dockerfile lines.
- [ ] **Step 5: Run** `pnpm typecheck && pnpm lint && pnpm test:coverage && pnpm build`. Expected: PASS. Gegenversuch:
  - Remove the `zxing-wasm` path from `extraPackagePaths` → the built-output test fails.
  - Add `json` to `globPatterns` → the `sw.js` assertion fails.
  - Delete `MIT` from a policy copy and point `LICENCE_POLICY` at it → `pnpm build` fails, naming a package.
- [ ] **Step 6: Commit** `build(web): licence list and CycloneDX SBOM of everything the web app ships` (`Refs #154`).

### Task B3: Dependency licences on the About page

Use the design skills as in A4, plus `break-ui` for long names and long texts.

**Files:**
- Create:
  - `frontend/src/features/about/licences.ts`, `licences.test.ts`
  - `DependencyLicences.tsx`, `DependencyLicences.test.tsx`
  - `frontend/e2e/fixtures/backend-licences.json`
- Modify: `AboutPage.tsx`, `frontend/e2e/about.spec.ts`, the e2e app setup that serves `frontend/dist` (copy the fixture to `dist/licenses/backend.json` in `frontend/e2e/global-setup.ts`), `messages.po` (en, de)

**Interfaces:**
- Consumes: `/licenses/frontend.json`, `/licenses/backend.json` (B1, B2).
- Produces:
  - `export type LicenceEntry = {name: string; version: string; licence: string; text: string | null; part: "web" | "server"}`.
  - `export function parseLicenceList(raw: unknown, part): LicenceEntry[]` — a non-array gives `[]`; records without `name` or `version` are dropped; `licenseText: ""` becomes `null`.
  - `export async function fetchLicenceList(url: string, part): Promise<LicenceEntry[] | "missing">` — any non-2xx answer, a `content-type` without `application/json`, or a JSON parse error gives `"missing"`.
  - `export function useLicenceLists(): {entries; missing: Array<"web" | "server">; isPending}` — react-query with `staleTime: Infinity`, fetched only on the About page.

**Copy (en → de):**

| English | Context | German |
|---|---|---|
| "Third-party software" | `"heading"` | "Software von Dritten" |
| "{count} packages" (Lingui plural) | — | "{count} Pakete" |
| "Show licence text" | `"action"` | "Lizenztext anzeigen" |
| "Hide licence text" | `"action"` | "Lizenztext ausblenden" |
| "The licence list of the web app is not included in this build." | — | "Die Lizenzliste der Web-App ist in diesem Build nicht enthalten." |
| "The licence list of the server is not included in this build." | — | "Die Lizenzliste des Servers ist in diesem Build nicht enthalten." |

The two "not included" messages are full sentences, so German gender agreement needs no placeholders.

- [ ] **Step 1: Write the failing tests.**
  - `licences.test.ts`:
    - `parseLicenceList({}, "web")` → `[]`;
    - a record without `version` is dropped;
    - `fetchLicenceList` gives `"missing"` for 404, for **200 `text/html`** (the app shell), and for malformed JSON.
  - `DependencyLicences.test.tsx`:
    - the table has columns package, version, licence and part, with rows sorted by name;
    - a licence text is **not** in the DOM until "Show licence text" is pressed;
    - `"<script>alert(1)</script>"` appears as literal text and no `script` element is created;
    - with the server list missing, the web rows render plus the server message;
    - with both missing, only the two messages show, while the project licence and the source link are still shown.
  - `e2e/about.spec.ts`: the table lists `react` and `brother-ql`; expanding `brother-ql` shows `GNU GENERAL PUBLIC LICENSE` (fixture text from the B1 fallback file).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement**: the component in the `data-section="dependencies"` slot, the e2e fixture copy, and the messages.
- [ ] **Step 4: Run** the web gates and `pnpm e2e`. Expected: PASS. Gegenversuch:
  - Render the text with `dangerouslySetInnerHTML` → the `<script>` test fails.
  - Drop the content-type check → the `text/html` test fails.
- [ ] **Step 5: Commit** `feat(ui): list every shipped third-party licence on the about page` (`Refs #154`).

### Task B4: Third-party notices

**Files:**
- Modify: `THIRD_PARTY_NOTICES.md`, `backend/tests/unit/test_licence_metadata.py`

- [ ] **Step 1: Write the failing test** `test_notices_name_copyleft_dependencies`. The file must contain:
  - `brother_ql`, `GPL-3.0-or-later`, `ptouch`, `LGPL-2.1-or-later`;
  - `/licenses/backend.json`, `/licenses/frontend.json`, `/frontend.cdx.json`, `/opt/app/LICENSE`.

  It must no longer contain "is tracked in".
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Keep every existing table and section as it is, because the sheet-archive branches add rows and a "Sheet type data" section. Then:
  - Rewrite the intro: the complete generated lists are in the image and on the About page.
  - Add a section "Copyleft dependencies":
    - brother_ql: GPL-3.0-or-later, upstream URL, source as `.py` files in the image (S3b), licence text from `backend/licences/` because the wheel ships none;
    - ptouch: LGPL-2.1-or-later, PyPI URL, the same notes;
    - the hub's own source of each version is linked from the About page (GPLv3 §6(d), AGPL §13).
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `docs(docs): name the copyleft dependencies and the generated licence lists` (`Refs #154`).

### Task B5: Provenance, attestations and an image check in CI

**Files:**
- Modify: `.github/workflows/docker-publish.yml` (`provenance: mode=max`), `.github/workflows/ci.yml` (`docker-build` job), `backend/tests/unit/test_release_workflows.py`

- [ ] **Step 1: Write the failing check.**
  - Guard test `test_provenance_max` — `provenance: mode=max` and `sbom: true` in the build step.
  - The `docker-build` job builds with `load: true` and `tags: label-printer-hub:ci`, then gets Syft through `download-syft@v0.24.3` (`syft-version: v1.55.0`) and runs these gates:
    - `syft label-printer-hub:ci --select-catalogers +sbom-cataloger -o json | jq -e '[.artifacts[].name] as $n | ($n | index("react")) and ($n | index("react-dom")) and ($n | index("brother-ql"))'`
    - `docker run --rm --entrypoint sh label-printer-hub:ci -c 'test -s /opt/app/web/licenses/backend.json && test -s /opt/app/web/licenses/frontend.json && test -s /opt/app/web/frontend.cdx.json && test -s /opt/app/LICENSE && test -f /opt/venv/lib/python3.12/site-packages/brother_ql/__init__.py'`
  - Informational only, never a gate (it tests Syft, not the image; Minor 7): one `syft label-printer-hub:ci -o json | jq '[.artifacts[].name] | index("react")'` echoed into the step summary.
- [ ] **Step 2: Run on the PR.** Expected: green. Gegenversuch: on a scratch commit drop the `frontend.cdx.json` entry from `additionalFiles` → the Syft gate fails. Revert.
- [ ] **Step 3: Implement** `provenance: mode=max`. Confirm that no build arg carries a secret: only `VERSION`, `REVISION` and `BUILD_DATE` exist, and `mode=max` records them.
- [ ] **Step 4: Spike S2 (20 min)** on a throwaway pre-release `v0.0.0-ci.2`, built the same way as A1 Step 5, including the cleanup:
  - `docker buildx imagetools inspect ghcr.io/strausmann/label-printer-hub-backend:0.0.0-ci.2 --format '{{json .SBOM}}'` returns an SPDX document for `linux/amd64` and `linux/arm64`, i.e. the merge kept the attestations.
  - `--format '{{json .Provenance}}'` shows `mode=max` content.
  - Check whether the SPDX lists `react`.

  Record the three answers for B7. A missing SBOM after the merge is a stop-and-report; do not switch on `BUILDKIT_SBOM_SCAN_STAGE`.
- [ ] **Step 5: Commit** `ci(docker): max provenance and an image check for the embedded SBOM and licence lists` (`Refs #154`).

### Task B6: CycloneDX SBOM as release asset

**Files:**
- Modify: `.github/workflows/docker-publish.yml` (new job `release-sbom`), `backend/tests/unit/test_release_workflows.py`

**Interfaces:**
- Consumes: `inputs.tag` (A1) and the merged tag from `merge`.

- [ ] **Step 1: Write the failing guard test** `test_release_sbom_job`:
  - the job needs `merge` and runs only when the tag input is non-empty;
  - it has `permissions: {contents: write, packages: read}`;
  - its `run:` steps contain no `${{ inputs.` (the tag arrives via `env:`);
  - it sets `GH_REPO`.
- [ ] **Step 2: Implement** job `release-sbom`:
  - `env: {TAG: ${{ inputs.tag }}, GH_REPO: ${{ github.repository }}, GH_TOKEN: ${{ github.token }}}`.
  - Get Syft as in B5.
  - `syft "ghcr.io/strausmann/label-printer-hub-backend:${TAG}" --platform linux/amd64 --select-catalogers +sbom-cataloger -o "cyclonedx-json=label-printer-hub-${TAG}.cdx.json"`.
  - `jq -e '.components | map(.name) | (index("react") and index("brother-ql"))'` on the file.
  - `gh release upload "v${TAG}" "label-printer-hub-${TAG}.cdx.json" --clobber`.
- [ ] **Step 3: Run** the guard test and actionlint. Expected: PASS, no findings.
- [ ] **Step 4: Live Gegenversuch** with a throwaway pre-release, never a published version:
  - `git tag v0.0.0-ci.3 && git push origin v0.0.0-ci.3`.
  - `gh release create v0.0.0-ci.3 --prerelease --verify-tag --notes "CI test, deleted after the check"`.
  - `gh workflow run docker-publish.yml --ref <branch> -f tag=0.0.0-ci.3`.
  - `gh release view v0.0.0-ci.3 --json assets --jq '.assets[].name'` lists `label-printer-hub-0.0.0-ci.3.cdx.json`.
  - Clean up: `gh release delete v0.0.0-ci.3 --yes --cleanup-tag`, plus the GHCR version as in A1 Step 5.
  - 1.1.0 keeps no SBOM asset. Generating one for it would read a published image without rebuilding it, so it is allowed only on the operator's explicit request (`syft …:1.1.0` + `gh release upload`).
- [ ] **Step 5: Commit** `ci(release): attach a CycloneDX SBOM of the image to each release` (`Refs #154`).

### Task B7: Documentation and closing

**Files:**
- Modify: `README.md` (section "Supply chain: SBOM and provenance"), `backend/tests/unit/test_licence_metadata.py`

- [ ] **Step 1: Write the failing test** `test_readme_supply_chain`. The README contains:
  - `imagetools inspect`, `{{ json .SBOM.SPDX }}`, `{{ json .Provenance }}`;
  - `--select-catalogers +sbom-cataloger`, `frontend.cdx.json`, `.cdx.json`;
  - `licence-policy.yml`.
- [ ] **Step 2: Implement.** The README section covers:
  - getting the SBOM and the provenance without pulling;
  - the release asset;
  - the embedded `frontend.cdx.json`, and why scanners need `+sbom-cataloger` (the S2 result, as measured);
  - Scalar's subtree as an over-approximation;
  - the build note from S1;
  - the licence lists at `/about`;
  - the policy and its exception mechanism;
  - VEX is not provided (a follow-up issue).
- [ ] **Step 3: Run.** Expected: PASS.
- [ ] **Step 4: Commit** `docs(docs): how to get the SBOM, provenance and licence lists of an image` (`Refs #154`).
- [ ] **Step 5: Close-out after 1.2.0.** Check each acceptance criterion of #154 against 1.2.0:
  - `imagetools inspect` returns SBOM and provenance;
  - `syft ghcr.io/…:1.2.0 --select-catalogers +sbom-cataloger` lists `react` and `react-dom`;
  - the release has the `.cdx.json` asset;
  - the About page shows both lists.

  Then tick the boxes, open a follow-up issue for VEX, and close #154 with a summary.

---

## Files shared with the sheet-archive work and merge order

| File | This plan | Sheet archive | Rule |
|---|---|---|---|
| `THIRD_PARTY_NOTICES.md` | A5 line 3; B4 intro + new section | plan 1 "Sheet type data"; plan 2 reportlab rows | never reorder or rewrite existing tables; on conflict keep both |
| `docs/decisions/register.md` | A3 `D20`, B1 `D21` (append) | `D13`–`D19`, `V1`–`V4` | append-only; the sheet archive's next label is `D22` |
| `backend/app/api/routes/info.py`, `test_info.py` | A3 fields | plan 4 flips feature flags | different lines; `test_info_shape` takes both |
| `backend/app/main.py` | A3 `license_info`, healthz value | plans 1–4 lifespan/routers | small separate hunks |
| `backend/app/schemas/info.py`, `frontend/src/api/schema.gen.ts`, `frontend/src/test-utils.tsx` | A3 | every API task | regenerate `schema.gen.ts` with `pnpm gen:api`, never by hand |
| `frontend/src/app/router.tsx` | A4 `/about` | plan 4 sheet routes | keep both |
| `backend/pyproject.toml` | A5 licence lines | plan 2 `reportlab` | different hunks |
| `backend/Dockerfile` | A2 check, A5 label/LICENSE, B1 list, B2 policy/`ARG` | plan 4 test reads it | — |
| specs, `docs/policies/trademarks.md` | A5 | not touched on `feat/sheet-archive-1` | — |

**Order:** A1, then A2 (both without a release; A1 first, because the nightly release must prove the SSH push). Then the A3–A5 PR, before any sheet-archive `feat` merge (open question 2). Then A6 and A7. Part B follows after 1.1.0 and is independent of the sheet archive; B3 is the `feat` that makes 1.2.0.

## Review trace (revision 2)

| ID | Resolution |
|---|---|
| B1 | Done: pre-release `v0.0.0-ci.<n>` for every live test (A1 S5, B5 S4, B6 S4); pre-releases never float and never reach Docker Hub (A1 guard test); no assumption that `latest` = 1.0.2 |
| B2 | Done: `MIT-0` added (call 7); S3a measures before the list is fixed |
| M1 | Done: merge job checks out the tag; index annotation from the tag commit, checked in A1 S5/A6 S5 |
| M2 | Done: release concurrency group `release-<tag>`, never cancelled; guard test |
| M3 | Done: `images` skips `dry_run`; guard test |
| M4 | Done: dry run on the simulated rebase-merge result before merging (A6 S3) |
| M5 | Done per ruling 3: only `Dependency review` required; backend check in the image build + path-filtered PR workflow |
| M6 | Done: classifier `; ` = OR, bare BSD unmapped, exceptions with reasons in the policy, tests for both |
| M7 | Done per ruling 2: the Vite plugin reads the same policy; shared test vectors |
| M8 | Done: `allow-dependencies-licenses` + exception entry for `json-schema@0.4.0`, documented in CONTRIBUTING |
| M9 | Done: canonical-text fallback with `--require-texts`; own `LICENSE` in the image; concrete e2e fixture |
| M10 | Done: `includePackages` for Scalar subtree, `zxing-wasm`, Workbox runtime; zxing-cpp extra record; tests |
| M11 | Done: `licenses/` misses are 404 in `spa.py`; client treats non-JSON as missing; tests |
| M12 | Done per ruling 4: deploy-key push, bypass only admin role + deploy keys |
| M13 | Done: `<LAST_MIT>` read at execution time; regex test |
| Minor 1 | Done: fixtures in A3 file list; each commit passes typecheck |
| Minor 2 | Done: `PRINTER_HUB_PUBLIC_URL` in A6 S5 |
| Minor 3 | Done: `docs/policies/trademarks.md:25` in A5 |
| Minor 4 | Done: reason corrected (consistency, not a hatchling error) |
| Minor 5 | Done: `ptouch` exception → `LGPL-2.1-or-later` |
| Minor 6 | Done: `GH_REPO`, tag via `env:`, input validation + `v` stripping |
| Minor 7 | Done: default-catalogue Syft result informational only |
| Minor 8 | Done: bootstrap screen link; OpenAPI `license_info` |
| Minor 9 | Done: user info rejected; same sanitising for `/healthz` |
| Minor 10 | Done: `fail-on-scopes: [runtime, unknown]`; transitive Gegenversuch |
| Minor 11 | Done: `--with-system`, `pip` asserted in B1 |
| Minor 12 | Done: comment on #154 in A1 S0 |
| Minor 13 | Done: autosquash before the rebase merge (A6 S1) |
