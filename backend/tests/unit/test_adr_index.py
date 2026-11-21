# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Guard: the status in the ADR index equals the status in the ADR's own header.

The index (``docs/decisions/README.md``) and each ADR carry a status. They are written by hand in
two places, so they drift (ADR 0012 was "Superseded" in the index and a sentence in its header).

Rules the test applies:

* the first ADR link of an index row (``[0012](0012-....md)``) names the ADR file;
* the *status keyword* is the first word of the status text (``Accepted``, ``Superseded``,
  ``Deprecated``, ``Proposed``); qualifiers such as "(amended by 0020)" are free text and are not
  compared.

Limit: this compares keywords, not the meaning of the qualifier text. It also cannot tell whether
the successor named is the right one; it only requires that one is named.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DECISIONS = REPO / "docs" / "decisions"
INDEX = DECISIONS / "README.md"
ROW_RE = re.compile(r"^\|\s*\[(\d{4})\]\(([^)]+\.md)\)[^|]*\|[^|]*\|\s*(.*?)\s*\|\s*$")
HEADER_RE = re.compile(r"^- \*\*Status:\*\*\s*(.*)$", re.MULTILINE)
KEYWORDS = {"Accepted", "Superseded", "Deprecated", "Proposed"}


def _keyword(status: str) -> str:
    words = re.sub(r"[`*_]", "", status).split()
    return words[0].rstrip(".,;:") if words else ""


def _rows() -> list[tuple[str, str, str]]:
    rows = []
    for line in INDEX.read_text(encoding="utf-8").splitlines():
        m = ROW_RE.match(line)
        if m:
            rows.append((m.group(1), m.group(2), m.group(3)))
    return rows


def test_adr_index_status_equals_header_status() -> None:
    rows = _rows()
    assert len(rows) >= 20, f"the index regex matched only {len(rows)} rows"
    problems = []
    for number, link, index_status in rows:
        path = DECISIONS / link
        assert path.is_file(), f"index row {number} links a missing file {link}"
        header = HEADER_RE.search(path.read_text(encoding="utf-8"))
        assert header, f"{link} has no '- **Status:**' header line"
        head_kw, index_kw = _keyword(header.group(1)), _keyword(index_status)
        if head_kw not in KEYWORDS:
            problems.append(f"{link}: header status {head_kw!r} is not one of {sorted(KEYWORDS)}")
        elif head_kw != index_kw:
            problems.append(f"{link}: header says {head_kw!r}, index says {index_kw!r}")
    assert problems == []


def test_every_adr_file_is_in_the_index() -> None:
    indexed = {link for _, link, _ in _rows()}
    on_disk = {p.name for p in DECISIONS.glob("[0-9][0-9][0-9][0-9]-*.md")}
    assert on_disk - indexed == set()


# --- Reciprocal supersede and amend links -------------------------------------------------------
#
# A link between two ADRs is written by hand on both sides: "Supersedes" on the new one and
# "Superseded by" on the old one, "Amends" on the new one and "Amended by" on the old one. The
# status check above compares only the leading word, so a one-sided link stayed green (0008 named
# no amending ADR while 0025 and the index said it was amended by 0025).
#
# What the guard reads, in the header only (every line before the first "## " heading):
#
# * ``- **Supersedes:**``, ``- **Superseded by:**``, ``- **Amends:**``, ``- **Amended by:**``: every
#   ADR number (``0NNN``) in the value;
# * ``- **Status:**``: the numbers right after "Superseded by" and after "amended by";
# * ``- **Amended:**``: the numbers right after "by" ("2026-11-11 by [ADR 0026](…)").
#
# Limits: a number is a four-digit token starting with 0, so it cannot tell an ADR number from
# another such token in a field value; prose outside the header and other relations ("Related",
# "Restates") are not read. It checks that both sides name each other, not that the link is right.

FIELD_RE = re.compile(r"^- \*\*(?P<field>[^*:]+):\*\*\s*(?P<value>.*)$")
NUMBER_RE = re.compile(r"\b0\d{3}\b")
# An ADR reference right after the anchor, up to the end of the clause.
_REF = r"\s+(\[?(?:ADR[- ]?)?0\d{3}[^:;—)]*)"
STATUS_SUPERSEDED_RE = re.compile(r"\bSuperseded by" + _REF)
STATUS_AMENDED_RE = re.compile(r"\b[Aa]mended by" + _REF)
AMENDED_BY_RE = re.compile(r"\bby" + _REF)

