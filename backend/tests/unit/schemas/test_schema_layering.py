# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""``app/schemas`` is below ``app/services``: no schema module imports from the services (263-33).

There is no import-linter in the project, so this reads the source of every module under
``app/schemas`` and looks at its import statements.

What it cannot detect:

* a dynamic import (``importlib.import_module("app.services...")``, ``__import__``);
* an import that reaches the services through another package (``app.schemas`` importing
  ``app.api`` which imports ``app.services``): only the direct edge is checked;
* a relative import whose target is decided by where the file sits, beyond the plain
  ``from ..services import x`` form resolved below;
* anything in a module that does not parse (that fails the test with the file name instead).

Imports inside functions and under ``TYPE_CHECKING`` are counted: they are still an edge.
"""

from __future__ import annotations

import ast
from pathlib import Path

import app.schemas

SCHEMAS_DIR = Path(app.schemas.__file__).parent
FORBIDDEN_ROOT = "app.services"


def _imports_services(tree: ast.AST, package: str) -> list[tuple[int, str]]:
    """The ``(line, imported module)`` pairs that point at ``app.services``."""
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == FORBIDDEN_ROOT or alias.name.startswith(FORBIDDEN_ROOT + "."):
                    hits.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - (node.level - 1)]
                module = ".".join([*base, node.module] if node.module else base)
            else:
                module = node.module or ""
            names = [f"{module}.{a.name}" for a in node.names]
            for target in [module, *names]:
                if target == FORBIDDEN_ROOT or target.startswith(FORBIDDEN_ROOT + "."):
                    hits.append((node.lineno, target))
                    break
    return hits


def test_schemas_do_not_import_services() -> None:
    offenders: list[str] = []
    files = sorted(SCHEMAS_DIR.rglob("*.py"))
    assert files, "found no schema modules; the scan would pass on nothing"
    for path in files:
        rel = path.relative_to(SCHEMAS_DIR.parent.parent)
        package = ".".join(rel.with_suffix("").parts[:-1])
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offenders += [
            f"{rel}:{line} imports {mod}" for line, mod in _imports_services(tree, package)
        ]
    assert not offenders, (
        "app/schemas must not import from app/services (move the shared type into app/schemas):\n"
        + "\n".join(offenders)
    )


def test_the_scan_sees_the_import_forms_it_claims_to() -> None:
    source = (
        "import app.services.x\n"
        "from app.services import y\n"
        "from app.services.z import w\n"
        "from ..services import v\n"
        "from . import ok\n"
        "import app.schemas.fine\n"
    )
    hits = _imports_services(ast.parse(source), "app.schemas")
    assert [line for line, _ in hits] == [1, 2, 3, 4]
