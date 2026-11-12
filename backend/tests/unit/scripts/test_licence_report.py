"""Tests for ``scripts.licence_report`` (hand-written records, no network)."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from scripts import licence_report
from scripts.licence_report import (
    LicenceException,
    Policy,
    _collect,
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


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _policy(reviewed: dict[str, str] | None = None, /, **exceptions: tuple[str, str]) -> Policy:
    reviewed = reviewed or {}
    return Policy(
        allowed=ALLOWED,
        exceptions={
            normalise_purl(f"pkg:pypi/{name}"): LicenceException(
                purl=f"pkg:pypi/{name}",
                licence=lic,
                reason=reason,
                reviewed_expression=reviewed.get(name),
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
    text: str = "text",
) -> dict[str, str]:
    return {
        "Name": name,
        "Version": "1.0",
        "License-Expression": expression,
        "License-Metadata": metadata,
        "License-Classifier": classifier,
        "LicenseText": text,
    }


def _pinned(policy: Policy, name: str, text: str) -> Policy:
    """``policy`` with the exception for ``name`` pinned to the hash of ``text``."""
    key = normalise_purl(f"pkg:pypi/{name}")
    pinned = replace(policy.exceptions[key], licence_text_sha256=_sha256(text))
    return Policy(allowed=policy.allowed, exceptions={**policy.exceptions, key: pinned})


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


def test_exception_does_not_hide_a_declared_expression() -> None:
    # The exception was reviewed for a release with deficient metadata. A release that declares
    # a licence is judged as declared: a drifted licence must not hide behind the old review.
    policy = _policy(qrcode=("BSD-3-Clause", "reason"))
    assert classify(_record("qrcode", expression="GPL-2.0-only"), policy) == (
        "GPL-2.0-only",
        False,
    )
    assert classify(_record("qrcode", expression="MIT"), policy) == ("MIT", True)


def test_exception_applies_while_the_metadata_stays_deficient() -> None:
    policy = _policy(qrcode=("BSD-3-Clause", "reason"))
    entry = _record("qrcode", metadata="BSD", classifier="BSD License; Other/Proprietary License")
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


def test_exception_survives_the_exact_expression_it_was_reviewed_against() -> None:
    # A package that declares a non-SPDX or LicenseRef expression has a documented way out.
    policy = _policy(
        {"bundled": "Apache-2.0 AND LicenseRef-Bundled-Font"},
        bundled=("Apache-2.0", "the bundled font is OFL-1.1"),
    )
    declared = "Apache-2.0 AND LicenseRef-Bundled-Font"
    assert classify(_record("bundled", expression=declared), policy) == ("Apache-2.0", True)
    assert check([_record("bundled", expression=declared)], policy) == []


def test_exception_stops_applying_when_the_declared_expression_changes() -> None:
    policy = _policy({"bundled": "BSD"}, bundled=("BSD-3-Clause", "declares the bare id BSD"))
    drifted = _record("bundled", expression="GPL-2.0-only")
    assert classify(drifted, policy) == ("GPL-2.0-only", False)
    assert check([drifted], policy) == [
        "bundled (GPL-2.0-only): exception reviewed against BSD, package now declares GPL-2.0-only"
    ]
    # An unusable declaration that was never reviewed is refused with the same message.
    unusable = _record("bundled", expression="BSD-ish")
    assert check([unusable], policy) == [
        "bundled (BSD-ish): exception reviewed against BSD, package now declares BSD-ish"
    ]


def test_exception_without_reviewed_expression_stops_when_something_is_declared() -> None:
    policy = _policy(pysnmp=("BSD-2-Clause", "metadata UNKNOWN"))
    drifted = _record("pysnmp", expression="LicenseRef-x")
    assert check([drifted], policy) == [
        "pysnmp (LicenseRef-x): exception reviewed against no declared expression, "
        "package now declares LicenseRef-x"
    ]


def test_conflicting_classifier_is_not_settled_by_metadata() -> None:
    entry = _record("x", metadata="MIT", classifier="GNU General Public License v2 (GPLv2)")
    assert classify(entry, _policy()) == ("UNKNOWN", False)


def test_load_policy_reads_reviewed_expression(tmp_path: Path) -> None:
    path = tmp_path / "policy.yml"
    doc: dict[str, Any] = {
        "allow-licenses": ["MIT"],
        "x-licence-exceptions": [
            {"purl": "pkg:pypi/a", "licence": "MIT", "reason": "r", "reviewed_expression": "BSD"}
        ],
    }
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert load_policy(path).exceptions["pkg:pypi/a"].reviewed_expression == "BSD"
    doc["x-licence-exceptions"][0]["reviewed_expression"] = " "
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError):
        load_policy(path)


def test_collect_excludes_the_own_package_and_reports_tool_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        _record("label-printer-hub-backend", expression="MIT"),
        _record("a", expression="MIT"),
    ]

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        assert command[1:3] == ["-m", "piplicenses"]
        assert "--from=all" in command
        return subprocess.CompletedProcess(command, 0, json.dumps(records), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert [e["Name"] for e in _collect("python")] == ["a"]

    def failing_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 2, "", "boom")

    monkeypatch.setattr(subprocess, "run", failing_run)
    with pytest.raises(RuntimeError, match="boom"):
        _collect("python")


def test_main_exit_codes_and_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    policy_file = tmp_path / "policy.yml"
    policy_file.write_text(json.dumps({"allow-licenses": ["MIT"]}), encoding="utf-8")
    monkeypatch.setattr(
        licence_report,
        "_collect",
        lambda _: [_record("ok", expression="MIT"), _record("bad", expression="GPL-2.0-only")],
    )
    out = tmp_path / "out.json"
    code = licence_report.main(
        ["--python", "x", "--policy", str(policy_file), "--output", str(out)]
    )
    assert code == 1
    assert capsys.readouterr().out == "bad (GPL-2.0-only)\n"
    assert {r["name"]: r["allowed"] for r in json.loads(out.read_text("utf-8"))} == {
        "ok": True,
        "bad": False,
    }
    monkeypatch.setattr(licence_report, "_collect", lambda _: [_record("ok", expression="MIT")])
    assert licence_report.main(["--python", "x", "--policy", str(policy_file)]) == 0


def test_exception_with_changed_licence_text_fails() -> None:
    # The pinned hash is of the text that was reviewed; a changed licence file voids the
    # exception even when the classifiers alone would be accepted (ptouch maps to LGPL).
    classifier = "GNU Lesser General Public License v2 or later (LGPLv2+)"
    policy = _pinned(
        _policy(ptouch=("LGPL-2.1-or-later", "shipped text is LGPL 2.1")), "ptouch", "reviewed text"
    )
    changed = _record("ptouch", classifier=classifier, text="a different licence text")
    assert classify(changed, policy) == ("UNKNOWN", False)
    assert check([changed], policy) == [
        "ptouch (UNKNOWN): exception reviewed against a different licence text, "
        "the licence file has changed"
    ]
    unchanged = _record("ptouch", classifier=classifier, text="reviewed text")
    assert classify(unchanged, policy) == ("LGPL-2.1-or-later", True)


def test_exception_without_hash_still_applies() -> None:
    policy = _policy(pysnmp=("BSD-2-Clause", "metadata UNKNOWN"))
    entry = _record("pysnmp", text="any text at all")
    assert classify(entry, policy) == ("BSD-2-Clause", True)


def test_proprietary_in_join_is_unknown() -> None:
    entry = _record("newpkg", classifier="MIT License; Other/Proprietary License")
    assert classify(entry, _policy()) == ("UNKNOWN", False)
    # Without a mapped Proprietary the join stays an OR of the mapped licences.
    entry = _record("other", classifier="Apache Software License; MIT License")
    assert classify(entry, _policy()) == ("Apache-2.0 OR MIT", True)


def test_proprietary_join_is_not_settled_by_metadata() -> None:
    entry = _record("newpkg", metadata="MIT", classifier="MIT License; Other/Proprietary License")
    assert classify(entry, _policy()) == ("UNKNOWN", False)


def test_load_policy_reads_licence_text_sha256(tmp_path: Path) -> None:
    digest = _sha256("x")
    path = tmp_path / "policy.yml"
    doc: dict[str, Any] = {
        "allow-licenses": ["MIT"],
        "x-licence-exceptions": [
            {"purl": "pkg:pypi/a", "licence": "MIT", "reason": "r", "licence-text-sha256": digest}
        ],
    }
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert load_policy(path).exceptions["pkg:pypi/a"].licence_text_sha256 == digest
    for bad in (" ", "abc", "Z" * 64, 5):
        doc["x-licence-exceptions"][0]["licence-text-sha256"] = bad
        path.write_text(json.dumps(doc), encoding="utf-8")
        with pytest.raises(ValueError):
            load_policy(path)


def test_shipped_policy_pins_the_python_exceptions() -> None:
    policy = load_policy(REPO_ROOT / "licence-policy.yml")
    pypi = {p: e for p, e in policy.exceptions.items() if p.startswith("pkg:pypi/")}
    assert {
        "pkg:pypi/" + n for n in ("pysnmp", "qrcode", "jinja2", "pyusb", "ptouch", "reportlab")
    } <= set(pypi)
    unpinned = sorted(p for p, e in pypi.items() if not e.licence_text_sha256)
    assert unpinned == [], f"pypi exceptions without licence-text-sha256: {unpinned}"
