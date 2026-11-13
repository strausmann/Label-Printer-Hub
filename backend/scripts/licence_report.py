"""Check the licences of an installed Python environment against ``licence-policy.yml``.

The policy file is the one source for every licence gate of the project. It is written as
JSON (valid YAML), so ``actions/dependency-review-action`` reads it as YAML and this script
reads it with :mod:`json`. The script has no dependency on ``app`` and runs from a throw-away
tool venv in the Docker ``builder`` stage and in CI.

pip-licenses fields (``--from=all --format=json``, pip-licenses 5.5.5), one record per package:

``Name``, ``Version``
    Distribution name and version.
``License-Expression``
    The PEP 639 SPDX expression (``License-Expression`` metadata). ``UNKNOWN`` when absent.
``License-Metadata``
    The free-text ``License`` metadata field, e.g. ``MIT License``, ``BSD``, ``GPL``.
``License-Classifier``
    The ``License ::`` trove classifiers, joined with ``"; "``.
``LicenseText``
    The text of the shipped licence file, or ``UNKNOWN``.

Python has no lockfile. The check therefore runs against what is *installed* (the Docker
image build) and is never a required pull request check.

Classification rules, in this order (:func:`classify`):

1. An exception for ``pkg:pypi/<normalised name>`` in ``x-licence-exceptions`` applies when the
   package declares no ``License-Expression`` at all (the metadata is missing), or declares
   exactly the string the exception records as ``reviewed_expression`` (the metadata is wrong
   in a way that was reviewed). Exceptions carry no version (there is no lockfile, and a pinned
   exception would fail the image build on every upstream release). When a release declares
   something else, the exception does not apply and the record is judged as declared: a later
   release cannot hide behind the licence that was reviewed for an older one. If that leaves
   the package refused, the report says "exception reviewed against X, package now declares Y".
2. A valid SPDX ``License-Expression`` is used as it is.
3. Otherwise the classifiers are mapped one by one through :data:`CLASSIFIER_TO_SPDX` and
   joined with `` OR ``. When the only unmapped classifier is the ambiguous bare
   ``BSD License``, the step yields nothing and the metadata decides; any other unmapped
   classifier yields ``UNKNOWN`` (conflicting data is never settled by the metadata).
4. Otherwise :data:`METADATA_TO_SPDX`.
5. Otherwise ``UNKNOWN``, which is never allowed.

A bare ``BSD License`` classifier is deliberately *not* mapped: it covers BSD-2-Clause,
BSD-3-Clause and others, and guessing would be a silent licence decision. Such a package needs
an exception that names the licence its licence file really carries.

An exception may pin the reviewed licence file with ``licence-text-sha256`` (see
:func:`licence_text_sha256`). When the collected ``LicenseText`` hashes differently the exception
does not apply and the record is ``UNKNOWN``: a licence file that changed since the review is
not covered by it. A ``Proprietary`` classifier next to other classifiers also yields
``UNKNOWN`` instead of ``<licence> OR Proprietary``. How to refresh a hash is written in
``licence-policy.yml`` (``x-licence-text-sha256-refresh``).

Measured on 2026-11-05 (spike S3a, the runtime venv of ``backend/pyproject.toml``):
expressions, classifiers and metadata strings listed in the two maps below are exactly the
ones seen; the packages that still resolve to ``UNKNOWN`` (``pysnmp``, ``qrcode``, ``Jinja2``,
``pyusb``) carry an exception in ``licence-policy.yml``.

Usage::

    python -m scripts.licence_report --python <interpreter> --policy <file> \\
        --own-project <pyproject.toml> [--output <json>] [--require-texts] \\
        [--extra <json> [--extra-root <dir>]] [--fallback-dir <dir>]

``--output`` writes the list the image serves as ``/licenses/backend.json``: one
:class:`LicenceRecord` per package, with the field names of ``rollup-license-plugin`` so the
About page parses it and the web list with one function.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

PROPRIETARY = "Proprietary"

#: Classifier names (after ``License ::``) seen in the runtime environment, mapped to SPDX.
CLASSIFIER_TO_SPDX: Mapping[str, str] = {
    "Apache Software License": "Apache-2.0",
    "GNU General Public License v3 or later (GPLv3+)": "GPL-3.0-or-later",
    "GNU Lesser General Public License v2 or later (LGPLv2+)": "LGPL-2.0-or-later",
    "MIT License": "MIT",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "Other/Proprietary License": PROPRIETARY,
}

#: Values of the free-text ``License`` metadata field seen in the runtime environment.
METADATA_TO_SPDX: Mapping[str, str] = {
    "Apache-2.0": "Apache-2.0",
    "BSD-2-Clause": "BSD-2-Clause",
    "BSD-3-Clause": "BSD-3-Clause",
    "MIT": "MIT",
    "MIT License": "MIT",
    "MPL-2.0": "MPL-2.0",
}

UNKNOWN = "UNKNOWN"

MISSING_TEXT_POINTER = (
    'See "Dependencies and licences → A licence text is missing" in CONTRIBUTING.md'
)

_SHA256 = re.compile(r"[0-9a-f]{64}")

_TOKEN = re.compile(r"\(|\)|[A-Za-z0-9][A-Za-z0-9.+:\-]*")


class LicenceRecord(TypedDict):
    """One package of the served list; the keys are those of ``rollup-license-plugin``."""

    name: str
    version: str
    license: str
    licenseText: str | None
    repository: str | None


@dataclass(frozen=True)
class LicenceException:
    """One reviewed deviation: the licence a package really carries, and why."""

    purl: str
    licence: str
    reason: str
    #: The ``License-Expression`` string the package declared when the exception was reviewed
    #: (only for packages that declare something that is not usable as it stands).
    reviewed_expression: str | None = None
    #: SHA-256 (lower-case hex, UTF-8) of the ``LicenseText`` that was reviewed.
    licence_text_sha256: str | None = None


@dataclass(frozen=True)
class Policy:
    """The allow list and the exceptions, keyed by normalised purl."""

    allowed: frozenset[str]
    exceptions: Mapping[str, LicenceException]


def normalise_purl(purl: str) -> str:
    """Normalise a package URL so lookups do not depend on spelling.

    PyPI names are case-insensitive and treat ``-``, ``_`` and ``.`` alike (PEP 503).
    """
    purl = purl.strip()
    if purl.lower().startswith("pkg:pypi/"):
        name, sep, version = purl[len("pkg:pypi/") :].partition("@")
        return "pkg:pypi/" + re.sub(r"[-_.]+", "-", name).lower() + sep + version
    return purl


def load_policy(path: Path) -> Policy:
    """Read the policy file. Raises :class:`ValueError` when it is malformed."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: the policy must be a mapping")
    licences = data.get("allow-licenses")
    if not isinstance(licences, list) or not licences:
        raise ValueError(f"{path}: allow-licenses must be a non-empty list")
    exceptions: dict[str, LicenceException] = {}
    for raw in data.get("x-licence-exceptions", []):
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: every x-licence-exceptions entry must be a mapping")
        purl, licence, reason = raw.get("purl"), raw.get("licence"), raw.get("reason")
        if not (isinstance(purl, str) and isinstance(licence, str) and isinstance(reason, str)):
            raise ValueError(f"{path}: an exception needs purl, licence and reason: {raw!r}")
        if not purl.strip() or not licence.strip() or not reason.strip():
            raise ValueError(f"{path}: purl, licence and reason must not be empty: {raw!r}")
        reviewed = raw.get("reviewed_expression")
        if reviewed is not None and not (isinstance(reviewed, str) and reviewed.strip()):
            raise ValueError(f"{path}: reviewed_expression must be a non-empty string: {raw!r}")
        digest = raw.get("licence-text-sha256")
        if digest is not None and not (isinstance(digest, str) and _SHA256.fullmatch(digest)):
            raise ValueError(
                f"{path}: licence-text-sha256 must be 64 lower-case hex digits: {raw!r}"
            )
        exceptions[normalise_purl(purl)] = LicenceException(
            purl, licence, reason, reviewed.strip() if reviewed else None, digest
        )
    return Policy(allowed=frozenset(licences), exceptions=exceptions)


