# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Guard: the public decision register and the D<n> labels used in code stay in sync."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DECISIONS = REPO / "docs" / "decisions"
REGISTER = DECISIONS / "register.md"
LABEL_RE = re.compile(r"\bD\d+\b")
ROW_RE = re.compile(r"^\|\s*(D\d+)\s*\|(.*)\|\s*$")
LINK_RE = re.compile(r"\]\(([^)]+\.md)\)")


def _rows() -> list[tuple[str, str]]:
    assert REGISTER.is_file(), f"missing {REGISTER}"
    rows = []
    for line in REGISTER.read_text(encoding="utf-8").splitlines():
        m = ROW_RE.match(line)
        if m:
            rows.append((m.group(1), m.group(2)))
    return rows


def _code_labels() -> dict[str, list[str]]:
    # Guard limits: a source-text scan sees comments, strings and identifiers alike;
    # it cannot tell a decision label from an unrelated token such as a hex colour
    # "#D1..." (excluded by the word boundary) — no behaviour test can express
    # "every comment names a registered decision", hence the text scan.
    found: dict[str, list[str]] = {}
    roots = [
        (REPO / "backend" / "app", "*.py"),
        (REPO / "frontend" / "src", "*.ts"),
        (REPO / "frontend" / "src", "*.tsx"),
    ]
    for root, pattern in roots:
        if not root.is_dir():
            continue
        for path in root.rglob(pattern):
            for n, line in enumerate(
                path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
            ):
                for label in LABEL_RE.findall(line):
                    found.setdefault(label, []).append(f"{path.relative_to(REPO)}:{n}")
    return found


def test_register_labels_unique_and_linked() -> None:
    rows = _rows()
    labels = [label for label, _ in rows]
    assert labels, "register has no rows"
    assert len(labels) == len(set(labels)), f"duplicate labels: {labels}"
    for label, rest in rows:
        for target in LINK_RE.findall(rest):
            assert (DECISIONS / target).is_file(), f"{label}: ADR link {target} does not resolve"


def _header_status(adr: Path) -> str:
    """Leading status word of an ADR header, e.g. ``Accepted (amended …)`` -> ``Accepted``."""
    for line in adr.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^- \*\*Status:\*\*\s*(\w+)", line)
        if m:
            return m.group(1)
    raise AssertionError(f"{adr.name}: no '- **Status:**' header line")


def _row_status(rest: str) -> str:
    # `rest` is everything after the label cell: title | date | status | adr
    cells = [c.strip() for c in rest.strip().strip("|").split("|")]
    m = re.match(r"\w+", cells[2])
    assert m, f"unreadable status cell: {cells}"
    return m.group(0)


def test_register_status_equals_adr_header_status() -> None:
    # Guard limits: reads the header line text; it cannot tell a status that is
    # true from one that is merely consistent in both places — see the next test.
    mismatches = []
    for label, rest in _rows():
        for target in LINK_RE.findall(rest):
            adr_status = _header_status(DECISIONS / target)
            if _row_status(rest) != adr_status:
                mismatches.append(f"{label}: register {_row_status(rest)} vs {target} {adr_status}")
    assert not mismatches, f"register and ADR header disagree: {mismatches}"


def test_decision_used_in_code_is_not_proposed() -> None:
    # A label that code already follows has shipped; an ADR still `Proposed` then
    # is stale (ADR upkeep rule in CLAUDE.md: Accepted in the same PR that ships).
    in_code = _code_labels()
    stale = []
    for label, rest in _rows():
        if label in in_code and _row_status(rest) == "Proposed":
            stale.append(f"{label} is used in {in_code[label][0]} but registered as Proposed")
    assert not stale, f"shipped decisions still Proposed: {stale}"


def test_adr_index_status_equals_header_status() -> None:
    index = (DECISIONS / "README.md").read_text(encoding="utf-8")
    mismatches = []
    for m in re.finditer(r"^\| \[(\d{4})\]\(([^)]+\.md)\) \|.*\| (\w+)[^|]*\|\s*$", index, re.M):
        number, target, shown = m.groups()
        header = _header_status(DECISIONS / target)
        if header != shown:
            mismatches.append(f"{number}: index {shown} vs header {header}")
    assert not mismatches, f"README index and ADR header disagree: {mismatches}"


def test_every_code_label_is_registered() -> None:
    registered = {label for label, _ in _rows()}
    unknown = {k: v[:3] for k, v in _code_labels().items() if k not in registered}
    assert not unknown, f"labels used in code but missing from the register: {unknown}"
