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

1. An exception for ``pkg:pypi/<normalised name>`` in ``x-licence-exceptions`` wins.
2. A valid SPDX ``License-Expression`` is used as it is.
3. Otherwise the classifiers are mapped one by one through :data:`CLASSIFIER_TO_SPDX` and
   joined with `` OR ``. When one classifier cannot be mapped, the step yields nothing.
4. Otherwise :data:`METADATA_TO_SPDX`.
5. Otherwise ``UNKNOWN``, which is never allowed.

A bare ``BSD License`` classifier is deliberately *not* mapped: it covers BSD-2-Clause,
BSD-3-Clause and others, and guessing would be a silent licence decision. Such a package needs
an exception that names the licence its licence file really carries.

Measured on 2026-11-05 (spike S3a, the runtime venv of ``backend/pyproject.toml``):
expressions, classifiers and metadata strings listed in the two maps below are exactly the
ones seen; the packages that still resolve to ``UNKNOWN`` (``pysnmp``, ``qrcode``, ``Jinja2``,
``pyusb``) carry an exception in ``licence-policy.yml``.

Usage::

    python -m scripts.licence_report --python <interpreter> --policy <file> [--output <json>]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

#: The project's own distribution, excluded from the check.
OWN_PACKAGE = "label-printer-hub-backend"

#: Classifier names (after ``License ::``) seen in the runtime environment, mapped to SPDX.
CLASSIFIER_TO_SPDX: Mapping[str, str] = {
    "Apache Software License": "Apache-2.0",
    "GNU General Public License v3 or later (GPLv3+)": "GPL-3.0-or-later",
    "GNU Lesser General Public License v2 or later (LGPLv2+)": "LGPL-2.0-or-later",
    "MIT License": "MIT",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "Other/Proprietary License": "Proprietary",
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

_TOKEN = re.compile(r"\(|\)|[A-Za-z0-9][A-Za-z0-9.+:\-]*")


@dataclass(frozen=True)
class LicenceException:
    """One reviewed deviation: the licence a package really carries, and why."""

    purl: str
    licence: str
    reason: str


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
        exceptions[normalise_purl(purl)] = LicenceException(purl, licence, reason)
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


def _classifier_expression(classifiers: str) -> str | None:
    parts = [part.strip() for part in classifiers.split("; ") if part.strip()]
    if not parts or classifiers == UNKNOWN:
        return None
    mapped = [CLASSIFIER_TO_SPDX.get(part) for part in parts]
    if any(item is None for item in mapped):
        return None
    return " OR ".join(item for item in mapped if item is not None)


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


def classify(entry: Mapping[str, str], policy: Policy) -> tuple[str, bool]:
    """Return ``(licence expression, allowed)`` for one pip-licenses ``--from=all`` record."""
    exception = policy.exceptions.get(normalise_purl(f"pkg:pypi/{entry['Name']}"))
    if exception is not None:
        expression = exception.licence
    elif _is_spdx_expression(entry.get("License-Expression", UNKNOWN)):
        expression = entry["License-Expression"].strip()
    else:
        expression = (
            _classifier_expression(entry.get("License-Classifier", UNKNOWN))
            or METADATA_TO_SPDX.get(entry.get("License-Metadata", UNKNOWN).strip())
            or UNKNOWN
        )
    return expression, expression_allowed(expression, policy.allowed)


def check(entries: Iterable[Mapping[str, str]], policy: Policy) -> list[str]:
    """The sorted ``name (licence)`` of every record the policy refuses."""
    offenders = []
    for entry in entries:
        expression, allowed = classify(entry, policy)
        if not allowed:
            offenders.append(f"{entry['Name']} ({expression})")
    return sorted(offenders, key=str.lower)


def _collect(interpreter: str) -> list[dict[str, str]]:
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
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"pip-licenses failed ({result.returncode}): {result.stderr.strip()}")
    data = json.loads(result.stdout)
    own = normalise_purl(f"pkg:pypi/{OWN_PACKAGE}")
    return [e for e in data if normalise_purl(f"pkg:pypi/{e['Name']}") != own]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    parser.add_argument("--python", required=True, help="interpreter of the environment to check")
    parser.add_argument("--policy", required=True, type=Path, help="licence-policy.yml")
    parser.add_argument("--output", type=Path, help="write the classified records as JSON")
    args = parser.parse_args(argv)

    policy = load_policy(args.policy)
    entries = _collect(args.python)
    if args.output:
        classified = [
            {
                "name": e["Name"],
                "version": e["Version"],
                "licence": classify(e, policy)[0],
                "allowed": classify(e, policy)[1],
            }
            for e in entries
        ]
        args.output.write_text(json.dumps(classified, indent=2) + "\n", encoding="utf-8")
    offenders = check(entries, policy)
    for line in offenders:
        sys.stdout.write(line + "\n")
    return 1 if offenders else 0


if __name__ == "__main__":
    raise SystemExit(main())
