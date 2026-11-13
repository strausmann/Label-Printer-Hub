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