RELATIONS = {
    # field on the newer ADR -> field the older ADR must carry, and back
    "supersedes": "superseded_by",
    "superseded_by": "supersedes",
    "amends": "amended_by",
    "amended_by": "amends",
}


def _numbers(text: str) -> set[str]:
    return set(NUMBER_RE.findall(text))


def _header_links(text: str) -> dict[str, set[str]]:
    """The supersede and amend links an ADR header names, by relation."""
    links: dict[str, set[str]] = {relation: set() for relation in RELATIONS}
    for line in text.splitlines():
        if line.startswith("## "):
            break
        m = FIELD_RE.match(line)
        if not m:
            continue
        field, value = m.group("field").strip().lower(), m.group("value")
        if field == "status":
            for ref in STATUS_SUPERSEDED_RE.findall(value):
                links["superseded_by"] |= _numbers(ref)
            for ref in STATUS_AMENDED_RE.findall(value):
                links["amended_by"] |= _numbers(ref)
        elif field == "amended":
            for ref in AMENDED_BY_RE.findall(value):
                links["amended_by"] |= _numbers(ref)
        elif field.replace(" ", "_") in RELATIONS:
            links[field.replace(" ", "_")] |= _numbers(value)
    return links


def link_problems(decisions: Path) -> list[str]:
    """Every supersede or amend link that only one of the two ADRs names."""
    adrs = {p.name[:4]: p for p in sorted(decisions.glob("[0-9][0-9][0-9][0-9]-*.md"))}
    links = {number: _header_links(p.read_text(encoding="utf-8")) for number, p in adrs.items()}
    problems = []
    for number, relations in links.items():
        for relation, targets in relations.items():
            back = RELATIONS[relation]
            for target in sorted(targets):
                if target == number:
                    problems.append(f"{number}: {relation} names itself")
                elif target not in links:
                    problems.append(f"{number}: {relation} {target}, but there is no ADR {target}")
                elif number not in links[target][back]:
                    problems.append(
                        f"{number}: {relation} {target}, but {target} has no {back} {number}"
                    )
    return problems


def test_supersede_and_amend_links_are_on_both_sides() -> None:
    assert link_problems(DECISIONS) == []


def test_a_one_sided_link_is_reported(tmp_path: Path) -> None:
    # Counter-test of the guard itself: both sides named -> clean; one side removed -> reported.
    amended_by = "- **Amended by:** [0002](0002-new.md)\n"
    old = "# 0001 — Old\n\n- **Status:** Accepted\n" + amended_by + "\n## Context\n"
    new = (
        "# 0002 — New\n\n- **Status:** Accepted\n- **Amends:** [0001](0001-old.md)\n\n## Context\n"
    )
    (tmp_path / "0001-old.md").write_text(old, encoding="utf-8")
    (tmp_path / "0002-new.md").write_text(new, encoding="utf-8")
    assert link_problems(tmp_path) == []

    (tmp_path / "0001-old.md").write_text(old.replace(amended_by, ""), encoding="utf-8")
    assert link_problems(tmp_path) == ["0002: amends 0001, but 0001 has no amended_by 0002"]


def test_status_and_amended_lines_count_as_links(tmp_path: Path) -> None:
    # "Superseded by ADR-0002" in the status and "Amended: <date> by [ADR 0003](…)" are links too;
    # a date or a "by" that names no ADR is not.
    (tmp_path / "0001-old.md").write_text(
        "- **Status:** Superseded by ADR-0002\n"
        "- **Amended:** 2026-11-11 by [ADR 0003](0003-x.md): the name\n"
        "- **Amended:** 2026-11-09 (#226) — the paths, consumed by the UI (0004)\n",
        encoding="utf-8",
    )
    (tmp_path / "0002-new.md").write_text("- **Status:** Accepted\n", encoding="utf-8")
    (tmp_path / "0003-x.md").write_text("- **Status:** Accepted\n", encoding="utf-8")
    (tmp_path / "0004-y.md").write_text("- **Status:** Accepted\n", encoding="utf-8")
    assert link_problems(tmp_path) == [
        "0001: superseded_by 0002, but 0002 has no supersedes 0001",
        "0001: amended_by 0003, but 0003 has no amends 0001",
    ]
