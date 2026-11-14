#!/usr/bin/env python3
"""Keep rule and preview tag logic for the Labelyard image on GHCR and Docker Hub.

Used by .github/workflows/registry-cleanup.yml and .github/workflows/preview-image.yml
so that the workflows and the tests share one implementation. Both registries
follow the same rule: keep_regex() for GHCR (the cleanup action takes a regex),
select_deletions() for Docker Hub (a list of tags), which agree by construction.

CLI (tags are read from stdin, one per line):

    python3 scripts/ghcr_rules.py fetch-tags            # env: ACTOR, GHCR_TOKEN, IMAGE_PATH
    python3 scripts/ghcr_rules.py keep-regex
    python3 scripts/ghcr_rules.py next-preview <version-or-milestone>
    python3 scripts/ghcr_rules.py released               # the x.y.z tags among stdin
    python3 scripts/ghcr_rules.py select-deletions --released <file>
    python3 scripts/ghcr_rules.py dockerhub-tags        # env: DOCKERHUB_USERNAME, DOCKERHUB_ADMIN_TOKEN, HUB_REPOSITORY
    python3 scripts/ghcr_rules.py dockerhub-delete      # same env; deletes the tags on stdin

Standard library only.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from typing import Any

# dev, latest, releases >= 1.4.0 with their floating tags (x.y and x).
#
# The pattern is kept flat on purpose: the cleanup action validates
# exclude-tags with safe-regex2, which rejects a repetition nested in another
# one (`(\.(0|[1-9][0-9]*))?`, `(...){0,2}`). Optional parts are therefore
# spelled out as alternatives. Equivalence with the nested form is tested.
_MINOR = r"[1-9][0-9]+"  # >= 10
_PATCH = r"(0|[1-9][0-9]*)"
_MAJOR = r"([2-9]|[1-9][0-9]+)"  # >= 2
_MINOR_FROM_4 = rf"1\.([4-9]|{_MINOR})"
BASE_KEEP = "|".join(
    [
        "dev",
        "latest",
        "1",
        _MINOR_FROM_4,
        rf"{_MINOR_FROM_4}\.{_PATCH}",
        _MAJOR,
        rf"{_MAJOR}\.{_PATCH}",
        rf"{_MAJOR}\.{_PATCH}\.{_PATCH}",
    ]
)

_NUM = r"(?:0|[1-9][0-9]*)"
_RELEASE = re.compile(rf"^({_NUM})\.({_NUM})\.({_NUM})$")
_PREVIEW = re.compile(rf"^(({_NUM})\.({_NUM})\.({_NUM}))-rc\.([0-9]+)$")
_PATCH_MILESTONE = re.compile(rf"^({_NUM})\.({_NUM})\.x$")
# Tags the retention rule knows. Anything else is foreign: GHCR's cleanup
# action deletes it (every tag is a candidate there), the Docker Hub job only
# reports it and leaves the decision to a maintainer.
_KNOWN = re.compile(rf"^(dev|latest|{_NUM}|{_NUM}\.{_NUM}|{_NUM}\.{_NUM}\.{_NUM}(-rc\.[0-9]+)?)$")
# A Docker tag (the registry's own grammar); used before a tag goes into a URL.
_DOCKER_TAG = re.compile(r"\A[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\Z")

DOCKERHUB_API = "https://hub.docker.com/v2"

# A package that has never been pushed answers the tag list with one of these.
MISSING_PACKAGE_STATUSES = frozenset({403, 404})

Opener = Callable[[urllib.request.Request], Any]


# The cleanup action rejects exclude-tags longer than this (validateUserRegex).
MAX_REGEX_LENGTH = 1000


def keep_regex(tags: list[str]) -> str:
    """Return the exclude-tags regex: base rule plus every open preview.

    A preview x.y.z-rc.N is open while the release x.y.z is not among the tags.
    Previews are matched per open version (``(x.y.z|...)-rc.N`` with one shared suffix), not per
    tag, so the pattern grows with the number of open versions, not with the
    number of preview builds. Raises ValueError if it still exceeds the length
    the cleanup action accepts, so the job fails here with a clear message.
    """
    present = set(tags)
    open_versions: list[str] = []
    for tag in tags:
        match = _PREVIEW.match(tag)
        if match is None or match.group(1) in present or match.group(1) in open_versions:
            continue
        open_versions.append(match.group(1))
    # One shared "-rc.N" suffix: the validator caps the number of repetitions
    # (25), so a repetition per open version would fail after a few of them.
    suffix = ""
    if open_versions:
        alternatives = "|".join(re.escape(v) for v in sorted(open_versions))
        suffix = f"|({alternatives})-rc\\.[0-9]+"
    pattern = f"^({BASE_KEEP}{suffix})$"
    if len(pattern) > MAX_REGEX_LENGTH:
        raise ValueError(
            f"keep rule is {len(pattern)} characters, the cleanup action accepts {MAX_REGEX_LENGTH}; "
            f"{len(open_versions)} versions have open previews"
        )
    return pattern


def next_preview_tag(version_or_milestone: str, tags: list[str], released: list[str]) -> str:
    """Return the next free preview tag.

    ``1.6.0``  -> ``1.6.0-rc.<n>``
    ``1.5.x``  -> ``1.5.<next free patch>-rc.<n>``

    Raises ValueError for a malformed input or a version that is already released.
    """
    patch_milestone = _PATCH_MILESTONE.match(version_or_milestone)
    if patch_milestone:
        major, minor = patch_milestone.group(1), patch_milestone.group(2)
        patches = [
            int(m.group(3))
            for r in released
            if (m := _RELEASE.match(r)) and m.group(1) == major and m.group(2) == minor
        ]
        version = f"{major}.{minor}.{max(patches) + 1 if patches else 0}"
    elif _RELEASE.match(version_or_milestone):
        version = version_or_milestone
    else:
        raise ValueError(f"version must be x.y.z or x.y.x, got '{version_or_milestone}'")
    if version in released:
        raise ValueError(f"{version} is already released; a preview must lead to an unreleased version")
    numbers = [int(m.group(5)) for t in tags if (m := _PREVIEW.match(t)) and m.group(1) == version]
    return f"{version}-rc.{max(numbers, default=0) + 1}"


def released_versions(tags: list[str]) -> list[str]:
    """The exact x.y.z tags among ``tags``."""
    return [t for t in tags if _RELEASE.match(t)]


def foreign_tags(tags: Iterable[str]) -> list[str]:
    """Tags the retention rule does not know (branch slugs, CI tags, ...)."""
    return list(dict.fromkeys(t for t in tags if not _KNOWN.match(t)))


def select_deletions(tags: Iterable[str], released: set[str]) -> list[str]:
    """Return the tags to delete, in input order, by the same rule as keep_regex().

    ``released`` are the x.y.z versions that exist (on either registry); a
    preview x.y.z-rc.N whose version is released is closed and deleted. Foreign
    tags are never returned (see foreign_tags()).
    """
    tags = list(dict.fromkeys(tags))
    rule = re.compile(keep_regex(tags + sorted(released)))
    return [t for t in tags if _KNOWN.match(t) and not rule.match(t)]


def fetch_tags(
    image: str, actor: str, token: str, opener: Opener = urllib.request.urlopen
) -> list[str]:
    """Read the tag list of ``image`` from ghcr.io.

    A package that does not exist yet (first preview of a new image) answers
    403 or 404: that is an empty tag list. Every other error is raised, and so
    is a paginated answer (``Link: ...; rel="next"``): a partial list would
    silently shrink the keep rule.
    Credentials are sent in-process and never appear in a command line.
    """
    scope = urllib.parse.quote(f"repository:{image}:pull", safe=":/")
    basic = base64.b64encode(f"{actor}:{token}".encode()).decode()
    token_request = urllib.request.Request(
        f"https://ghcr.io/token?scope={scope}", headers={"Authorization": f"Basic {basic}"}
    )
    with opener(token_request) as response:
        registry_token = json.load(response)["token"]
    list_request = urllib.request.Request(
        f"https://ghcr.io/v2/{image}/tags/list?n=10000",
        headers={"Authorization": f"Bearer {registry_token}"},
    )
    try:
        with opener(list_request) as response:
            payload = json.load(response)
            link = getattr(response, "headers", None) and response.headers.get("Link")
    except urllib.error.HTTPError as err:
        if err.code in MISSING_PACKAGE_STATUSES:
            return []
        raise
    if link and re.search(r'rel="?next"?', link):
        raise RuntimeError("tag list is paginated (Link rel=next); refusing to use a partial list")
    return list(payload.get("tags") or [])


def _hub_request(
    method: str, url: str, opener: Opener, token: str | None = None, body: dict[str, str] | None = None
) -> tuple[int, Any]:
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    with opener(request) as response:
        raw = response.read()
        return getattr(response, "status", 200), (json.loads(raw) if raw else None)


def dockerhub_token(username: str, secret: str, opener: Opener = urllib.request.urlopen) -> str:
    """Exchange a Docker Hub personal access token for a bearer token.

    The secret travels in the request body, never in a URL or a command line.
    """
    _, payload = _hub_request(
        "POST", f"{DOCKERHUB_API}/auth/token", opener, body={"identifier": username, "secret": secret}
    )
    return str(payload["access_token"])


def fetch_dockerhub_tags(
    namespace: str, repository: str, token: str, opener: Opener = urllib.request.urlopen
) -> list[str]:
    """Read every tag of ``namespace/repository`` (follows ``next``).

    A repository without tags (or not created yet) answers 404: an empty list,
    as for GHCR. Every other error is raised.
    """
    url: str | None = f"{DOCKERHUB_API}/namespaces/{namespace}/repositories/{repository}/tags?page_size=100"
    tags: list[str] = []
    while url:
        if not url.startswith(f"{DOCKERHUB_API}/"):
            raise RuntimeError(f"refusing to follow a next page outside {DOCKERHUB_API}")
        try:
            _, page = _hub_request("GET", url, opener, token=token)
        except urllib.error.HTTPError as err:
            if err.code == 404 and not tags:
                return []
            raise
        tags += [str(item["name"]) for item in page.get("results") or []]
        url = page.get("next")
    return tags


def delete_dockerhub_tag(
    namespace: str, repository: str, tag: str, token: str, opener: Opener = urllib.request.urlopen
) -> None:
    """Delete one tag. A 404 means it is gone already; every other error is raised.

    The endpoint is not in Docker Hub's current API reference; it was confirmed
    in the Labelyard Task 4 spike (204, tag gone from the list afterwards).
    """
    if not _DOCKER_TAG.match(tag):
        raise ValueError(f"not a tag: {tag!r}")
    url = f"{DOCKERHUB_API}/repositories/{namespace}/{repository}/tags/{tag}/"
    try:
        _hub_request("DELETE", url, opener, token=token)
    except urllib.error.HTTPError as err:
        if err.code != 404:
            raise


def _hub_env() -> tuple[str, str, str]:
    username = os.environ["DOCKERHUB_USERNAME"]
    token = dockerhub_token(username, os.environ["DOCKERHUB_ADMIN_TOKEN"])
    return username.lower(), os.environ["HUB_REPOSITORY"], token


def _read_tags(stream: Any) -> list[str]:
    return [line.strip() for line in stream.read().splitlines() if line.strip()]


def main(argv: list[str], stdin: Any = None, stdout: Any = None) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    if argv[:1] == ["fetch-tags"] and argv[1:] in ([], ["--on-empty=allow"], ["--on-empty=warn"], ["--on-empty=fail"]):
        mode = argv[1].split("=")[1] if argv[1:] else "allow"
        image = os.environ["IMAGE_PATH"].lower()
        tags = fetch_tags(image, os.environ["ACTOR"], os.environ["GHCR_TOKEN"])
        if not tags and mode != "allow":
            # An existing package with a falsely empty list (403/404) would make
            # the cleanup treat every open preview as deletable.
            level = "error" if mode == "fail" else "warning"
            print(f"::{level}::tag list of {image} is empty; open previews cannot be protected", file=sys.stderr)
            if mode == "fail":
                return 1
        stdout.write("".join(f"{t}\n" for t in tags))
        return 0
    if argv == ["keep-regex"]:
        stdout.write(keep_regex(_read_tags(stdin)) + "\n")
        return 0
    if len(argv) == 2 and argv[0] == "next-preview":
        tags = _read_tags(stdin)
        try:
            stdout.write(next_preview_tag(argv[1], tags, released_versions(tags)) + "\n")
        except ValueError as err:
            print(f"::error::{err}", file=sys.stderr)
            return 1
        return 0
    if argv == ["released"]:
        stdout.write("".join(f"{t}\n" for t in dict.fromkeys(released_versions(_read_tags(stdin)))))
        return 0
    if len(argv) == 3 and argv[:2] == ["select-deletions", "--released"]:
        with open(argv[2], encoding="utf-8") as released_file:
            released = set(_read_tags(released_file))
        tags = _read_tags(stdin)
        for tag in foreign_tags(tags):
            print(f"::notice::foreign tag, not deleted: {tag}", file=sys.stderr)
        stdout.write("".join(f"{t}\n" for t in select_deletions(tags, released)))
        return 0
    if argv == ["dockerhub-tags"]:
        namespace, repository, token = _hub_env()
        stdout.write("".join(f"{t}\n" for t in fetch_dockerhub_tags(namespace, repository, token)))
        return 0
    if argv == ["dockerhub-delete"]:
        tags = _read_tags(stdin)
        if tags:
            namespace, repository, token = _hub_env()
            for tag in tags:
                delete_dockerhub_tag(namespace, repository, tag, token)
                stdout.write(f"deleted {tag}\n")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
