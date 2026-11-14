# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Base-URL normalisation shared by the integration probes and clients.

Users paste the address of an integration the way they see it in the browser:
with or without a trailing slash, sometimes with the API root appended
(``/api``), sometimes with a sub-path because the app sits behind a reverse
proxy prefix. Everything that builds a URL from that setting goes through
:func:`base_url` / :func:`api_url`, so the rules live in one place.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def base_url(raw: str, *, strip_api: bool = False) -> str:
    """Return ``scheme://host[:port][/sub/path]`` without trailing slash.

    Query and fragment are dropped. With ``strip_api`` a trailing ``/api``
    path segment is removed too (only that exact segment, so ``/apiary`` and
    ``/my/api/app`` are left alone). The sub-path is otherwise preserved.
    """
    parts = urlsplit(raw.strip())
    path = parts.path.rstrip("/")
    if strip_api and path.rsplit("/", 1)[-1] == "api":
        path = path[: -len("api")].rstrip("/")
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def api_url(raw: str, path: str, *, strip_api: bool = False) -> str:
    """Join the normalised base URL with an absolute API ``path`` (may carry a query)."""
    return base_url(raw, strip_api=strip_api) + path
