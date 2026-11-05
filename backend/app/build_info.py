"""Project licence and the public source link of the running build (D20).

AGPL-3.0-or-later section 13 obliges a network service to offer the users the
source of the version they are talking to. ``/api/info`` is public, so
everything here is derived from build values only and never carries a secret.
"""

from __future__ import annotations

import re
from typing import Final
from urllib.parse import urlsplit

PROJECT_LICENSE: Final = "AGPL-3.0-or-later"
CANONICAL_REPO_URL: Final = "https://github.com/strausmann/label-printer-hub"

_SEMVER = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?")
_COMMIT = re.compile(r"[0-9a-f]{7,40}")


def public_repo_url(repo_url: str) -> str:
    """Return ``repo_url`` cleaned for public display, or the canonical URL.

    Only ``http``/``https`` URLs with a host, no user info, no query and no
    fragment are accepted; surrounding whitespace is stripped and embedded
    control characters are refused. A trailing ``/`` and ``.git`` are stripped.
    """
    repo_url = repo_url.strip()
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in repo_url):
        return CANONICAL_REPO_URL
    try:
        parts = urlsplit(repo_url)
        # Accessing .hostname / .port validates the authority (raises on junk).
        host = parts.hostname
        _ = parts.port
    except ValueError:
        return CANONICAL_REPO_URL
    if (
        parts.scheme not in ("http", "https")
        or not host
        or "@" in parts.netloc
        or parts.query
        or parts.fragment
    ):
        return CANONICAL_REPO_URL
    cleaned = repo_url.rstrip("/").removesuffix(".git").rstrip("/")
    return cleaned


def source_url(repo_url: str, version: str, revision: str) -> str:  # D20
    """Link to the exact source of this build.

    A release links its tag, any other build with a known commit links that
    commit, and anything else falls back to the repository root.
    """
    base = public_repo_url(repo_url)
    if _SEMVER.fullmatch(version) and not version.startswith("0.0.0-"):
        return f"{base}/tree/v{version}"
    if _COMMIT.fullmatch(revision):
        return f"{base}/tree/{revision}"
    return base
