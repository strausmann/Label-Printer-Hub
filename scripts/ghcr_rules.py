#!/usr/bin/env python3
"""GHCR keep rule and preview tag logic for the Label Printer Hub backend image.

Used by .github/workflows/ghcr-cleanup.yml and .github/workflows/preview-image.yml
so that the workflows and the tests share one implementation.

CLI (tags are read from stdin, one per line):

    python3 scripts/ghcr_rules.py fetch-tags            # env: ACTOR, GHCR_TOKEN, IMAGE_PATH
    python3 scripts/ghcr_rules.py keep-regex
    python3 scripts/ghcr_rules.py next-preview <version-or-milestone>

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
from collections.abc import Callable
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

# A package that has never been pushed answers the tag list with one of these.
MISSING_PACKAGE_STATUSES = frozenset({403, 404})

Opener = Callable[[urllib.request.Request], Any]


# The cleanup action rejects exclude-tags longer than this (validateUserRegex).
MAX_REGEX_LENGTH = 1000


def keep_regex(tags: list[str]) -> str:
    """Return the exclude-tags regex: base rule plus every open preview.

    A preview x.y.z-rc.N is open while the release x.y.z is not among the tags.
    Previews are matched per open version (``x\\.y\\.z-rc\\.[0-9]+``), not per
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
    suffix = "".join(f"|{re.escape(v)}-rc\\.[0-9]+" for v in sorted(open_versions))
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


def fetch_tags(
    image: str, actor: str, token: str, opener: Opener = urllib.request.urlopen
) -> list[str]:
    """Read the tag list of ``image`` from ghcr.io.

    A package that does not exist yet (first preview of a new image) answers
    403 or 404: that is an empty tag list. Every other error is raised.
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
    except urllib.error.HTTPError as err:
        if err.code in MISSING_PACKAGE_STATUSES:
            return []
        raise
    return list(payload.get("tags") or [])


def _read_tags(stream: Any) -> list[str]:
    return [line.strip() for line in stream.read().splitlines() if line.strip()]


def main(argv: list[str], stdin: Any = None, stdout: Any = None) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    if len(argv) >= 1 and argv[0] == "fetch-tags" and len(argv) == 1:
        image = os.environ["IMAGE_PATH"].lower()
        tags = fetch_tags(image, os.environ["ACTOR"], os.environ["GHCR_TOKEN"])
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
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
