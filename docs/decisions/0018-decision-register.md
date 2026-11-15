<!--
SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# 0018 — Public decision register with D/V/L labels

- **Status:** Accepted
- **Date:** 2026-11-04
- **Deciders:** maintainer
- **Decision label:** D9

## Context

ADRs explain architecture decisions in full, but a code comment cannot point at a paragraph. Developers reading a line of code want to know which decision it follows and where else that decision applies, without reading every ADR.

## Decision

We keep a register of short labels in `docs/decisions/register.md`, one line per label with title, date, status and a link to an ADR where one exists. Three kinds exist: `D<n>` decision, `V<n>` assumption still to be verified, `L<n>` lesson learned. Code comments, commit messages and docs cite a label where code follows a decision, so searching for the label finds all related code.

The register is public. Changing a decided behaviour adds a new label that supersedes the old row; rows are never rewritten or reused. ADRs remain the place for full rationale and are only changed in their status header.

A guard test in the backend test suite checks that labels are unique, that ADR links resolve, and that every `D<n>` used in `backend/app` and `frontend/src` has a row in the register.

## Options considered

### Option A — public register plus guard test (picked)
- Pros: cheap to maintain, searchable, enforced.
- Cons: one more file to update with each decision.

### Option B — ADRs only
- Pros: no extra artifact.
- Cons: no stable short handle for code comments.

### Option C — private register
- Pros: freedom to note unfinished thoughts.
- Cons: contributors cannot resolve labels they see in public code.

## Consequences

- Adding a `D<n>` comment without a register row fails the test suite.
- The guard is a text scan: it cannot tell a label from an unrelated token with the same shape; word boundaries avoid hex colours.

## References

- Spec section 9; related ADR-0015 to ADR-0019