class _Parser:
    """Recursive descent over an SPDX expression: ``WITH`` > ``AND`` > ``OR``."""

    def __init__(self, tokens: Sequence[str], allowed: frozenset[str]) -> None:
        self._tokens = tokens
        self._allowed = allowed
        self._pos = 0

    def _peek(self) -> str | None:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else None

    def _next(self) -> str:
        token = self._tokens[self._pos]
        self._pos += 1
        return token

    def parse(self) -> bool:
        result = self._or()
        if self._peek() is not None:
            raise ValueError("trailing tokens")
        return result

    def _or(self) -> bool:
        result = self._and()
        while self._peek() == "OR":
            self._next()
            right = self._and()  # always parse the right side, it may be malformed
            result = result or right
        return result

    def _and(self) -> bool:
        result = self._atom()
        while self._peek() == "AND":
            self._next()
            right = self._atom()
            result = result and right
        return result

    def _atom(self) -> bool:
        token = self._peek()
        if token is None:
            raise ValueError("unexpected end")
        if token == "(":
            self._next()
            result = self._or()
            if self._peek() != ")":
                raise ValueError("missing )")
            self._next()
            return result
        if token in {")", "AND", "OR", "WITH"}:
            raise ValueError(f"unexpected {token}")
        self._next()
        result = token in self._allowed
        if self._peek() == "WITH":  # the exception is judged by the licence it modifies
            self._next()
            exception = self._peek()
            if exception is None or exception in {"(", ")", "AND", "OR", "WITH"}:
                raise ValueError("WITH needs an exception id")
            self._next()
        return result


