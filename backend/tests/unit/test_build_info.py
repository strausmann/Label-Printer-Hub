# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Licence constant and the source link of the running build (D20)."""

from __future__ import annotations

import pytest
from app.build_info import CANONICAL_REPO_URL, PROJECT_LICENSE, public_repo_url, source_url

R = CANONICAL_REPO_URL
SHA = "0123456789abcdef0123456789abcdef01234567"


def test_project_license() -> None:
    assert PROJECT_LICENSE == "AGPL-3.0-or-later"


@pytest.mark.parametrize(
    ("repo_url", "version", "revision", "expected"),
    [
        (R, "1.1.0", SHA, f"{R}/tree/v1.1.0"),
        (R, "1.1.0-rc.1", SHA, f"{R}/tree/v1.1.0-rc.1"),
        (R, "dev", SHA, f"{R}/tree/{SHA}"),
        (R, "feat-sheets", SHA, f"{R}/tree/{SHA}"),
        (R, "0.0.0-dev", "unknown", R),
        (R, "0.0.0-dev", SHA, f"{R}/tree/{SHA}"),
        (
            "https://example.invalid/fork.git/",
            "1.1.0",
            SHA,
            "https://example.invalid/fork/tree/v1.1.0",
        ),
        ("javascript:alert(1)", "1.1.0", SHA, f"{R}/tree/v1.1.0"),
        ("https://token@example.invalid/fork", "1.1.0", SHA, f"{R}/tree/v1.1.0"),
        ("", "dev", "unknown", R),
        (R, "1.1.0\n", SHA, f"{R}/tree/{SHA}"),
        (R, "dev", SHA + "\n", R),
        (R, "\u0661.\u0662.\u0663", SHA, f"{R}/tree/{SHA}"),  # Arabic-Indic digits
        (R, "dev", "\uff11\uff12\uff13\uff14\uff15\uff16\uff17", R),  # full-width digits
    ],
)
def test_source_url(repo_url: str, version: str, revision: str, expected: str) -> None:
    assert source_url(repo_url, version, revision) == expected


@pytest.mark.parametrize(
    ("repo_url", "expected"),
    [
        (R, R),
        (f"{R}/", R),
        (f"{R}.git", R),
        ("https://example.invalid/fork.git/", "https://example.invalid/fork"),
        ("http://example.invalid/fork", "http://example.invalid/fork"),
        ("javascript:alert(1)", R),
        ("ftp://example.invalid/fork", R),
        ("https://token@example.invalid/fork", R),
        ("https://user:pw@example.invalid/fork", R),
        ("https://example.invalid/fork?x=1", R),
        ("https://example.invalid/fork#frag", R),
        ("https:///nohost", R),
        ("", R),
        ("https://example.invalid/fork\n", "https://example.invalid/fork"),
        ("  https://example.invalid/fork  ", "https://example.invalid/fork"),
        ("https://example.invalid/fo\trk", R),
        ("https://example.invalid/fork\r\nX: y", R),
    ],
)
def test_public_repo_url_strips_and_rejects(repo_url: str, expected: str) -> None:
    assert public_repo_url(repo_url) == expected
