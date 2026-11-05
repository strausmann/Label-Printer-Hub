"""Tests for ``scripts.licence_report`` (hand-written records, no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.licence_report import (
    LicenceException,
    Policy,
    check,
    classify,
    expression_allowed,
    load_policy,
    normalise_purl,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
VECTORS = json.loads((REPO_ROOT / "docs" / "licence-test-vectors.json").read_text("utf-8"))
ALLOWED = frozenset({"MIT", "MIT-0", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "CC0-1.0"})
ALLOWED |= frozenset({"PSF-2.0", "LGPL-2.1-or-later"})


def _policy(**exceptions: tuple[str, str]) -> Policy:
    return Policy(
        allowed=ALLOWED,
        exceptions={
            normalise_purl(f"pkg:pypi/{name}"): LicenceException(
                purl=f"pkg:pypi/{name}", licence=lic, reason=reason
            )
            for name, (lic, reason) in exceptions.items()
        },
    )


def _record(
    name: str,
    *,
    expression: str = "UNKNOWN",
    metadata: str = "UNKNOWN",
    classifier: str = "UNKNOWN",
) -> dict[str, str]:
    return {
        "Name": name,
        "Version": "1.0",
        "License-Expression": expression,
        "License-Metadata": metadata,
        "License-Classifier": classifier,
        "LicenseText": "text",
    }


@pytest.mark.parametrize("vector", VECTORS, ids=lambda v: v["expression"] or "<empty>")
def test_vectors(vector: dict[str, object]) -> None:
    policy = load_policy(REPO_ROOT / "licence-policy.yml")
    assert expression_allowed(str(vector["expression"]), policy.allowed) is vector["allowed"]


@pytest.mark.parametrize(
    "expression",
    ["MIT AND", "(MIT", "MIT)", "MIT MIT", "OR MIT", "MIT WITH", "AND", "()", "MIT OR OR MIT"],
)
def test_unparseable_expression_is_refused(expression: str) -> None:
    assert expression_allowed(expression, ALLOWED) is False


def test_precedence_and_grouping() -> None:
    # AND binds tighter than OR: MIT OR (GPL AND MIT) is allowed, (MIT OR GPL) AND GPL is not.
    assert expression_allowed("MIT OR GPL-2.0-only AND MIT", ALLOWED) is True
    assert expression_allowed("(MIT OR Apache-2.0) AND GPL-2.0-only", ALLOWED) is False


def test_multi_classifier_is_or() -> None:
    entry = _record("uvloop", classifier="Apache Software License; MIT License")
    assert classify(entry, _policy()) == ("Apache-2.0 OR MIT", True)


def test_bare_bsd_classifier_needs_exception() -> None:
    entry = _record("Jinja2", classifier="BSD License")
    assert classify(entry, _policy()) == ("UNKNOWN", False)
    with_exception = _policy(jinja2=("BSD-3-Clause", "bare BSD License classifier"))
    assert classify(entry, with_exception) == ("BSD-3-Clause", True)


def test_proprietary_classifier_alone_refused() -> None:
    entry = _record("thing", classifier="Other/Proprietary License")
    assert classify(entry, _policy()) == ("Proprietary", False)


def test_unknown_everywhere_refused() -> None:
    entry = _record("pysnmp")
    assert classify(entry, _policy()) == ("UNKNOWN", False)
    with_exception = _policy(pysnmp=("BSD-2-Clause", "metadata UNKNOWN; licence file is BSD-2"))
    assert classify(entry, with_exception) == ("BSD-2-Clause", True)


def test_ptouch_exception() -> None:
    entry = _record("ptouch", classifier="GNU Lesser General Public License v2 or later (LGPLv2+)")
    policy = _policy(ptouch=("LGPL-2.1-or-later", "shipped text is LGPL 2.1"))
    assert classify(entry, policy) == ("LGPL-2.1-or-later", True)


def test_expression_field_wins() -> None:
    entry = _record("cffi", expression="MIT-0")
    assert classify(entry, _policy()) == ("MIT-0", True)


def test_expression_beats_classifier_and_metadata() -> None:
    entry = _record("pkg", expression="MIT", metadata="GPL", classifier="Other/Proprietary License")
    assert classify(entry, _policy()) == ("MIT", True)


def test_exception_beats_a_valid_expression() -> None:
    entry = _record("qrcode", expression="MIT")
    policy = _policy(qrcode=("BSD-3-Clause", "reason"))
    assert classify(entry, policy) == ("BSD-3-Clause", True)


def test_exception_lookup_normalises_the_name() -> None:
    entry = _record("Typing_Extensions")
    policy = _policy(**{"typing-extensions": ("PSF-2.0", "reason")})
    assert classify(entry, policy) == ("PSF-2.0", True)


def test_unmapped_classifier_falls_through_to_metadata() -> None:
    # httpx: classifier is a bare BSD License, metadata names the real licence.
    entry = _record("httpx", metadata="BSD-3-Clause", classifier="BSD License")
    assert classify(entry, _policy()) == ("BSD-3-Clause", True)


def test_metadata_strings_are_mapped() -> None:
    assert classify(_record("a", metadata="MIT License"), _policy()) == ("MIT", True)
    assert classify(_record("b", metadata="BSD-2-Clause"), _policy()) == ("BSD-2-Clause", True)


def test_ambiguous_metadata_is_not_guessed() -> None:
    assert classify(_record("c", metadata="BSD"), _policy()) == ("UNKNOWN", False)
    assert classify(_record("d", metadata="GPL"), _policy()) == ("UNKNOWN", False)


def test_check_lists_offenders_sorted() -> None:
    entries = [
        _record("zeta", classifier="Other/Proprietary License"),
        _record("fine", expression="MIT"),
        _record("Alpha"),
        _record("label-printer-hub-backend"),
    ]
    assert check(entries, _policy()) == [
        "Alpha (UNKNOWN)",
        "label-printer-hub-backend (UNKNOWN)",
        "zeta (Proprietary)",
    ]


def test_load_policy_reads_exceptions_by_normalised_purl(tmp_path: Path) -> None:
    path = tmp_path / "policy.yml"
    path.write_text(
        json.dumps(
            {
                "allow-licenses": ["MIT"],
                "x-licence-exceptions": [
                    {"purl": "pkg:pypi/Foo_Bar", "licence": "MIT", "reason": "r"},
                    {"purl": "pkg:npm/x@1.0.0", "licence": "MIT", "reason": "r"},
                ],
            }
        ),
        encoding="utf-8",
    )
    policy = load_policy(path)
    assert policy.allowed == frozenset({"MIT"})
    assert set(policy.exceptions) == {"pkg:pypi/foo-bar", "pkg:npm/x@1.0.0"}


@pytest.mark.parametrize(
    "document",
    [
        {"x-licence-exceptions": []},
        {"allow-licenses": []},
        {"allow-licenses": ["MIT"], "x-licence-exceptions": [{"purl": "pkg:pypi/a"}]},
        {
            "allow-licenses": ["MIT"],
            "x-licence-exceptions": [{"purl": "pkg:pypi/a", "licence": "MIT", "reason": " "}],
        },
        ["not", "a", "mapping"],
    ],
)
def test_load_policy_rejects_malformed_documents(tmp_path: Path, document: object) -> None:
    path = tmp_path / "policy.yml"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError):
        load_policy(path)
