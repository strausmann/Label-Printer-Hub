# CLAUDE.md — Project Rules and Memory

This file is the **canonical memory** for AI assistants (Claude, Copilot, Gemini, …) working in this repository. It captures every binding rule, decision, and convention so we never re-litigate them.

If a rule is missing or wrong, update this file in the same PR that changes the rule. Treat this as code: reviewed, versioned, authoritative.

---

## 1. Project identity

**Name:** Label Printer Hub
**Repo:** `strausmann/label-printer-hub`
**License:** MIT
**Status:** Early development
**Maintainer:** Björn Strausmann (`strausmannservices@googlemail.com`)

**Purpose:** Self-hosted multi-printer hub for Brother PT-Series and QL-Series label printers. Pull-mode (UI scan-print) and push-mode (webhook). Integrates with Snipe-IT, Grocy, Spoolman. Plugin-based for additional printer models.

---

## 2. Trademark and IP rules — MANDATORY

> **Brother**, **P-touch**, **PT-Series**, and **QL-Series** are trademarks of **Brother Industries, Ltd.**

**Always:**
- Mention this disclaimer prominently in README, CONTRIBUTING, and any user-facing docs.
- Use Brother trademarks **only** for descriptive purposes ("compatible with Brother PT-P750W") — never in a way that suggests endorsement, partnership, or affiliation.

**Never:**
- Use a Brother logo or distinctive branding in this project's icons, banners, or UI.
- Imply that Brother Industries, Ltd. has authorised, sponsored, or supports this project.
- Distribute Brother proprietary firmware, drivers, or copyrighted code.

**Brother Raster Command Reference PDF:** if redistributed in `docs/research/brother-spec/`, include it verbatim and unmodified, with a note that copyright remains with Brother Industries, Ltd.

---

## 3. Architecture (canonical)

### High-level

```
┌──────────────────────┐  HTTP+SSE   ┌──────────────────────┐  TCP/9100   ┌──────────┐
│  Browser / PWA       │ ──────────► │ Backend (Python)     │ ──────────► │ Printer  │
│  Tailwind, HTMX,     │             │ FastAPI, asyncio     │             │ Brother  │
│  Service Worker      │             │ ptouch / brother_ql  │             │ PT / QL  │
│  Notifications API   │ ◄────────── │ pysnmp, EventBus     │ ◄────────── │          │
└──────────────────────┘   SSE       │ Print-Queue + State  │  passive    └──────────┘
                                     └──────────────────────┘  status
```

### Stack — binding decisions

| Layer | Technology | Decision date |
|---|---|---|
| **Backend language** | **Python 3.12+** | 2026-05-10 |
| Backend framework | **FastAPI** | 2026-05-10 |
| Backend DB | **SQLite via SQLModel** | 2026-05-10 |
| Backend printer libs | `nbuchwitz/ptouch` (PT), `pklaus/brother_ql` (QL), `pysnmp` (status) | 2026-05-10 |
| Backend testing | **pytest** + pytest-asyncio + respx | 2026-05-10 |
| **Frontend language** | **Go (web server) + Tailwind CSS + HTMX** | 2026-05-10 (under review — see issue) |
| Frontend testing | Go `testing` + Playwright (e2e) | TBD |
| **PWA** | Manifest + Service Worker + Web Notifications API | 2026-05-10 |
| Container | Docker (multi-stage), non-root UID 1000 | 2026-05-10 |
| CI/CD | GitHub Actions, semantic-release, Dependabot | 2026-05-10 |
| Image registries | GHCR (primary) + Docker Hub (mirror) | 2026-05-10 |

### Plugin architecture (binding)

Every printer model is a plugin in `app/printer_models/<series>.py` implementing the `PrinterModel` protocol from `app/printer_models/base.py`. Auto-discovery happens via the SNMP `enterprises.2435.2.3.9.1.1.7.0` PJL string.

**Never** hardcode model-specific logic in `PrinterService`, the queue, or anywhere outside the plugin module.

### Print queue — binding facts

