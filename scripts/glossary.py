#!/usr/bin/env python3
"""One terminology source for the docs, the prose linter and the UI catalogues.

``docs/glossary.toml`` lists every concept once, in English and German. This script

* ``write``: generates the two glossary pages of the website, the two Vale substitution rules
  and the four Vale vocabulary files from it (``--check`` only reports files that are stale);
* ``check-catalog <file.po>``: fails when a ``msgstr`` of a message catalogue contains a rejected
  term of the glossary as a whole word.

Usage: python3 scripts/glossary.py [--root .] write [--check]
       python3 scripts/glossary.py check-catalog frontend/src/i18n/locales/de/messages.po

Exit code: 0 = clean, 1 = stale files or rejected terms, 2 = the glossary itself is invalid.
Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NamedTuple

GENERATED = "Generated from docs/glossary.toml — edit that file"

Target = Literal[
    "glossary-en",
    "glossary-de",
    "vale-terms-en",
    "vale-terms-de",
    "vale-exempt-de",
    "accept-en",
    "reject-en",
    "accept-de",
    "reject-de",
]

# Target -> generated file, relative to the repository root.
OUTPUTS: dict[str, str] = {
    "glossary-en": "website/src/content/docs/using/glossary.md",
    "glossary-de": "website/src/content/docs/de/using/glossary.md",
    "vale-terms-en": ".vale/styles/Labelyard/Terms.yml",
    "vale-terms-de": ".vale/styles/Labelyard-de/Terms.yml",
    "vale-exempt-de": ".vale/styles/Labelyard-de/Label.yml",
    "accept-en": ".vale/styles/config/vocabularies/Labelyard-en/accept.txt",
    "reject-en": ".vale/styles/config/vocabularies/Labelyard-en/reject.txt",
    "accept-de": ".vale/styles/config/vocabularies/Labelyard-de/accept.txt",
    "reject-de": ".vale/styles/config/vocabularies/Labelyard-de/reject.txt",
}

_REQUIRED = ("id", "en", "de", "definition_en", "definition_de")
_LISTS = ("reject_en", "reject_de", "old_names", "exempt")
_KNOWN = {*_REQUIRED, *_LISTS, "product"}


class GlossaryError(Exception):
    """The glossary file is invalid."""


@dataclass(frozen=True)
class Term:
    id: str
    en: str
    de: str
    definition_en: str
    definition_de: str
    # Rejected spellings; they become errors (Vale.Avoid) and are checked in the UI catalogues.
    reject_en: tuple[str, ...] = ()
    reject_de: tuple[str, ...] = ()
    # Rejected only when the line does not also name the product: written by hand into the
    # OldName rules, never into reject.txt (Vale has no per-line exception there).
    old_names: tuple[str, ...] = ()
    # Strings that contain a rejected word legitimately (the product subtitle, a header name).
    exempt: tuple[str, ...] = ()
    # The product name entry: its old names are the brand guard's business, so it stays out of
    # the substitution rule, the glossary pages and the catalogue check.
    product: bool = False

    def canonical(self, lang: str) -> str:
        return self.en if lang == "en" else self.de

    def rejected(self, lang: str) -> tuple[str, ...]:
        return self.reject_en if lang == "en" else self.reject_de


def load_glossary(path: Path) -> list[Term]:
    """Read and validate the glossary. Raises GlossaryError naming the entry and the field."""
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise GlossaryError(f"{path}: {exc}") from exc
    rows = data.get("term")
    if not isinstance(rows, list) or not rows:
        raise GlossaryError(f"{path}: no [[term]] entries")
    terms: list[Term] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        label = row.get("id") or f"entry #{index}"
        unknown = sorted(set(row) - _KNOWN)
        if unknown:
            raise GlossaryError(f"{label}: unknown key(s) {', '.join(unknown)}")
        for key in _REQUIRED:
            value = row.get(key)
            if not isinstance(value, str) or not value.strip():
                raise GlossaryError(f"{label}: missing or empty field '{key}'")
        if row["id"] in seen:
            raise GlossaryError(f"{label}: duplicate id")
        seen.add(row["id"])
        lists: dict[str, tuple[str, ...]] = {}
        for key in _LISTS:
            value = row.get(key, [])
            if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
                raise GlossaryError(f"{label}: '{key}' must be a list of non-empty strings")
            lists[key] = tuple(value)
        terms.append(
            Term(
                id=row["id"],
                en=row["en"],
                de=row["de"],
                definition_en=row["definition_en"],
                definition_de=row["definition_de"],
                product=bool(row.get("product", False)),
                **lists,
            )
        )
    return terms


# --- Rendering ----------------------------------------------------------------


def _escape(text: str) -> str:
    return re.sub(r"([.^$*+?{}\[\]\\|()])", r"\\\1", text)


def _vocab_lines(terms: list[Term], lang: str, kind: str) -> list[str]:
    lines: list[str] = []
    for term in terms:
        if kind == "accept":
            # Vale treats each entry as a regular expression and lets an accepted word cancel a
            # rejected one that contains it (a rejected "printer-x" would be hidden by "printer");
            # anchoring the entry keeps it to the whole word.
            values = ["^" + _escape(term.canonical(lang)) + "$"]
        elif term.exempt:
            # Enforced by the line-aware rule (vale-exempt): reject.txt cannot skip a line.
            values = []
        else:
            values = list(term.rejected(lang))
        for value in values:
            if value not in lines:
                lines.append(value)
    return lines


def _render_vale_exempt(terms: list[Term], lang: str) -> str:
    """A script rule for rejected terms that may appear inside an exempt string.

    Vale.Avoid (reject.txt) cannot skip a line, so a rejected word such as "Label" would hit
    inside the product subtitle. This rule works like OldName: line by line over the raw file,
    skipping fenced and inline code and every line that contains an exempt string.
    """
    tokens: list[str] = []
    exempt: list[str] = []
    for term in terms:
        if term.exempt and term.rejected(lang):
            tokens += [t for t in term.rejected(lang) if t not in tokens]
            exempt += [e for e in term.exempt if e not in exempt]
    quote = lambda items: ", ".join(f'"{i}"' for i in items)  # noqa: E731
    pattern = r"\\b(?:" + "|".join(_escape(t) for t in tokens) + r")\\b"
    return f"""# {GENERATED}
