#!/usr/bin/env python3
"""Print the files Vale lints, one per line.

Scope: README.md, CONTRIBUTING.md, docs/**/*.md and website/src/content/docs/**/*.{md,mdx},
without the history paths of the brand guard (plans, designs, research, old ADRs and the
single-container migration note), which are a dated record and are never rewritten.
Files come from ``git ls-files``, so untracked scratch files are not linted.

Usage: python3 scripts/vale_scope.py [--root .]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from brand_guard import is_excluded

WEBSITE = "website/src/content/docs/"


def in_scope(path: str) -> bool:
    if is_excluded(path):
        return False
    if path in ("README.md", "CONTRIBUTING.md"):
        return True
    if path.startswith("docs/"):
        return path.endswith(".md")
    return path.startswith(WEBSITE) and path.endswith((".md", ".mdx"))


def scope_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True
    ).stdout.decode("utf-8", "surrogateescape")
    return sorted(p for p in out.split("\0") if p and in_scope(p))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    print("\n".join(scope_files(Path(args.root))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