def expression_allowed(expr: str, allowed: frozenset[str]) -> bool:
    """Whether an SPDX expression is covered by the allow list.

    ``OR`` means any branch, ``AND`` means all branches, ``X WITH Y`` is judged by ``X``.
    An empty or unparseable expression is not allowed.
    """
    stripped = expr.strip()
    if not stripped:
        return False
    tokens = _TOKEN.findall(stripped)
    if "".join(tokens) != re.sub(r"\s+", "", stripped):
        return False  # characters outside the SPDX grammar
    try:
        return _Parser(tokens, allowed).parse()
    except ValueError:
        return False


#: The one classifier that is knowingly ambiguous (BSD-2-Clause, BSD-3-Clause and others).
_AMBIGUOUS_CLASSIFIER = "BSD License"


def _classifier_expression(classifiers: str) -> tuple[str | None, bool]:
    """Map the classifiers to ``(expression, metadata_may_decide)``."""
    parts = [part.strip() for part in classifiers.split("; ") if part.strip()]
    if not parts or classifiers == UNKNOWN:
        return None, True
    mapped = [CLASSIFIER_TO_SPDX.get(part) for part in parts]
    unmapped = [part for part, item in zip(parts, mapped, strict=True) if item is None]
    if unmapped:
        return None, all(part == _AMBIGUOUS_CLASSIFIER for part in unmapped)
    if len(mapped) > 1 and PROPRIETARY in mapped:
        # ``X; Other/Proprietary License`` must not read as ``X OR Proprietary`` and pass.
        return None, False
    return " OR ".join(item for item in mapped if item is not None), True


def _is_spdx_expression(value: str) -> bool:
    # A syntactically valid expression: judged against a permissive allow list.
    value = value.strip()
    if not value or value == UNKNOWN:
        return False
    tokens = _TOKEN.findall(value)
    if "".join(tokens) != re.sub(r"\s+", "", value):
        return False
    try:
        everything = frozenset(token for token in tokens if token not in {"(", ")"})
        _Parser(tokens, everything).parse()
    except ValueError:
        return False
    return True


