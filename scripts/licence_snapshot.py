#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Snapshot of the declared licences of every package the image carries.

The image ships ``/opt/app/web/licenses/backend.json`` and ``frontend.json``: one entry per
package with its declared licence. ``licences/snapshot.json`` records ``package -> licence``
for both lists. A licence can move between two allowed licences (MIT to Apache-2.0) without
tripping the licence policy; this tool makes such a move visible and fails until the snapshot
is updated on purpose.

    licence_snapshot.py check  --backend B.json --frontend F.json [--snapshot S.json]
    licence_snapshot.py update --backend B.json --frontend F.json [--snapshot S.json]
    licence_snapshot.py notes  --old OLD.json --new NEW.json

``check`` prints one line per difference (``name: OLD → NEW``; a new package is
``name: (new) → LICENCE``, a removed one ``name: LICENCE → (removed)``), appends the lines to
``$GITHUB_STEP_SUMMARY`` and exits 1 on any difference. ``update`` rewrites the snapshot sorted
by name. ``notes`` renders the difference between two snapshots as a release-notes section.

Exit codes: 0 ok, 1 licences differ or snapshot missing, 2 unreadable input.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT_SNAPSHOT = Path(__file__).resolve().parent.parent / "licences" / "snapshot.json"
NEW = "(new)"
REMOVED = "(removed)"


class InputError(Exception):
    """A licence list or a snapshot could not be read."""


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InputError(f"cannot read {path}: {exc}") from exc


def read_lists(*paths: Path) -> dict[str, str]:
    """Merge licence lists into ``name -> licence``.

    A name that appears with several versions or in both lists and carries different licences
    is recorded as the sorted, distinct licences joined with `` / ``.
    """
    seen: dict[str, set[str]] = {}
    for path in paths:
        data = _load_json(path)
        if not isinstance(data, list):
            raise InputError(f"{path}: expected a list of packages")
        for entry in data:
            name = entry.get("name") if isinstance(entry, dict) else None
            licence = entry.get("license") if isinstance(entry, dict) else None
            if not isinstance(name, str) or not name:
                raise InputError(f"{path}: an entry has no name")
            if not isinstance(licence, str) or not licence:
                raise InputError(f"{path}: package {name} has no declared licence")
            seen.setdefault(name, set()).add(licence)
    return {name: " / ".join(sorted(found)) for name, found in seen.items()}


def read_snapshot(path: Path) -> dict[str, str]:
    data = _load_json(path)
    packages = data.get("packages") if isinstance(data, dict) else None
    if not isinstance(packages, dict):
        raise InputError(f"{path}: expected an object with a 'packages' map")
    return {str(k): str(v) for k, v in packages.items()}


def diff(old: dict[str, str], new: dict[str, str]) -> list[str]:
    """One line per difference, sorted by package name."""
    lines = []
    for name in sorted(old.keys() | new.keys()):
        before, after = old.get(name, NEW), new.get(name, REMOVED)
        if name in old and name in new:
            if before == after:
                continue
        lines.append(f"{name}: {before} → {after}")
    return lines


def write_snapshot(path: Path, packages: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"packages": dict(sorted(packages.items()))}
    path.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _append_summary(lines: list[str]) -> None:
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target or not lines:
        return
    with open(target, "a", encoding="utf-8") as handle:
        handle.write("## Licence changes\n\n")
        handle.write("\n".join(f"- {line}" for line in lines) + "\n")
        handle.write("\nRun `scripts/licence_snapshot.py update` to accept them.\n")


def _current(args: argparse.Namespace) -> dict[str, str]:
    return read_lists(args.backend, args.frontend)


def cmd_check(args: argparse.Namespace) -> int:
    if not args.snapshot.is_file():
        print(f"licence snapshot {args.snapshot} is missing; run 'update' first", file=sys.stderr)
        return 1
    lines = diff(read_snapshot(args.snapshot), _current(args))
    for line in lines:
        print(line)
    _append_summary(lines)
    return 1 if lines else 0


def cmd_update(args: argparse.Namespace) -> int:
    write_snapshot(args.snapshot, _current(args))
    return 0


def cmd_notes(args: argparse.Namespace) -> int:
    if not args.old.is_file():
        return 0  # a first release has no previous snapshot to compare with
    lines = diff(read_snapshot(args.old), read_snapshot(args.new))
    if lines:
        print("## Licence changes\n")
        print("\n".join(f"- {line}" for line in lines))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name, func in (("check", cmd_check), ("update", cmd_update)):
        p = sub.add_parser(name)
        p.add_argument("--backend", type=Path, required=True)
        p.add_argument("--frontend", type=Path, required=True)
        p.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
        p.set_defaults(func=func)
    p = sub.add_parser("notes")
    p.add_argument("--old", type=Path, required=True)
    p.add_argument("--new", type=Path, required=True)
    p.set_defaults(func=cmd_notes)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