- Brother printers have **no built-in multi-job queue**. The hub queue is mandatory.
- One `asyncio.Queue` + worker per printer. Single TCP connection at a time.
- Jobs persisted in SQLite (survive restarts).
- Mid-print cancel is **not possible** (Brother spec — no command accepted during print).
- Job states: `queued → printing → completed | failed`, plus `paused` and `cancelled` from queued states.

### Status sources by phase

| Phase | Source | Why |
|---|---|---|
| Pre-print | TCP/9100 `ESC i S` (1B 69 53) → 32-byte status block | Most data: tape, errors, colours, model |
| Active print | Passive read of automatic status notifications | Brother sends them unprompted |
| Idle (dashboard polling) | SNMP Display-OID `1.3.6.1.2.1.43.16.5.1.2.1.1` | Lightweight, doesn't open TCP |

Reference: [`docs/research/2026-05-10-brother-pt-raster-extract.md`](docs/research/2026-05-10-brother-pt-raster-extract.md).

---

## 4. Coding rules

### Test-Driven Development (mandatory)

Every behaviour change follows red → green → refactor:
1. Write failing test
2. Make it pass with minimal code
3. Refactor

If you can't think of a test for what you want to write, you don't yet understand what you're writing. Step back, write the test, then code.

### Code style

- **Python:** ruff (lint + format), mypy strict on `app/`. Line length 100.
- **Go:** gofmt + golangci-lint default config.
- **HTML/CSS/JS:** Prettier defaults.
- **Imports sorted, no wildcards.**
- **No commented-out code** in commits.

### Type hints — mandatory in Python

`mypy --strict` must pass. Use `Protocol`, `dataclass`, `TypedDict`, `Literal`, `StrEnum` over `Any`.

### Error handling

- Validate at system boundaries (HTTP input, external APIs, printer responses).
- Trust internal calls — don't validate the same thing twice.
- No bare `except:`. Catch specific exceptions; let unexpected ones propagate.
- Brother printer errors: parse from status block bits — never invent error categories.

### File and module size

Keep modules focused. If a file exceeds ~400 lines, ask whether it has more than one responsibility.

---

## 5. Commit messages — Conventional Commits (mandatory)

We use **semantic-release** which generates versions and changelogs from commit messages. Wrong commit messages = broken releases.

Format:
```
<type>(<scope>): <subject>

<body>

<footer>
```

| Type | Bump | Use |
|---|---|---|
| `feat` | minor | New feature |
| `fix` | patch | Bug fix |
| `perf` | patch | Performance |
| `docs` | none | Docs only |
| `test`, `refactor`, `chore`, `ci`, `style` | none | Internal |
| `feat!` or `BREAKING CHANGE:` footer | major | Breaking API change |

Scopes: `printer-models`, `queue`, `status`, `api`, `ui`, `webhook`, `docker`, `ci`, `examples`, `docs`.

**Subject:** imperative, lowercase, no period. ≤72 chars.

**Footers:**
- `Closes #N` / `Refs #N`
- `BREAKING CHANGE: <description>`
- `Co-Authored-By: Name <email>` if applicable

### Examples

```
feat(printer-models): add Brother PT-D610BT plugin

Implements PrinterModel protocol for the PT-D610BT desktop label printer.
Tested with TZe-12mm and TZe-24mm tapes.

Closes #42
```

```
fix(queue): retry job no longer duplicates on race
```

```
feat(api)!: rename print() to submit_job()

BREAKING CHANGE: API consumers must update method calls. submit_job() returns
immediately with a JobId instead of blocking until print is done.
```

---

## 6. Releases — semantic-release

- **Trigger:** push to `main` only
- **Tooling:** `semantic-release` with `@semantic-release/changelog`, `/git`, `/github`, `/exec` (for Docker push)
- **Version source:** Conventional Commits since last tag
- **Outputs:** Git tag, GitHub Release, `CHANGELOG.md`, GHCR + Docker Hub image push
- **Maintainers do NOT manually tag releases.**

Configuration: `.releaserc.json`.

### 6.1 Docker image tag scheme — MANDATORY

Every **stable** release publishes the image with **four** tags pointing to the same digest:

