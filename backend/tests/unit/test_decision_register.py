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


def test_every_code_label_is_registered() -> None:
    registered = {label for label, _ in _rows()}
    unknown = {k: v[:3] for k, v in _code_labels().items() if k not in registered}
    assert not unknown, f"labels used in code but missing from the register: {unknown}"
