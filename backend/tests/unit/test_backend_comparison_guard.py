# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Source guard: a printer's page/tape kind is asked through one helper only (#208).

It reads the syntax tree, so docstrings and comments cannot trip it. A comparison spelled
differently is not seen: ``in {"ipp"}``, a local variable holding the backend, ``getattr(p,
"backend")``, ``row["backend"]`` / ``.get("backend")``, a backend under another attribute name,
and ``match`` statements. Kind logic that never mentions ``backend`` is outside it too (the cache
row's ``kind`` in ``status_freshness.backoff_of`` without ``page=``, and ``sse_snapshot``). A
behaviour test cannot pin where a check lives, hence a source guard.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"
HELPER_MODULE = APP / "models" / "printer.py"


def _is_backend_attr(node: ast.expr) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "backend"


def _is_ipp_literal(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return node.value == "ipp"
    return isinstance(node, ast.Name) and node.id == "IPP_BACKEND"


def _offending_lines(tree: ast.AST) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        if any(_is_backend_attr(o) for o in operands) and any(_is_ipp_literal(o) for o in operands):
            lines.append(node.lineno)
    return lines


def test_guard_sees_a_comparison_and_ignores_docstrings() -> None:
    bad = ast.parse('def f(p):\n    return p.backend == "ipp"\n')
    assert _offending_lines(bad) == [2]
    sql = ast.parse('q = select(Printer).where(Printer.backend == "ipp")\n')
    assert _offending_lines(sql) == [1]
    reversed_ = ast.parse("def f(p):\n    return IPP_BACKEND != p.backend\n")
    assert _offending_lines(reversed_) == [2]
    docstring = ast.parse('def f(p):\n    """p.backend == "ipp" """\n    # p.backend == "ipp"\n')
    assert _offending_lines(docstring) == []


def test_no_backend_comparison_outside_the_helper() -> None:
    found: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        if path == HELPER_MODULE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        found.extend(f"{path.relative_to(APP.parent)}:{n}" for n in _offending_lines(tree))
    assert not found, (
        "compare a backend through app.models.printer.is_page_printer / is_page_backend: "
        + ", ".join(found)
    )