| Tag | Example for `1.0.0` | Purpose |
|---|---|---|
| `<major>.<minor>.<patch>` | `1.0.0` | Pin to exact version |
| `<major>.<minor>` | `1.0` | Track latest patch in a minor line |
| `<major>` | `1` | Track latest minor.patch in a major line |
| `latest` | `latest` | Always points to the most recent stable |

Example for `2.4.7`: tags `2.4.7`, `2.4`, `2`, `latest`.

**Pre-releases** (semver with hyphen, e.g. `1.0.0-rc.1` or `2.0.0-beta.3`) publish **only** the full version tag — never `<major>.<minor>`, `<major>`, or `latest`. This prevents a pre-release from accidentally becoming the default for a major or minor line.

Implementation: `.github/workflows/docker-publish.yml` via `docker/metadata-action`. The `type=semver` extractor automatically skips the `{{major}}.{{minor}}` and `{{major}}` patterns for pre-releases; `latest` is gated by an explicit hyphen check.

**Registries** (both receive identical tags + digests):
- GHCR: `ghcr.io/strausmann/label-printer-hub`
- Docker Hub: `docker.io/strausmann/label-printer-hub` (only when `DOCKERHUB_USERNAME` + `DOCKERHUB_TOKEN` secrets are set)

**Architectures:** every release builds `linux/amd64` + `linux/arm64`.

**OCI labels** every image carries:
- `org.opencontainers.image.version` — the full semver
- `org.opencontainers.image.revision` — the git SHA
- `org.opencontainers.image.source` — the GitHub repo URL
- `org.opencontainers.image.licenses` — `MIT`

---

## 7. Dependency management — Dependabot

- **Configuration:** `.github/dependabot.yml`
- **Schedule:** weekly for production deps, weekly for dev deps, daily for security
- **Ecosystems:** `pip` (Python), `gomod` (Go), `npm` (Tailwind tooling), `docker` (base images), `github-actions` (workflows)
- **Labels (mandatory):** every Dependabot PR gets `dependencies` + ecosystem label (`python`, `go`, `npm`, `docker`, `github-actions`)
- **Auto-merge:** enabled for **patch** and **minor** updates that pass all CI checks
- **Reviewer:** Dependabot PRs that need manual review get `@strausmann` requested

Auto-merge is implemented in `.github/workflows/dependabot-auto-merge.yml`.

---

## 8. Labels — managed in code

All issue/PR labels are defined in `.github/labels.yml` and synced via the `labels-sync` workflow. Don't create labels in the GitHub UI — they will be removed on the next sync.

Categories: `type:*`, `area:*`, `status:*`, `priority:*`, `dependencies`, `good-first-issue`, `help-wanted`.

---

## 9. CI workflows

| Workflow | Trigger | Purpose |
|---|---|---|
| `ci.yml` | push, PR | Tests, lint, type-check, coverage |
| `docker-publish.yml` | semantic-release tag | Build + push to GHCR and Docker Hub |
| `release.yml` | push to main | semantic-release |
| `dependabot-auto-merge.yml` | Dependabot PR | Auto-merge after CI green (patch/minor only) |
| `labels-sync.yml` | manual + on `labels.yml` change | Sync labels from `labels.yml` |
| `codeql.yml` | weekly + push | Security scanning |

---

## 10. AI-assisted development

### Claude Code

This file (CLAUDE.md) is loaded automatically. Read top to bottom before making non-trivial changes.

Skill files (when applicable) are in the parent `homelab-management` repo at `.claude/skills/`. This repo doesn't carry skills.

### GitHub Copilot

Copilot Chat instructions are at `.github/copilot-instructions.md`. They are a subset of this file.

### Gemini

Gemini Code Assist configuration: `.gemini/styleguide.md` (referenced in `.gemini/config.yaml`). Configures Gemini to follow our conventions when reviewing PRs.

---

## 11. Security and secrets

- Never commit `.env`, `.pem`, `.key`, or anything in `secrets/`.
- Don't put real tokens in tests or examples — use placeholders like `CHANGE_ME`.
- API keys for Snipe-IT/Grocy/Spoolman live in user-supplied `.env`; the project provides `.env.example` only.
- Webhook API key is generated by the deployer (32 bytes random) and stored in their secret manager.
- Container runs as non-root (UID 1000) — don't break this.

