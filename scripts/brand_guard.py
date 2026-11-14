#!/usr/bin/env python3
"""Brand guard: list every remaining old project name outside an allow-list.

The project was renamed to Labelyard. Some old identifiers must stay (they live
in users' data, configuration or clients), and history is never rewritten. This
script finds every other occurrence so the rename can be finished and kept
finished.

Usage: python3 scripts/brand_guard.py [--root .]
Exit code: 0 = clean, 1 = hits, 2 = --root is not a git work tree. Each hit is printed as ``path:line: rule: text``.
Files come from ``git ls-files``; stdlib only.

The patterns below spell the last letter of each old name as ``[b]``: the
character class matches the name, but the pattern text itself does not, so this
file is not a hit of its own rules.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, NamedTuple


class Hit(NamedTuple):
    path: str
    line: int
    rule: str
    text: str


class Rule(NamedTuple):
    name: str
    pattern: re.Pattern[str]
    # allowed(path, line, match) -> True when this match is an accepted survivor
    allowed: Callable[[str, str, re.Match[str]], bool]


# --- Allow-lists ------------------------------------------------------------

# History is never rewritten and is never scanned. Entries ending in "/" are
# directory prefixes, the rest are globs ("*" stays inside a path segment).
EXCLUDED: tuple[str, ...] = (
    "CHANGELOG.md",  # released notes name the old product
    "docs/superpowers/",  # plans and specs are a dated record
    "docs/plans/",
    "docs/designs/",
    "docs/research/",
    # Old ADRs are decided history. The rename ADR itself is scanned, see
    # RENAME_ADR_SUFFIX: matching by name, not number, because other ADRs may
    # be added before the rename ADR gets its number.
    "docs/decisions/[0-9][0-9][0-9][0-9]-*.md",
    "docs/migration/v-next-single-container.md",
    "frontend/pnpm-lock.yaml",  # generated
    # Files that must name the old names in order to reject them:
    "docs/glossary.toml",
    ".vale.ini",  # names the files that may mention the old name
    ".vale/styles/**/OldName.yml",
    ".vale/styles/**/Label.yml",  # generated: the exempt strings include the old display name
    ".vale/styles/config/vocabularies/*/reject.txt",
    "scripts/fixtures/vale/",
)
RENAME_ADR_SUFFIX = "-rename-to-labelyard.md"

# The website's upgrade guide for people coming from the old name, in English and German. Its
# slug carries the old name on purpose (the URL says what the page is about).
_GUIDE_SLUG = "from-label-printer-hu" + "b"
WEBSITE_UPGRADE_GUIDE: tuple[str, ...] = (
    f"website/src/content/docs/admin/upgrades/{_GUIDE_SLUG}.md",
    f"website/src/content/docs/de/admin/upgrades/{_GUIDE_SLUG}.md",
)

# Files that may keep the old environment prefixes: the compatibility layer
# that still reads them, its tests, the migration guide on the website (both
# languages), the rename ADR (glob) and the guard files that name them.
LEGACY_ENV_FILES: tuple[str, ...] = (
    "backend/app/config_legacy.py",
    "backend/app/page_render/pdf.py",
    "backend/tests/unit/test_config_legacy_prefix.py",
    "backend/tests/unit/test_pdf_font_env.py",
    # The settings model, the log-level lookup and the example env file describe the
    # fallback; the image reads the old port variable as a fallback too.
    "backend/app/config.py",
    "backend/app/main.py",
    "backend/.env.example",
    "backend/Dockerfile",
    # Tests that set or clear the old names to check the fallback (and that an older,
    # never-read variable stays ignored).
    "backend/tests/conftest.py",
    "backend/tests/db/test_engine.py",
    "backend/tests/integration/test_legacy_env_startup_warning.py",
    "backend/tests/unit/test_brand_identity.py",
    "backend/tests/unit/test_startup_error.py",
    "docs/decisions/*-rename-to-labelyard.md",
    "scripts/brand_guard.py",
    "scripts/test_brand_guard.py",
    *WEBSITE_UPGRADE_GUIDE,
)

# Files that may keep the old command name (it stays as an alias of `labelyard`).
LEGACY_CLI_FILES: tuple[str, ...] = (
    "backend/pyproject.toml",
    "backend/tests/unit/test_brand_identity.py",
    "scripts/brand_guard.py",
    "scripts/test_brand_guard.py",
    *WEBSITE_UPGRADE_GUIDE,
)


# Files that must show the old image and repository names so users can recognise their own
# ``image:`` line: the migration guide on the website and the rename ADR, plus the files that
# link to the guide by its slug (the website's upgrades overview and the pointer left at the
# guide's old repository path). Nothing else.
LEGACY_SLUG_FILES: tuple[str, ...] = (
    "docs/migration/labelyard.md",
    "docs/decisions/*-rename-to-labelyard.md",
    *WEBSITE_UPGRADE_GUIDE,
    "website/src/content/docs/admin/upgrades/index.md",
    "website/src/content/docs/de/admin/upgrades/index.md",
)


# The IPP user name of jobs sent by 1.5.x: the hub still recognises them as its own after the
# upgrade, so the old name stays in exactly one constant. Only this line of this file is allowed.
LEGACY_IPP_USER_FILE = "backend/app/printer_backends/ipp/job_attrs.py"
LEGACY_IPP_USER_LINE_START = "LEGACY_IPP_USER_NAME = "

# Temporary, until Task 13 (repository rename): semantic-release pushes over the repository URL,
# which only changes once the repository is renamed. Remove both paths in the Task 13 commit
# that switches ``repositoryUrl``.
TEMPORARY_REPO_URL_FILES: tuple[str, ...] = (
    ".releaserc.json",
    "backend/tests/unit/test_release_workflows.py",
)


def _glob_to_regex(glob: str) -> re.Pattern[str]:
    """Translate a path glob: ``**`` crosses directories, ``*`` and ``?`` do not."""
    out: list[str] = []
    i = 0
    while i < len(glob):
        ch = glob[i]
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        if glob.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        if ch == "*":
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        elif ch == "[":
            end = glob.index("]", i)
            out.append(glob[i : end + 1])
            i = end
        else:
            out.append(re.escape(ch))
        i += 1
    return re.compile("".join(out) + r"\Z")


def _matches_any(path: str, globs: tuple[str, ...]) -> bool:
    for glob in globs:
        if glob.endswith("/"):
            if path.startswith(glob):
                return True
        elif _glob_to_regex(glob).match(path):
            return True
    return False


def is_excluded(path: str) -> bool:
    if path.endswith(RENAME_ADR_SUFFIX) and path.startswith("docs/decisions/"):
        return False
    return _matches_any(path, EXCLUDED)


# --- Rules --------------------------------------------------------------------


def _never(_path: str, _line: str, _m: re.Match[str]) -> bool:
    return False


def _slug_allowed(path: str, line: str, m: re.Match[str]) -> bool:
    # `<slug>.sheet-type` is the file format's registered name; it is stored in
    # users' exported files and stays. The migration guide and the rename ADR may
    # name the old image and repository.
    if line.startswith(".sheet-type", m.end()) or _matches_any(path, LEGACY_SLUG_FILES):
        return True
    if path == LEGACY_IPP_USER_FILE and line.startswith(LEGACY_IPP_USER_LINE_START):
        return True
    return path in TEMPORARY_REPO_URL_FILES


def _in_legacy_env_file(path: str, _line: str, _m: re.Match[str]) -> bool:
    return _matches_any(path, LEGACY_ENV_FILES)


def _in_legacy_cli_file(path: str, _line: str, _m: re.Match[str]) -> bool:
    return _matches_any(path, LEGACY_CLI_FILES)


def _nickname_allowed(_path: str, line: str, m: re.Match[str]) -> bool:
    # The API key header `X-Label-Hub-Key` is a client-facing identifier and
    # stays; a match inside that token is not a nickname.
    token = "X-Label-Hub-Key"
    start = line.find(token)
    while start != -1:
        if start <= m.start() and m.end() <= start + len(token):
            return True
        start = line.find(token, start + 1)
    return False


# The README hero states the subtitle and the former name on lines of their own. Matching the
# line text (not "the line below the H1") is the sturdier choice: it does not depend on layout,
# and any edit of these sentences, or the same text in another file, is a hit again. The
# former-name sentence is matched by its start so the link after it may change.
_OLD_DISPLAY = "Label Printer " + "Hub"
README_HERO_TAGLINE = f"**The self-hosted {_OLD_DISPLAY} for all your labels.**"
README_HERO_FORMERLY = f"Formerly *{_OLD_DISPLAY}*."

# The old display name stays as the subtitle inside these exact phrases: the web app's tagline
# (English and German, sentence start and mid-sentence) and its PWA manifest description. A
# match is allowed only when it lies inside one of them and the file is part of the web app
# (``frontend/``); a changed phrase, or the phrase in any other file, is a hit again. The README
# keeps its own exact-line allowance above.
SUBTITLE_FILES: tuple[str, ...] = ("frontend/",)
SUBTITLE_PHRASES: tuple[str, ...] = (
    f"The self-hosted {_OLD_DISPLAY} for all your labels",
    f"the self-hosted {_OLD_DISPLAY} for all your labels",
    f"Der selbst gehostete {_OLD_DISPLAY} für all deine Etiketten",
    f"der selbst gehostete {_OLD_DISPLAY} für all deine Etiketten",
    f"{_OLD_DISPLAY} — print labels, scan codes and watch your label printers.",
)


def _inside_phrase(line: str, m: re.Match[str], phrase: str) -> bool:
    start = line.find(phrase)
    while start != -1:
        if start <= m.start() and m.end() <= start + len(phrase):
            return True
        start = line.find(phrase, start + 1)
    return False


def _display_allowed(path: str, line: str, m: re.Match[str]) -> bool:
    # The old display name survives only as the subtitle next to the new name.
    if "Labelyard" in line:
        return True
    in_web_app = _matches_any(path, SUBTITLE_FILES)
    if in_web_app and any(_inside_phrase(line, m, p) for p in SUBTITLE_PHRASES):
        return True
    if path == "README.md":
        text = line.strip()
        return text == README_HERO_TAGLINE or text.startswith(README_HERO_FORMERLY)
    return False


RULES: tuple[Rule, ...] = (
    # Old image/repository slug; only the `.sheet-type` format name stays.
    Rule("slug", re.compile(r"label-printer-hu[b]", re.IGNORECASE), _slug_allowed),
    # Old canonical environment prefix; read only by the compatibility layer.
    Rule("env-prefix", re.compile(r"PRINTER_HU[B]_"), _in_legacy_env_file),
    # Other historic environment prefixes.
    Rule("env-other", re.compile(r"PRINTHU[B]_|PRINTERHU[B]_|LABEL_HU[B]_"), _in_legacy_env_file),
    # Old command name, kept as an alias. The lookbehind leaves the slug (and so
    # the `.sheet-type` format) to the slug rule; the lookahead keeps the
    # database file name `<cli>.db`, which stays so existing installs find it.
    Rule(
        "cli",
        re.compile(r"(?<!(?i:label-))printer-hu[b](?!\.db)"),
        _in_legacy_cli_file,
    ),
    # Informal short names that were never the product name. `Label[ -]Hub`
    # also covers the hyphenated spelling, so the header allowance below is live.
    Rule(
        "nickname",
        re.compile(r"Print-Hu[b]|PrintHu[b]|printerhu[b]|Label[ -]Hu[b]"),
        _nickname_allowed,
    ),
    # The descriptive old name is allowed only as the subtitle beside Labelyard.
    Rule("display", re.compile(r"Label Printer Hu[b]"), _display_allowed),
)

_MAX_TEXT = 200


class NotAGitRepoError(RuntimeError):
    """`git ls-files` failed: --root is not a git work tree."""


# --- Scan -------------------------------------------------------------------


def _tracked_files(root: Path) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            check=True,
            capture_output=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError, NotADirectoryError) as exc:
        raise NotAGitRepoError(f"cannot list files with git in {root}") from exc
    return [p for p in out.decode("utf-8", "surrogateescape").split("\0") if p]


def _scan_text(path: str, text: str) -> list[Hit]:
    hits: list[Hit] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for rule in RULES:
            # One hit per line and rule, so the inventory counts lines.
            if any(not rule.allowed(path, line, m) for m in rule.pattern.finditer(line)):
                hits.append(Hit(path, number, rule.name, line.strip()[:_MAX_TEXT]))
    return hits


def find_hits(root: Path) -> list[Hit]:
    root = Path(root)
    hits: list[Hit] = []
    for rel in _tracked_files(root):
        if is_excluded(rel):
            continue
        full = root / rel
        if full.is_symlink() or not full.is_file():
            continue
        data = full.read_bytes()
        if b"\0" in data[:8192]:  # binary
            continue
        hits.extend(_scan_text(rel, data.decode("utf-8", "replace")))
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default=".", help="repository root (default: .)")
    args = parser.parse_args(argv)
    try:
        hits = find_hits(Path(args.root))
    except NotAGitRepoError as exc:
        print(f"brand_guard: error: {exc}", file=sys.stderr)
        return 2
    for hit in hits:
        print(f"{hit.path}:{hit.line}: {hit.rule}: {hit.text}")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