# Rejected terms that Vale.Avoid cannot enforce because they occur inside an exempt string (the
# product subtitle, a header name). Like OldName: a script over the raw file, line by line, skipping
# fenced and inline code and every line that contains an exempt string.
extends: script
message: "„%s“ ist ein abgelehnter Begriff. Nimm den Glossarbegriff."
level: error
scope: raw
script: |
  text := import("text")
  exempt := [{quote(exempt)}]
  matches := []
  in_fence := false
  offset := 0
  for line in text.split(scope, "\\n") {{
    trimmed := text.trim_space(line)
    skip := false
    for e in exempt {{
      if text.contains(line, e) {{ skip = true }}
    }}
    if text.has_prefix(trimmed, "```") || text.has_prefix(trimmed, "~~~") {{
      in_fence = !in_fence
    }} else if !in_fence && !skip {{
      found := text.re_find("{pattern}", line)
      if found != undefined {{
        for group in found {{
          for m in group {{
            ticks := len(text.split(line[:m.begin], "`")) - 1
            if ticks % 2 == 0 {{
              matches = append(matches, {{begin: offset + m.begin, end: offset + m.end}})
            }}
          }}
        }}
      }}
    }}
    offset += len(line) + 1
  }}
"""


def _yaml_key(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _render_vale_terms(terms: list[Term], lang: str) -> str:
    message = "Use '%s' instead of '%s'." if lang == "en" else "Schreibe „%s“ statt „%s“."
    swaps: list[str] = []
    for term in terms:
        if term.product:
            continue
        for rejected in term.rejected(lang):
            swaps.append(f"  {_yaml_key(rejected)}: {_yaml_key(term.canonical(lang))}")
    if not swaps:
        # A substitution rule without entries is invalid; this one never matches.
        swaps.append(f"  {_yaml_key(r'\b\B')}: {_yaml_key('-')}")
    return "\n".join(
        [
            f"# {GENERATED}",
            "extends: substitution",
            f'message: "{message}"',
            "level: warning",
            "ignorecase: false",
            "swap:",
            *swaps,
            "",
        ]
    )


_PAGE_TEXT = {
    "en": {
        "title": "Glossary",
        "description": (
            "The terms Labelyard uses for its concepts, in English and German, "
            "with the spellings to avoid."
        ),
        "intro": (
            "These are the words Labelyard uses, in the interface, in the documentation and in "
            "the API reference. Each concept has one English term and one German term; use them "
            "in every page you write."
        ),
        "term": "Term",
        "meaning": "Meaning",
        "avoid": "Avoid",
        "other": "German",
    },
    "de": {
        "title": "Glossar",
        "description": (
            "Die Begriffe, die Labelyard für seine Konzepte verwendet, auf Englisch und "
            "Deutsch, mit den Schreibweisen, die du vermeidest."
        ),
        "intro": (
            "Das sind die Wörter, die Labelyard in der Oberfläche, in der Dokumentation und in "
            "der API-Referenz benutzt. Jedes Konzept hat einen englischen und einen deutschen "
            "Begriff; verwende sie auf jeder Seite, die du schreibst."
        ),
        "term": "Begriff",
        "meaning": "Bedeutung",
        "avoid": "Vermeide",
        "other": "Englisch",
    },
}


def _render_glossary(terms: list[Term], lang: str) -> str:
    text = _PAGE_TEXT[lang]
    other = "en" if lang == "de" else "de"
    out = [
        "---",
        f"title: {text['title']}",
        f"description: {text['description']}",
        "---",
        "",
        f"<!-- {GENERATED} -->",
        "",
        text["intro"],
        "",
        f"| {text['term']} | {text['other']} | {text['meaning']} | {text['avoid']} |",
        "|---|---|---|---|",
    ]
    for term in (t for t in terms if not t.product):
        definition = term.definition_en if lang == "en" else term.definition_de
        avoid = ", ".join(f"`{r}`" for r in term.rejected(lang)) or "-"
        # The anchor sits in the first cell, so the same id links to the same row in both
        # languages. The leading text keeps the line a table row.
        out.append(
            f'| <a id="{term.id}"></a>**{term.canonical(lang)}** | {term.canonical(other)} | '
            f"{definition} | {avoid} |"
        )
    out.append("")
    return "\n".join(out)


def render(terms: list[Term], target: Target) -> str:
    """Return the text of one generated file."""
    if target not in OUTPUTS:
        raise ValueError(f"unknown target {target!r}")
    kind, _, lang = target.rpartition("-")
    if kind == "glossary":
        return _render_glossary(terms, lang)
    if kind == "vale-exempt":
        return _render_vale_exempt(terms, lang)
    if kind == "vale-terms":
        return _render_vale_terms(terms, lang)
    header = f"# {GENERATED}\n"
    lines = _vocab_lines(terms, lang, kind)
    return header + "".join(f"{line}\n" for line in lines)


# --- Catalogue check ----------------------------------------------------------


class Hit(NamedTuple):
    term_id: str
    rejected: str
    canonical: str
    msgid: str
    msgstr: str


def catalog_language(path: Path) -> str:
    """``.../locales/<lang>/messages.po`` -> ``<lang>``."""
    lang = Path(path).parent.name
    if lang not in ("en", "de"):
        raise ValueError(
            f"cannot tell the language of {path}: expected .../locales/en|de/messages.po"
        )
    return lang


def read_catalog(path: Path) -> list[tuple[str, str]]:
    """Return (msgid, msgstr) of every live, non-header entry of a .po file."""
    entries: list[tuple[str, str]] = []
    msgid: str | None = None
    msgstr: str | None = None
    target: str | None = None

    def flush() -> None:
        nonlocal msgid, msgstr, target
        if msgid:
            entries.append((msgid, msgstr or ""))
        msgid = msgstr = target = None

    def unquote(line: str) -> str:
        return str(json.loads(line.strip()))

    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("#~"):
            continue
        if line.startswith("msgid "):
            flush()
            msgid, target = unquote(line[6:]), "id"
        elif line.startswith("msgstr "):
            msgstr, target = unquote(line[7:]), "str"
        elif line.startswith('"'):
            if target == "id" and msgid is not None:
                msgid += unquote(line)
            elif target == "str" and msgstr is not None:
                msgstr += unquote(line)
        elif not line:
            flush()
    flush()
    return entries


# An ICU argument name is not prose: ``{label}`` and ``{Labels, plural, ...}`` keep their braces
# and the keyword text, only the name goes.
_ICU_NAME = re.compile(r"\{\s*\w+\s*(?=[,}])")


def _whole_word(word: str) -> re.Pattern[str]:
    return re.compile(r"(?<![\w-])" + re.escape(word) + r"(?![\w-])")


def check_catalog(terms: list[Term], path: Path, lang: str) -> list[Hit]:
    """Every msgstr that contains a rejected term of the glossary as a whole word."""
    exempt = sorted({e for t in terms for e in t.exempt}, key=len, reverse=True)
    hits: list[Hit] = []
    for msgid, msgstr in read_catalog(path):
        text = _ICU_NAME.sub("{", msgstr)
        for phrase in exempt:
            text = text.replace(phrase, " ")
        for term in terms:
            if term.product:
                continue
            for rejected in term.rejected(lang):
                if _whole_word(rejected).search(text):
                    hits.append(Hit(term.id, rejected, term.canonical(lang), msgid, msgstr))
    return hits


# --- Command line -------------------------------------------------------------


def _write(terms: list[Term], root: Path, check: bool) -> int:
    stale: list[str] = []
    for target, rel in OUTPUTS.items():
        wanted = render(terms, target)  # type: ignore[arg-type]
        path = root / rel
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if current == wanted:
            continue
        if check:
            stale.append(rel)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(wanted, encoding="utf-8")
            print(f"wrote {rel}")
    if stale:
        for rel in stale:
            print(f"stale: {rel}", file=sys.stderr)
        print("run: python3 scripts/glossary.py write", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", default=".", help="repository root (default: .)")
    sub = parser.add_subparsers(dest="command", required=True)
    write = sub.add_parser("write", help="regenerate the generated files")
    write.add_argument("--check", action="store_true", help="only report stale files")
    check = sub.add_parser("check-catalog", help="reject glossary violations in .po files")
    check.add_argument("catalogs", nargs="+", type=Path)
    args = parser.parse_args(argv)

    root = Path(args.root)
    try:
        terms = load_glossary(root / "docs" / "glossary.toml")
    except GlossaryError as exc:
        print(f"glossary: {exc}", file=sys.stderr)
        return 2
    if args.command == "write":
        return _write(terms, root, args.check)

    failed = False
    for catalog in args.catalogs:
        try:
            lang = catalog_language(catalog)
        except ValueError as exc:
            print(f"glossary: {exc}", file=sys.stderr)
            return 2
        for hit in check_catalog(terms, catalog, lang):
            failed = True
            print(
                f"{catalog}: '{hit.rejected}' in \"{hit.msgstr}\" "
                f"(msgid \"{hit.msgid}\"): glossary term '{hit.term_id}' is '{hit.canonical}'"
            )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
