# Code-review patterns and recurring findings

This file collects recurring findings from PR reviews — both AI (Gemini Code Assist, GitHub Copilot) and human — so the same mistakes don't show up in PR after PR.

It is **mandatory reading** before opening a PR. AI tools (Claude, Copilot, Gemini) configured for this repo are pointed here so they prefer these patterns proactively.

When an AI reviewer surfaces a new pattern that's likely to recur, add it here in the same PR that addresses the finding.

---

## Python

### Frozen dataclasses must not contain mutable fields

`@dataclass(frozen=True, slots=True)` only prevents *attribute reassignment*. A `list`, `dict`, or `set` field can still be mutated in place by callers, which silently breaks the immutability guarantee.

**Bad:**
```python
@dataclass(frozen=True)
class StatusBlock:
    errors: list[PrinterError]   # mutable! callers can errors.append(...)
```

**Good:**
```python
@dataclass(frozen=True, slots=True)
class StatusBlock:
    errors: PrinterError          # IntFlag — immutable, supports `in` membership
    # or: errors: tuple[PrinterError, ...]
    # or: errors: frozenset[PrinterError]
```

**Why we landed on `IntFlag`:** for *flag combinations* it is the idiomatic Python type — supports `in` (`PrinterError.NO_MEDIA in sb.errors`), bitwise combine, and unknown bits are masked off automatically by the default `CONFORM` boundary in Python 3.11+.

Source: PR #29 review (Gemini + Copilot).

---

### Use `IntFlag(combined_int)` over manual bit-mapping loops

When decoding a multi-byte error/flag field where each bit maps to a named flag, a manual loop is wasteful — `IntFlag` does it for you.

**Bad:**
```python
def _decode_errors(b1: int, b2: int) -> list[PrinterError]:
    flags = []
    bit_map_1 = [(0x01, NO_MEDIA), (0x02, ...), ...]   # rebuilt every call
    bit_map_2 = [(0x01, REPLACE_MEDIA), ...]
    for mask, flag in bit_map_1:
        if b1 & mask:
            flags.append(flag)
    # ... and the same for b2
    return flags
```

**Good:**
```python
class PrinterError(IntFlag):
    NO_MEDIA = 1 << 0          # info1 bit 0
    CUTTER_JAM = 1 << 2        # info1 bit 2
    REPLACE_MEDIA = 1 << 8     # info2 bit 0 → upper byte
    COVER_OPEN = 1 << 12       # info2 bit 4

def _decode_errors(b1: int, b2: int) -> PrinterError:
    return PrinterError(b1 | (b2 << 8))
```

The `IntFlag` definition aligns each named flag with its bit position; combining the two bytes is a single bitwise op. Unknown bits are silently dropped.

Source: PR #29 review (Gemini + Copilot).

---

### Don't include type stubs for libraries the project forbids

The repo's [Gemini styleguide](../../.gemini/styleguide.md) and [Claude config](../../CLAUDE.md) forbid the `requests` library — we use `httpx` exclusively. Including `types-requests` in `[project.optional-dependencies] dev` is therefore inconsistent and adds bloat.

Same applies to any other forbidden dependency: don't bring its type stubs along by reflex.

Source: PR #29 review (Gemini).

---

### Test assertions must be tight

Permissive assertions hide regressions. If a value should *deterministically* be one specific thing, assert exactly that — don't write `in (A, B, C) or value is None` "just in case".

**Bad:**
```python
def test_qlseries_has_no_tape_colour() -> None:
    sb = parse(QL_FIXTURE)
    # QL doesn't populate this byte
    assert sb.tape_color in (TapeColor.UNKNOWN, TapeColor.WHITE) or sb.tape_color is None
```

**Good:**
```python
def test_qlseries_has_no_tape_colour() -> None:
    sb = parse(QL_FIXTURE)
    # QL leaves byte 24 reserved (0x00) → must map to UNKNOWN
    assert sb.tape_color == TapeColor.UNKNOWN
```

Same rule for exception types: catch the *specific* exception you expect, not `Exception`.

**Bad:**
```python
with pytest.raises(Exception):
    sb.media_width_mm = 99
```

**Good:**
```python
import dataclasses
with pytest.raises(dataclasses.FrozenInstanceError):
    sb.media_width_mm = 99
```

