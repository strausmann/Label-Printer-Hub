<!--
Thanks for your contribution. Please fill in this template completely.
The PR title MUST follow Conventional Commits — see CONTRIBUTING.md.
-->

## Summary

<!-- One paragraph: what does this PR do, why is it needed? -->

## Contributor License Agreement (CLA)

The [Contributor License Agreement](../CLA.md) is signed once through CLA assistant.
On your first pull request the bot comments with a link; the `license/cla` check must
pass before merge.

- [ ] I have signed the CLA via CLA assistant.

## Linked issue

Closes #
<!-- or Refs # if it's a partial fix -->

## Target branch

<!-- Mark one. See CONTRIBUTING.md, "Milestones, branches and releases". The release-impact check enforces it. -->

- [ ] `main` — patch-level or non-releasing changes only (`fix`, `perf`, `docs`, `ci`, `chore`, …; no `feat`, `!` or `BREAKING CHANGE:`)
- [ ] `milestone/x.y.0` — feature work for that milestone
- [ ] Milestone release `milestone/x.y.0` → `main` — merge with a **merge commit**, not squash

## Type of change

<!-- Mark with x. Multiple OK. -->

- [ ] Bug fix (non-breaking)
- [ ] New feature (non-breaking)
- [ ] Breaking change (`feat!` / `fix!`) — describe migration path below
- [ ] New printer model plugin
- [ ] Documentation only
- [ ] Refactor / chore (no behaviour change)
- [ ] Test only
- [ ] CI / release tooling

## Hardware tested on

<!-- Required if this affects printer interaction. List the printer(s) you tested with. -->

- [ ] Brother PT-Series (model: ___)
- [ ] Brother QL-Series (model: ___)
- [ ] Other: ___
- [ ] No hardware impact

## Test coverage

- [ ] Added/updated unit tests
- [ ] Added/updated integration tests
- [ ] Hardware tests added (if applicable)
- [ ] Existing tests still pass

## Checklist

- [ ] PR title follows Conventional Commits (`feat(...): ...` etc.)
- [ ] All commits are signed off (if applicable)
- [ ] CHANGELOG entry isn't needed (semantic-release generates it)
- [ ] Documentation updated (if behaviour, API, or config changed)
- [ ] Website pages changed in English and German (if any page under `website/src/content/docs/` changed)
- [ ] UI change visible in a README screenshot → ran `pnpm screenshots` and committed the changed PNGs
- [ ] Changes a recorded decision → ADR added/amended and register updated (`docs/decisions/`)
- [ ] No private IPs, hostnames, domains, real tokens, or PII in commits
- [ ] CI is green (will be checked again after CI runs)

## Migration / breaking change notes

<!-- If this is a breaking change: what does the user need to do? Required for any feat!/fix!/BREAKING CHANGE: footer. -->

## Screenshots / output

<!-- If UI or output changed, paste before/after. Sanitise IPs/hostnames. -->
