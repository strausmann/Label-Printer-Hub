"""Guards for ``licence-policy.yml``, the one policy file every licence gate reads."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.licence_report import expression_allowed, normalise_purl

REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = REPO_ROOT / "licence-policy.yml"

# The agreed allow list (call 7 of the relicensing plan). A change here is a policy
# decision and has to be made in this test as well.
EXPECTED_ALLOWED = [
    "0BSD",
    "AFL-2.1",
    "AGPL-3.0-only",
    "AGPL-3.0-or-later",
    "Apache-2.0",
    "BlueOak-1.0.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "BSL-1.0",
    "CC-BY-4.0",
    "CC0-1.0",
    "GPL-2.0-or-later",
    "GPL-3.0-only",
    "GPL-3.0-or-later",
    "HPND",
    "ISC",
    "LGPL-2.0-or-later",
    "LGPL-2.1-only",
    "LGPL-2.1-or-later",
    "LGPL-3.0-only",
    "LGPL-3.0-or-later",
    "MIT",
    "MIT-0",
    "MIT-CMU",
    "MPL-2.0",
    "OFL-1.1",
    "PSF-2.0",
    "Python-2.0",
    "Unlicense",
    "Zlib",
]


def _policy() -> dict[str, Any]:
    data = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_policy_is_json() -> None:
    # JSON is valid YAML: dependency-review reads it as YAML, the scripts read it as JSON.
    assert isinstance(_policy(), dict)


# SPDX licence-list data used by rollup-license-plugin at build time. The CC-BY-3.0 data
# licence is deliberately not in allow-licenses: each package is excepted by purl and
# version, and the built web licence list must not contain it (see the web build test).
BUILD_TIME_ONLY = {
    "pkg:npm/spdx-exceptions@2.5.0": "CC-BY-3.0",
    "pkg:npm/spdx-expression-validate@2.0.0": "CC-BY-3.0 AND MIT",
}


def test_policy_contents() -> None:
    policy = _policy()
    allowed = policy["allow-licenses"]
    assert allowed == EXPECTED_ALLOWED
    assert "GPL-2.0-only" not in allowed
    assert "LGPL-2.0-only" not in allowed
    assert policy["fail-on-scopes"] == ["runtime", "unknown"]
    assert policy["license-check"] is True
    assert policy["vulnerability-check"] is False


def test_every_allowed_purl_has_reason() -> None:
    policy = _policy()
    purls = policy["allow-dependencies-licenses"]
    assert purls == ["pkg:npm/json-schema@0.4.0", *sorted(BUILD_TIME_ONLY)]
    exceptions = {normalise_purl(e["purl"]): e for e in policy["x-licence-exceptions"]}
    for purl in purls:
        assert exceptions[normalise_purl(purl)]["reason"].strip()


def test_exception_entries_are_complete() -> None:
    seen: set[str] = set()
    for entry in _policy()["x-licence-exceptions"]:
        assert (
            {"purl", "licence", "reason"}
            <= set(entry)
            <= {
                "purl",
                "licence",
                "reason",
                "reviewed_expression",
            }
        )
        assert entry["purl"].startswith("pkg:")
        assert entry["reason"].strip()
        key = normalise_purl(entry["purl"])
        assert key not in seen, f"duplicate exception {key}"
        seen.add(key)


def test_exception_licences_are_allowed() -> None:
    allowed = frozenset(_policy()["allow-licenses"])
    for entry in _policy()["x-licence-exceptions"]:
        if entry["purl"] in BUILD_TIME_ONLY:
            # Not shipped; judged by the dependency review only, never allowed globally.
            assert not expression_allowed(entry["licence"], allowed), entry
            assert BUILD_TIME_ONLY[entry["purl"]] == entry["licence"]
            continue
        assert expression_allowed(entry["licence"], allowed), entry