Source: PR #29 review (Gemini + Copilot).

---

## CI / GitHub Actions

### Don't use hyphens in `workflow_dispatch` input names

GitHub Actions expression parser treats `inputs.dry-run` as `inputs.dry` minus `run` — silent subtraction, the workflow runs but the input value is wrong.

**Bad:**
```yaml
inputs:
  dry-run:
    type: boolean
# referenced as ${{ inputs.dry-run }} → parsed as subtraction!
```

**Good:**
```yaml
inputs:
  dry_run:                     # snake_case — identifier-safe
    type: boolean
# referenced as ${{ inputs.dry_run }}
```

If you must keep a hyphenated name, use bracket notation: `${{ inputs['dry-run'] }}`. Snake-case is cleaner.

Source: PR #32 review (Copilot).

---

### `workflow_dispatch` jobs need a branch guard if they publish

`workflow_dispatch` can be triggered against any ref from the Actions UI dropdown. Without a guard, a maintainer (or a malicious PAT holder) could publish a release from a feature branch — completely bypassing the main-branch contract.

**Bad:**
```yaml
on:
  workflow_dispatch:
jobs:
  release:
    name: semantic-release
    runs-on: ubuntu-24.04
    steps: ...
```

**Good:**
```yaml
on:
  workflow_dispatch:
jobs:
  release:
    name: semantic-release
    runs-on: ubuntu-24.04
    if: github.ref == 'refs/heads/main'   # release only from main, ever
    steps: ...
```

This applies to any workflow that publishes (releases, registry pushes, deployments). Test/build workflows can run on any ref freely.

Source: PR #32 review (Copilot).

---

### Be precise about semantic-release skip behaviour

semantic-release evaluates the **entire commit history since the last tag**, not just commits made since the previous *run*. A common misstatement:

**Wrong:** "Push only `chore` commits today to skip a scheduled release."

If a `feat`/`fix`/`perf` commit is already on `main` from an earlier merge, the next scheduled run **will** publish that release. Adding `chore` commits afterwards does not suppress it.

**Right:** "A scheduled run only skips when there are no `feat`/`fix`/`perf` commits between the last tag and HEAD. The only way to postpone a release window is to defer version-bumping merges."

Source: PR #32 review (Gemini + Copilot, three places).

---

## Process

### Wait for AI reviewers before merging — even on small PRs

Gemini and Copilot post within 1-2 minutes after a push. Merging with `--admin` before they've commented forfeits the review value:

- The reviewers' findings end up on a follow-up PR instead of being addressed inline
- The original PR's diff is no longer there for context when the follow-up arrives
- It signals "AI reviews are nice-to-have" — they're not

**Rule:** wait at least until both AI reviewers have posted. If the PR is *truly* time-critical (broken main, security fix), call it out explicitly in the PR description and own the bypass — and address any post-merge findings in a follow-up PR.

Source: PR #30 (the maintainer merged via `--admin` before Copilot's comment landed; the Copilot finding was valid and required a separate follow-up PR).

---

### Side-effects must be in the PR description

If a PR primarily fixes A but also changes B as a side-effect, **list both in the description**. Reviewers shouldn't have to discover changes by reading the diff line-by-line.

**Real example:** PR #30's description focused on "make Python lint/test job branch-tolerant" but also removed `|| true` from the mypy step (turning it from warn-only into a hard gate). That second change was valid but invisible from the description. Copilot caught it; the maintainer should have led with it.

**Rule:** every behavioural change goes in the description's `Changes` section, even if it's "incidental". If you find yourself thinking "I'll just slip this in", that's the signal to break it out.

Source: PR #30 review (Copilot).

---

## How to use this file

- **Before opening a PR**: skim the relevant section (Python / CI / Process). Self-correct things you'd otherwise have to address in review.
- **After receiving an AI review**: if a finding represents a recurring class of mistake (not a one-off typo), add a section here in the same follow-up commit.
- **Format**: start with the rule. Show "bad" and "good" examples. Cite the PR where the finding originated.

A finding with no clear takeaway pattern (e.g. a typo, a one-off naming nit) doesn't need to land here — only patterns that are likely to recur.