See [SECURITY.md](SECURITY.md) for vulnerability reporting.

### 11.1 Privacy of the maintainer's environment — MANDATORY

This is a public, open-source project. **Nothing in this repository may reveal information about the maintainer's private network, infrastructure, or accounts.**

**Forbidden in this repository (commits, examples, tests, docs, issues, PRs):**

| Category | Examples to avoid | Use instead |
|---|---|---|
| **Internal IPs** | `172.16.50.212`, `192.168.x.x`, `10.x.x.x` if from real network, Tailscale `100.x.x.x` | `192.0.2.10`, `198.51.100.10`, `<printer-ip>` (RFC 5737 documentation ranges) |
| **Internal hostnames** | `hhdocker03`, `hhplex01`, `backend`, real Tailscale machine names | `printer-host`, `docker-host`, generic placeholders |
| **Personal domains** | `*.strausmann.cloud`, `*.strausmann.de`, `*.strausmann.net`, `lager.strausmann.cloud` | `printerhub.example.com`, `your-domain.example.com` |
| **Personal location/contact** | `HH-AK`, `Björn Strausmann`, real serial numbers, MAC addresses, real `sysLocation`/`sysContact` values | `Office`, `<your-name>`, `D5G123456` (synthetic), `04:68:74:00:00:00` (locally administered) |
| **Reverse-proxy specifics** | Pangolin organisation IDs, real OAuth client IDs, real API keys | Generic Traefik/Caddy/Pangolin placeholders |
| **App-specific tokens** | Real Snipe-IT, Grocy, Spoolman tokens | `<your-snipeit-token>` etc. |
| **MAC-based device names** | `BRW046874438070`, `BRN046874438070` | `BRW000000000000` (synthetic) |
| **Internal Vaultwarden item IDs** | UUIDs from the maintainer's vault | Just say "store in your secret manager" |

**When in doubt, ask:** "Could a stranger doxx the maintainer with this?" If yes, redact.

**Where private values DO live:** in the maintainer's separate `homelab-pangolin-client` repository (private deployment glue). That repo is **not** mirrored here. This split is intentional.

### 11.2 Sanitisation checklist for every commit

Before pushing, ensure no commit contains:
- [ ] Real LAN IP addresses
- [ ] Real Tailscale IPs (`100.64.0.0/10`)
- [ ] Real hostnames from the maintainer's infrastructure
- [ ] Real `*.strausmann.*` domains (or any real personal domain)
- [ ] Real serial numbers, MAC addresses, or printer-discovered identifiers
- [ ] Real API keys, tokens, OAuth credentials
- [ ] Real photo/image content with EXIF metadata revealing location

If a contributor accidentally includes any of the above, the maintainer will:
1. Not merge the PR
2. Ask the contributor to amend the commit history
3. (If already merged) Force-push a sanitised history within 24 hours

For new contributors: this rule isn't optional and isn't negotiable. The repository protects the maintainer's privacy, not just the code's quality.

---

## 12. Definition of done — mandatory checklist

A change isn't done until **all** of the following are true:

- [ ] Tests added/updated, all green
- [ ] Lint, format, type-check green
- [ ] Conventional Commit message
- [ ] Documentation touched if behaviour, API, or user-facing config changed
- [ ] If a new printer model: integration test or hardware confirmation in PR description
- [ ] If a breaking change: `BREAKING CHANGE:` footer + migration note in CHANGELOG
- [ ] PR template filled in completely
- [ ] CI green
- [ ] (For maintainers) Squash-merge with Conventional Commit message preserved

---

## 13. Things this project will NOT do (out of scope)

- Print to non-Brother printers (DYMO, Niimbot, Zebra) — separate project
- Bluetooth direct print — use the printer's network interface
- Provide a hosted SaaS — self-hosting only
- Reverse-engineer firmware updates
- Replicate Brother's iPrint&Label feature set

If unsure, open a Discussion.

---

## 14. Update policy for this file

If you discover a rule that should apply, that nobody followed because it wasn't documented:

1. Make the rule explicit here
2. Reference the incident or rationale (link to issue/PR)
3. Update affected places
4. Get review approval like any other PR

This file lives or dies by being kept current.
