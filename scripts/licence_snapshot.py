#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Snapshot of the declared licences of every package the image carries.

The image ships ``/opt/app/web/licenses/backend.json`` and ``frontend.json``: one entry per
package with its declared licence. ``licences/snapshot.json`` records ``package -> licence``
for both lists. A licence can move between two allowed licences (MIT to Apache-2.0) without
tripping the licence policy; this tool makes such a move visible and fails until the snapshot
is updated on purpose.

    licence_snapshot.py check  --backend B.json --frontend F.json [--snapshot S.json] [--strict]
    licence_snapshot.py update --backend B.json --frontend F.json [--snapshot S.json]
    licence_snapshot.py notes  --old OLD.json --new NEW.json

``check`` prints one line per difference (``name: OLD → NEW``; a new package is
``name: (new) → LICENCE``, a removed one ``name: LICENCE → (removed)``), appends the lines to
``$GITHUB_STEP_SUMMARY``. It exits 1 when a package present in both lists changed its licence;
a package that is only new or only removed is reported but does not fail, because the licence
policy gate of the image build already judges every package the image carries (a new package with
a disallowed licence stops that build) and a moved dependency set is not a defect of a pull
request. ``--strict`` also fails on new and removed packages; the weekly run uses it (the
release only renders ``notes``). ``update`` rewrites the snapshot sorted by name. ``notes`` renders the difference between two snapshots as a release-notes section.

Exit codes: 0 ok, 1 licences moved (or, with --strict, any difference) or snapshot missing, 2 unreadable input.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

DEFAULT_SNAPSHOT = Path(__file__).resolve().parent.parent / "licences" / "snapshot.json"
NEW = "(new)"
REMOVED = "(removed)"
# Every line `check` prints starts with this, so a package name is never at the start of a
# line. The runner trims leading whitespace and then looks for "::"; after this prefix the
# first character is "-", which no trimming removes.
LINE_PREFIX = "  - "


# Control characters (C0, DEL, C1) and the Unicode line and paragraph separators.
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")


class InputError(Exception):
    """A licence list or a snapshot could not be read."""


def _vet(name: str, licence: str, source: object) -> None:
    """Refuse an entry that could steer the workflow runner or the markdown output.

    Names and licences are third-party metadata and are printed to stdout, where the runner
    parses lines that start with ``::`` as workflow commands (``::error::``,
    ``::stop-commands::``). A control character can start such a line, and a name can open
    one, also after leading whitespace, which the runner trims. The entry is rejected, not
    cleaned: the run fails with exit 2 and names the entry, so a hostile package is seen
    instead of silently rewritten.
    """
    for label, value in (("name", name), ("licence", licence)):
        if _CONTROL.search(value):
            raise InputError(f"{source}: the {label} of {name!r} holds a control character")
    if name.startswith("::"):
        raise InputError(f"{source}: the name {name!r} starts with '::'")
    if name != name.lstrip():
        # The runner trims leading whitespace before it looks for "::", so " ::error::x" is a
        # command. str.lstrip() also covers Unicode whitespace.
        raise InputError(f"{source}: the name {name!r} starts with whitespace")


def code_span(value: str) -> str:
    """``value`` as a markdown code span that no backtick inside it can break.

    The fence is one backtick longer than the longest run in the value. A value that starts
    or ends with a backtick is padded with a space, as CommonMark requires.
    """
    longest = max((len(run) for run in re.findall(r"`+", value)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if value.startswith("`") or value.endswith("`") else ""
    return f"{fence}{pad}{value}{pad}{fence}"


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
            _vet(name, licence, path)
            seen.setdefault(name, set()).add(licence)
    return {name: " / ".join(sorted(found)) for name, found in seen.items()}


def read_snapshot(path: Path) -> dict[str, str]:
    data = _load_json(path)
    packages = data.get("packages") if isinstance(data, dict) else None
    if not isinstance(packages, dict):
        raise InputError(f"{path}: expected an object with a 'packages' map")
    result = {str(k): str(v) for k, v in packages.items()}
    for name, licence in result.items():
        _vet(name, licence, path)
    return result


def changes(old: dict[str, str], new: dict[str, str]) -> list[tuple[str, str, str]]:
    """``(name, before, after)`` per difference, sorted by package name."""
    found = []
    for name in sorted(old.keys() | new.keys()):
        before, after = old.get(name, NEW), new.get(name, REMOVED)
        if name in old and name in new and before == after:
            continue
        found.append((name, before, after))
    return found


def diff(old: dict[str, str], new: dict[str, str]) -> list[str]:
    """One plain line per difference, sorted by package name."""
    return [f"{name}: {before} → {after}" for name, before, after in changes(old, new)]


def markdown_lines(old: dict[str, str], new: dict[str, str]) -> list[str]:
    """Bullet per difference with the name and both licences as code spans.

    A scoped npm name such as ``@babel/types`` would otherwise render as an @mention, and a
    name with ``[x](url)`` or ``*`` would change the formatting.
    """
    return [
        f"- {code_span(name)}: {code_span(before)} → {code_span(after)}"
        for name, before, after in changes(old, new)
    ]


def write_snapshot(path: Path, packages: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"packages": dict(sorted(packages.items()))}
    path.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def is_licence_move(change: tuple[str, str, str]) -> bool:
    """True for a package present in both lists whose licence differs."""
    _, before, after = change
    return before not in (NEW, REMOVED) and after not in (NEW, REMOVED)


def _append_summary(bullets: list[str]) -> None:
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target or not bullets:
        return
    with open(target, "a", encoding="utf-8") as handle:
        handle.write("## Licence changes\n\n")
        handle.write("\n".join(bullets) + "\n")
        handle.write("\nRun `scripts/licence_snapshot.py update` to accept them.\n")


def _current(args: argparse.Namespace) -> dict[str, str]:
    return read_lists(args.backend, args.frontend)


def cmd_check(args: argparse.Namespace) -> int:
    if not args.snapshot.is_file():
        print(f"licence snapshot {args.snapshot} is missing; run 'update' first", file=sys.stderr)
        return 1
    old, new = read_snapshot(args.snapshot), _current(args)
    found = changes(old, new)
    for name, before, after in found:
        print(f"{LINE_PREFIX}{name}: {before} → {after}")
    _append_summary(markdown_lines(old, new))
    failing = found if args.strict else [c for c in found if is_licence_move(c)]
    return 1 if failing else 0


def cmd_update(args: argparse.Namespace) -> int:
    write_snapshot(args.snapshot, _current(args))
    return 0


def cmd_notes(args: argparse.Namespace) -> int:
    if not args.old.is_file():
        return 0  # a first release has no previous snapshot to compare with
    bullets = markdown_lines(read_snapshot(args.old), read_snapshot(args.new))
    if bullets:
        print("## Licence changes\n")
        print("\n".join(bullets))
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
        if name == "check":
            p.add_argument(
                "--strict",
                action="store_true",
                help="also fail on a package that is only new or only removed",
            )
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