def _declared(entry: Mapping[str, str]) -> str:
    """The ``License-Expression`` the package declares, or an empty string."""
    value = entry.get("License-Expression", UNKNOWN).strip()
    return "" if value == UNKNOWN else value


def licence_text_sha256(entry: Mapping[str, str]) -> str:
    """SHA-256 (hex) of the ``LicenseText`` exactly as pip-licenses reports it, UTF-8 encoded."""
    return hashlib.sha256(entry.get("LicenseText", UNKNOWN).encode("utf-8")).hexdigest()


def _text_changed(entry: Mapping[str, str], exception: LicenceException) -> bool:
    """Whether the exception pins a licence text and the collected one differs."""
    pinned = exception.licence_text_sha256
    return pinned is not None and pinned != licence_text_sha256(entry)


def _exception_matches(declared: str, exception: LicenceException) -> bool:
    """Whether the declared expression is the one the exception was reviewed against (or none)."""
    return not declared or declared == exception.reviewed_expression


def _stale_exception(entry: Mapping[str, str], policy: Policy) -> str | None:
    """Why an exception does not apply to this record, or None when it does or there is none."""
    exception = policy.exceptions.get(normalise_purl(f"pkg:pypi/{entry['Name']}"))
    declared = _declared(entry)
    if exception is None:
        return None
    if _exception_matches(declared, exception):
        if _text_changed(entry, exception):
            return (
                "exception reviewed against a different licence text, the licence file has changed"
            )
        return None
    reviewed = exception.reviewed_expression or "no declared expression"
    return f"exception reviewed against {reviewed}, package now declares {declared}"


def classify(entry: Mapping[str, str], policy: Policy) -> tuple[str, bool]:
    """Return ``(licence expression, allowed)`` for one pip-licenses ``--from=all`` record."""
    exception = policy.exceptions.get(normalise_purl(f"pkg:pypi/{entry['Name']}"))
    declared = _declared(entry)
    if exception is not None and _exception_matches(declared, exception):
        # A changed licence file voids the exception, whatever the classifiers would say.
        expression = UNKNOWN if _text_changed(entry, exception) else exception.licence
    elif _is_spdx_expression(declared):
        expression = declared
    elif declared and exception is not None:
        expression = declared  # unusable, and the reviewed exception no longer matches it
    else:
        from_classifiers, metadata_may_decide = _classifier_expression(
            entry.get("License-Classifier", UNKNOWN)
        )
        expression = (
            from_classifiers
            or (
                METADATA_TO_SPDX.get(entry.get("License-Metadata", UNKNOWN).strip())
                if metadata_may_decide
                else None
            )
            or UNKNOWN
        )
    return expression, expression_allowed(expression, policy.allowed)


def check(entries: Iterable[Mapping[str, str]], policy: Policy) -> list[str]:
    """The sorted ``name (licence)`` of every record the policy refuses."""
    offenders = []
    for entry in entries:
        expression, allowed = classify(entry, policy)
        if not allowed:
            line = f"{entry['Name']} ({expression})"
            stale = _stale_exception(entry, policy)
            offenders.append(f"{line}: {stale}" if stale else line)
    return sorted(offenders, key=str.lower)


def own_package_name(pyproject: Path) -> str:
    """The project's own distribution name, ``[project].name`` of its ``pyproject.toml``."""
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    name = data.get("project", {}).get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"{pyproject}: [project].name is missing")
    return name


def _collect(interpreter: str, own: str) -> list[dict[str, str]]:
    """The packages of ``interpreter``'s environment, without the project's own ``own``."""
    command = [
        sys.executable,
        "-m",
        "piplicenses",
        "--python",
        interpreter,
        "--from=all",
        "--with-system",
        "--format=json",
        "--with-license-file",
        "--no-license-path",
        "--with-urls",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"pip-licenses failed ({result.returncode}): {result.stderr.strip()}")
    data = json.loads(result.stdout)
    skip = normalise_purl(f"pkg:pypi/{own}")
    return [e for e in data if normalise_purl(f"pkg:pypi/{e['Name']}") != skip]


