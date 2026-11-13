"""Guard: the paths named in the contributor docs exist in the repository.

What it checks, and where it stops:

* every entry of a fenced *tree block* (a root line such as ``backend/app/`` followed by
  ``├──`` / ``└──`` lines; the fence may be indented, as in a list item) in ``docs/architecture.md`` and ``docs/plugin-development.md``;
* every inline code span in those two files that starts with a known repository root
  (``backend/``, ``frontend/``, ``docs/``, ``examples/``, ``.github/``).

It does NOT check prose that names a file without code formatting, paths that do not start with a
known root, symbol names inside files, or whether a comment next to a tree entry is still true. A
text scan cannot know what a sentence means; a behaviour test cannot express "the documentation
names no file that is gone", so the scan is the only tool for this class of drift.

A tree entry may use ``*`` as a wildcard for one path segment (``integrations/*/plugin.py``); it
passes when at least one file matches.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ROOTS = ("backend/", "frontend/", "docs/", "examples/", ".github/")
TREE_CHARS = ("├── ", "└── ")
INLINE_RE = re.compile(r"`([^`\n]+)`")


def _fenced_blocks(text: str) -> list[tuple[int, list[str]]]:
    """Fenced blocks as ``(line number of the first content line, lines)``.

    A fence may be indented (a list item); the fence's own indentation is stripped from the lines.
    """
    blocks: list[tuple[int, list[str]]] = []
    current: list[str] | None = None
    indent = 0
    start = 0
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip(" ")
        if stripped.startswith("```"):
            if current is None:
                current, indent, start = [], len(line) - len(stripped), number + 1
            else:
                blocks.append((start, current))
                current = None
        elif current is not None:
            current.append(line[indent:] if line[:indent].strip() == "" else line)
    return blocks


def tree_entries(block: list[str]) -> list[tuple[int, str]]:
    """Return ``(index in block, path)`` for a tree block; ``[]`` when the block is no tree."""
    if len(block) < 2 or not block[0].rstrip().endswith("/"):
        return []
    if not any(any(c in line for c in TREE_CHARS) for line in block[1:]):
        return []
    root = block[0].split("#")[0].strip()
    stack: list[str] = [root]
    paths: list[tuple[int, str]] = []
    for index, line in enumerate(block[1:], 1):
        marker = next((line.find(c) for c in TREE_CHARS if c in line), -1)
        if marker < 0:
            continue
        depth = marker // 4 + 1
        entry = line[marker + 4 :].split("#")[0].strip()
        for name in (n.strip() for n in entry.split(",")):
            if not name:
                continue
            del stack[depth:]
            paths.append((index, "".join(stack[:depth]) + name))
            if name.endswith("/"):
                stack.append(name)
    return paths


def tree_paths(block: list[str]) -> list[str]:
    return [path for _, path in tree_entries(block)]


def inline_entries(text: str) -> list[tuple[int, str]]:
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        for span in INLINE_RE.findall(line):
            token = span.split()[0] if span.split() else ""
            if token.startswith(ROOTS) and not any(ch in token for ch in "<>{}$"):
                found.append((number, token.rstrip(".,;:")))
    return found


def inline_paths(text: str) -> list[str]:
    return [path for _, path in inline_entries(text)]


def _exists(path: str) -> bool:
    if "*" in path:
        return any(REPO.glob(path))
    return (REPO / path).exists()


def _missing(doc: str, *, trees: bool, inline: bool) -> list[str]:
    text = (REPO / doc).read_text(encoding="utf-8")
    named: list[tuple[int, str]] = []
    if trees:
        for start, block in _fenced_blocks(text):
            named.extend((start + index, path) for index, path in tree_entries(block))
    if inline:
        named.extend(inline_entries(text))
    return [f"{doc}:{line}: {p}" for line, p in named if not _exists(p)]


def test_tree_parser_reconstructs_nested_paths() -> None:
    block = [
        "backend/app/",
        "├── main.py   # app",
        "├── services/",
        "│   ├── print_queue.py",
        "│   └── nested/",
        "│       └── deep.py",
        "└── models/",
    ]
    assert tree_paths(block) == [
        "backend/app/main.py",
        "backend/app/services/",
        "backend/app/services/print_queue.py",
        "backend/app/services/nested/",
        "backend/app/services/nested/deep.py",
        "backend/app/models/",
    ]
    assert tree_paths(["┌──────┐", "│ box  │", "└──────┘"]) == []


def test_indented_fence_is_read_and_failures_name_the_line() -> None:
    text = "intro\n\n- item\n\n  ```\n  backend/app/\n  ├── main.py\n  └── gone_nowhere.py\n  ```\n"
    blocks = _fenced_blocks(text)
    assert blocks == [(6, ["backend/app/", "├── main.py", "└── gone_nowhere.py"])]
    start, block = blocks[0]
    missing = [(start + i, p) for i, p in tree_entries(block) if not _exists(p)]
    assert missing == [(8, "backend/app/gone_nowhere.py")]


def test_architecture_names_a_real_tree() -> None:
    """The guard is not vacuous: architecture.md holds the backend and frontend trees."""
    text = (REPO / "docs/architecture.md").read_text(encoding="utf-8")
    named = [p for _, block in _fenced_blocks(text) for p in tree_paths(block)]
    assert len(named) >= 30
    assert "backend/app/services/layout_engine.py" in named
    assert "frontend/src/features/" in named


def test_architecture_paths_exist() -> None:
    assert _missing("docs/architecture.md", trees=True, inline=True) == []


def test_plugin_development_paths_exist() -> None:
    missing = _missing("docs/plugin-development.md", trees=True, inline=True)
    assert missing == []


def test_plugin_development_cites_code_paths() -> None:
    """The inline-path check is not vacuous for the plugin guide."""
    text = (REPO / "docs/plugin-development.md").read_text(encoding="utf-8")
    assert len(inline_paths(text)) >= 10