def load_extra(path: Path, root: Path) -> list[LicenceRecord]:
    """Read the hand-kept records of what pip does not list (fonts, sheet data).

    Every entry is ``{name, version, license, licenseTextFile, repository}``; the text file is
    read relative to ``root``. A missing file raises :class:`ValueError` naming it.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path}: the extra records must be a list")
    records: list[LicenceRecord] = []
    for raw in data:
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: every extra record must be a mapping: {raw!r}")
        try:
            name, version = str(raw["name"]), str(raw["version"])
            licence, text_file = str(raw["license"]), str(raw["licenseTextFile"])
        except KeyError as error:
            raise ValueError(f"{path}: an extra record lacks {error}: {raw!r}") from error
        text_path = root / text_file
        if not text_path.is_file():
            raise ValueError(f"{path}: licence text file not found for {name}: {text_path}")
        repository = raw.get("repository")
        records.append(
            {
                "name": name,
                "version": version,
                "license": licence,
                "licenseText": text_path.read_text(encoding="utf-8"),
                "repository": repository if isinstance(repository, str) else None,
            }
        )
    return records


_SINGLE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+\-]*")


def _text_for(entry: Mapping[str, str], expression: str, fallback_dir: Path) -> str | None:
    """The package's own licence text, else the canonical text of a single SPDX id, else None."""
    own = entry.get("LicenseText", UNKNOWN)
    if own != UNKNOWN and own.strip():
        return own
    if expression != UNKNOWN and _SINGLE_ID.fullmatch(expression):
        candidate = fallback_dir / f"{expression}.txt"
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    return None


def to_records(
    entries: Iterable[Mapping[str, str]],
    policy: Policy,
    fallback_dir: Path,
    extra: Sequence[LicenceRecord] = (),
) -> list[LicenceRecord]:
    """The served list (D23): ``entries`` classified, ``extra`` appended unjudged, sorted."""
    records: list[LicenceRecord] = []
    for entry in entries:
        expression, _ = classify(entry, policy)
        url = entry.get("URL", UNKNOWN).strip()
        records.append(
            {
                "name": entry["Name"],
                "version": entry["Version"],
                "license": expression,
                "licenseText": _text_for(entry, expression, fallback_dir),
                "repository": url if url.lower().startswith(("http://", "https://")) else None,
            }
        )
    records.extend(extra)
    return sorted(records, key=lambda record: record["name"].lower())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    parser.add_argument("--python", required=True, help="interpreter of the environment to check")
    parser.add_argument("--policy", required=True, type=Path, help="licence-policy.yml")
    parser.add_argument(
        "--own-project", required=True, type=Path, help="pyproject.toml of the project itself"
    )
    parser.add_argument("--output", type=Path, help="write the licence list as JSON")
    parser.add_argument(
        "--require-texts", action="store_true", help="fail when a record has no licence text"
    )
    parser.add_argument("--extra", type=Path, help="JSON list of records pip does not know")
    parser.add_argument("--extra-root", type=Path, default=Path(), help="base of the text files")
    parser.add_argument(
        "--fallback-dir", type=Path, default=Path("licences"), help="canonical SPDX texts"
    )
    args = parser.parse_args(argv)

    policy = load_policy(args.policy)
    entries = _collect(args.python, own_package_name(args.own_project))
    extra = load_extra(args.extra, args.extra_root) if args.extra else []
    offenders = check(entries, policy)
    records = to_records(entries, policy, args.fallback_dir, extra)
    if args.output:
        args.output.write_text(
            json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    for line in offenders:
        sys.stdout.write(line + "\n")
    missing = [r for r in records if not r["licenseText"]] if args.require_texts else []
    for record in missing:
        sys.stdout.write(f"{record['name']} ({record['license']}): no licence text\n")
    if missing:
        sys.stdout.write(MISSING_TEXT_POINTER + "\n")
    return 1 if offenders or missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
