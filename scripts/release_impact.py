#!/usr/bin/env python3
"""Release impact of pull requests and the release guard.

The project releases from ``main`` only (semantic-release, ``.releaserc.json``).
Minor and major versions come from a milestone integration branch
``milestone/x.y.z`` that is merged into ``main`` as one pull request; ``main``
itself only takes patch-level or non-releasing changes. See CONTRIBUTING.md,
section "Milestones, branches and releases", and ADR 0021.

Two modes:

``check``
    Runs on every pull request to ``main`` (``release-impact.yml``). Classifies
    the PR title and every commit of the PR exactly like semantic-release's
    commit analyzer does with the rules in ``.releaserc.json``, then

    * for a head branch that is not ``milestone/*``: fails on any minor or
      major change;
    * for ``milestone/x.y.z``: fails unless the last release on ``main`` bumped
      by the highest impact is ``x.y.z`` and a GitHub milestone titled
      ``x.y.z`` is open.

``guard``
    Runs inside semantic-release as the ``verifyRelease`` step
    (``@semantic-release/exec`` ``verifyReleaseCmd``), before anything is
    written or published. The computed version must be the next patch of the
    last release or the title of an open GitHub milestone. Otherwise the
    release is aborted and an issue "release blocked: computed <v>" is opened.

Only the Python standard library is used. Text that comes from commits or PR
titles is untrusted: it never reaches a shell, and every line printed starts
with a fixed prefix so it cannot be read as a workflow command.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
RELEASERC = REPO_ROOT / ".releaserc.json"

# Order matters: lower index = higher release (semantic-release RELEASE_TYPES).
RELEASE_TYPES = ["major", "premajor", "minor", "preminor", "patch", "prepatch", "prerelease"]

# @semantic-release/commit-analyzer 13 lib/default-release-rules.js. They are
# applied to a commit only when none of the custom rules matched it.
DEFAULT_RELEASE_RULES: list[dict[str, Any]] = [
    {"breaking": True, "release": "major"},
    {"revert": True, "release": "patch"},
    {"type": "feat", "release": "minor"},
    {"type": "fix", "release": "patch"},
    {"type": "perf", "release": "patch"},
    {"emoji": ":racehorse:", "release": "patch"},
    {"emoji": ":bug:", "release": "patch"},
    {"emoji": ":penguin:", "release": "patch"},
    {"emoji": ":apple:", "release": "patch"},
    {"emoji": ":checkered_flag:", "release": "patch"},
    {"tag": "BUGFIX", "release": "patch"},
    {"tag": "FEATURE", "release": "minor"},
    {"tag": "SECURITY", "release": "patch"},
    {"tag": "Breaking", "release": "major"},
    {"tag": "Fix", "release": "patch"},
    {"tag": "Update", "release": "minor"},
    {"tag": "New", "release": "minor"},
    {"component": "perf", "release": "patch"},
    {"component": "deps", "release": "patch"},
    {"type": "FEAT", "release": "minor"},
    {"type": "FIX", "release": "patch"},
]

# Parser options of the conventionalcommits preset (conventional-changelog-
# conventionalcommits parserOpts.js) and conventional-commits-parser's default
# notes pattern. JavaScript's \w is ASCII-only, hence re.ASCII.
HEADER_RE = re.compile(r"^(\w*)(?:\((.*)\))?!?: (.*)$", re.ASCII)
BREAKING_HEADER_RE = re.compile(r"^(\w*)(?:\((.*)\))?!: (.*)$", re.ASCII)
NOTES_RE = re.compile(r"^[\s|*]*(BREAKING CHANGE|BREAKING-CHANGE)[:\s]+(.*)", re.IGNORECASE)
REVERT_RE = re.compile(r'^(?:Revert|revert:)\s"?([\s\S]+?)"?\s*This reverts commit (\w*)\.', re.IGNORECASE)

VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
TAG_RE = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
MILESTONE_BRANCH_RE = re.compile(r"^milestone/((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))$")


# --------------------------------------------------------------------------- parsing


@dataclass
class Commit:
    """A commit message parsed the way conventional-commits-parser does it."""

    message: str
    hash: str = ""
    header: str = ""
    type: str | None = None
    scope: str | None = None
    subject: str | None = None
    notes: list[str] = field(default_factory=list)
    revert: dict[str, str] | None = None

    def as_match_object(self) -> dict[str, Any]:
        return {"type": self.type, "scope": self.scope, "subject": self.subject}


def parse_commit(message: str, sha: str = "") -> Commit:
    text = message.replace("\r\n", "\n").strip("\n")
    lines = text.split("\n")
    header = lines[0] if lines else ""
    commit = Commit(message=message, hash=sha, header=header)
    match = HEADER_RE.match(header)
    if match:
        commit.type, commit.scope, commit.subject = match.group(1), match.group(2), match.group(3)
    for line in lines[1:]:
        note = NOTES_RE.match(line)
        if note:
            commit.notes.append(note.group(2))
    if not commit.notes and BREAKING_HEADER_RE.match(header):
        commit.notes.append(BREAKING_HEADER_RE.match(header).group(3))  # type: ignore[union-attr]
    revert = REVERT_RE.match(text)
    if revert:
        commit.revert = {"header": revert.group(1), "hash": revert.group(2)}
    return commit


def filter_reverted(commits: list[Commit]) -> list[Commit]:
    """Drop revert commits together with the commit they revert (conventional-commits-filter)."""
    dropped: set[int] = set()
    for i, rev in enumerate(commits):
        if rev.revert is None or i in dropped:
            continue
        for j, target in enumerate(commits):
            if j == i or j in dropped:
                continue
            if (
                target.header == rev.revert["header"]
                and rev.revert["hash"]
                and target.hash
                and target.hash.startswith(rev.revert["hash"])
            ):
                dropped.update({i, j})
                break
    return [c for k, c in enumerate(commits) if k not in dropped]


# --------------------------------------------------------------------------- analysis


def load_release_rules(path: Path = RELEASERC) -> list[dict[str, Any]]:
    config = json.loads(path.read_text(encoding="utf-8"))
    for plugin in config.get("plugins", []):
        if isinstance(plugin, list) and plugin[0] == "@semantic-release/commit-analyzer":
            rules = plugin[1].get("releaseRules") if len(plugin) > 1 else None
            return list(rules or [])
    return []


def _higher(current: Any, candidate: Any) -> bool:
    """compare-release-types.js: !current || index(candidate) < index(current)."""
    if not current:
        return True

    def index(value: Any) -> int:
        return RELEASE_TYPES.index(value) if value in RELEASE_TYPES else -1

    return index(candidate) < index(current)


def _rule_matches(rule: dict[str, Any], commit: Commit) -> bool:
    if rule.get("breaking") and not commit.notes:
        return False
    if rule.get("revert") and not commit.revert:
        return False
    obj = commit.as_match_object()
    for key, expected in rule.items():
        if key in ("breaking", "revert", "release"):
            continue
        actual = obj.get(key)
        if isinstance(expected, str) and isinstance(actual, str):
            if not fnmatch.fnmatchcase(actual, expected):
                return False
        elif actual != expected:
            return False
    return True


def _analyze(rules: Iterable[dict[str, Any]], commit: Commit) -> Any:
    """analyze-commit.js. Returns None (no rule matched), False or a release type."""
    release: Any = None
    for rule in rules:
        if not _rule_matches(rule, commit):
            continue
        if _higher(release, rule.get("release")):
            release = rule.get("release")
            if release == RELEASE_TYPES[0]:
                break
    return release


def commit_impact(commit: Commit, rules: list[dict[str, Any]]) -> str | None:
    """Release type of one commit, or None when it does not release."""
    if not commit.message.strip():
        return None
    release = _analyze(rules, commit) if rules else None
    if release is None:
        release = _analyze(DEFAULT_RELEASE_RULES, commit)
    return release or None


def max_impact(impacts: Iterable[str | None]) -> str | None:
    best: str | None = None
    for impact in impacts:
        if impact and _higher(best, impact):
            best = impact
    return best


# --------------------------------------------------------------------------- versions


def parse_version(value: str) -> tuple[int, int, int]:
    match = VERSION_RE.match(value)
    if not match:
        raise ValueError(f"not a release version: {value!r}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def bump(last: str | None, impact: str | None) -> str | None:
    """Next version as semantic-release computes it; the first release is 1.0.0."""
    if impact is None:
        return None
    if not last:
        return "1.0.0"
    major, minor, patch = parse_version(last)
    if impact == "major":
        return f"{major + 1}.0.0"
    if impact == "minor":
        return f"{major}.{minor + 1}.0"
    if impact == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"unsupported release type {impact!r}")


def last_release_from_tags(tags: Iterable[str]) -> str | None:
    versions = []
    for tag in tags:
        match = TAG_RE.match(tag.strip())
        if match:
            versions.append(tuple(int(g) for g in match.groups()))
    if not versions:
        return None
    return "{}.{}.{}".format(*max(versions))


# --------------------------------------------------------------------------- git + API


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True).stdout


def git_last_release(ref: str) -> str | None:
    return last_release_from_tags(git("tag", "--merged", ref, "--list", "v*").splitlines())


def git_commits(rev_range: str) -> list[Commit]:
    out = git("log", "--format=%H%x1f%B%x1e", rev_range)
    commits = []
    for record in out.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        sha, _, body = record.partition("\x1f")
        commits.append(parse_commit(body, sha))
    return commits


HttpGet = Callable[[str], Any]


def _request(method: str, url: str, body: dict[str, Any] | None = None) -> Any:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read() or b"null")


def api_url(path: str, **query: str | int) -> str:
    base = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    return f"{base}{path}" + (f"?{urllib.parse.urlencode(query)}" if query else "")


def open_milestones(repo: str, get: HttpGet | None = None) -> set[str]:
    get = get or (lambda url: _request("GET", url))  # looked up at call time
    titles: set[str] = set()
    page = 1
    while True:
        batch = get(api_url(f"/repos/{repo}/milestones", state="open", per_page=100, page=page))
        if not batch:
            return titles
        titles.update(str(m.get("title", "")).strip() for m in batch)
        if len(batch) < 100:
            return titles
        page += 1


# --------------------------------------------------------------------------- output


def _clean(text: str) -> str:
    return " ".join(text.split())


def annotation(kind: str, message: str) -> str:
    """A workflow command whose payload is escaped (actions/toolkit escapeData)."""
    data = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return f"::{kind}::{data}"


def md_cell(text: str) -> str:
    return _clean(text).replace("\\", "\\\\").replace("|", "\\|").replace("`", "'")


@dataclass
class Entry:
    label: str
    subject: str
    impact: str | None


def summary_table(entries: list[Entry]) -> str:
    rows = ["| Commit | Message | Impact |", "|---|---|---|"]
    for e in entries:
        rows.append(f"| {md_cell(e.label)} | {md_cell(e.subject)} | {e.impact or 'none'} |")
    return "\n".join(rows) + "\n"


# --------------------------------------------------------------------------- check


@dataclass
class CheckResult:
    ok: bool
    errors: list[str]
    entries: list[Entry]
    last_release: str | None
    computed: str | None = None
    milestone: str | None = None


def evaluate_pr(
    *,
    title: str,
    commits: list[Commit],
    head_ref: str,
    same_repo: bool,
    last_release: str | None,
    base_impact: str | None,
    milestones: Callable[[], set[str]],
    rules: list[dict[str, Any]],
) -> CheckResult:
    """Decide whether a pull request to main respects the milestone model."""
    entries = [Entry("PR title", title, commit_impact(parse_commit(title), rules))]
    for c in filter_reverted(commits):
        entries.append(Entry(c.hash[:7] or "commit", c.header, commit_impact(c, rules)))
    pr_impact = max_impact(e.impact for e in entries)
    errors: list[str] = []

    branch = MILESTONE_BRANCH_RE.match(head_ref) if same_repo else None
    if branch is None:
        for e in entries:
            if e.impact in ("minor", "major"):
                target = bump(last_release, e.impact)
                errors.append(
                    f"{e.label} '{_clean(e.subject)}' is a {e.impact} change. Only patch or "
                    f"non-releasing changes may go to main directly; target the milestone "
                    f"branch milestone/{target} instead."
                )
        return CheckResult(not errors, errors, entries, last_release)

    expected = branch.group(1)
    total = max_impact([pr_impact, base_impact])
    computed = bump(last_release, total)
    result = CheckResult(False, errors, entries, last_release, computed, expected)
    if computed is None:
        errors.append(
            f"milestone/{expected} contains no releasable change (feat, fix, perf or breaking); "
            f"merging it would not release {expected}."
        )
    elif computed != expected:
        errors.append(
            f"the commits compute version {computed} (last release "
            f"{last_release or 'none'} + {total}), but the branch is milestone/{expected}. "
            f"Rename the branch and milestone to {computed} or change the commits."
        )
    if expected not in milestones():
        errors.append(f"no open GitHub milestone titled '{expected}' exists.")
    result.ok = not errors
    return result


def run_check(args: argparse.Namespace) -> int:
    rules = load_release_rules()
    last = git_last_release(args.base_sha)
    commits = git_commits(f"{args.base_sha}..{args.head_sha}")
    base_impact = None
    if MILESTONE_BRANCH_RE.match(args.head_ref):
        base_range = f"v{last}..{args.base_sha}" if last else args.base_sha
        base_impact = max_impact(commit_impact(c, rules) for c in filter_reverted(git_commits(base_range)))
    result = evaluate_pr(
        title=args.title,
        commits=commits,
        head_ref=args.head_ref,
        same_repo=args.head_repo == args.base_repo,
        last_release=last,
        base_impact=base_impact,
        milestones=lambda: open_milestones(args.repo),
        rules=rules,
    )
    lines = [
        "## Release impact",
        "",
        f"Last release on main: `{result.last_release or 'none'}`",
    ]
    if result.milestone:
        lines.append(f"Milestone branch: `{result.milestone}`, computed version: `{result.computed or 'none'}`")
    lines += ["", summary_table(result.entries)]
    if result.errors:
        lines += ["**Failed:**", ""] + [f"- {md_cell(e)}" for e in result.errors]
    else:
        lines.append("**Passed.**")
    text = "\n".join(lines) + "\n"
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text)
    for row in result.entries:
        print(f"  - {row.label}: {row.impact or 'none'}: {_clean(row.subject)}")
    for err in result.errors:
        print(annotation("error", err))
    print(f"  result: {'pass' if result.ok else 'fail'}")
    return 0 if result.ok else 1


# --------------------------------------------------------------------------- guard


def guard_allows(next_version: str, last: str | None, milestones: Callable[[], set[str]]) -> bool:
    parse_version(next_version)
    if last and next_version == bump(last, "patch"):
        return True
    return next_version in milestones()


def open_block_issue(repo: str, version: str, last: str | None, request: Callable[..., Any] | None = None) -> None:
    request = request or _request
    title = f"release blocked: computed {version}"
    for issue in request("GET", api_url(f"/repos/{repo}/issues", state="open", per_page=100)) or []:
        if issue.get("title") == title and "pull_request" not in issue:
            print(f"  issue already open: #{issue.get('number')}")
            return
    body = (
        f"The release run computed version `{version}` (last release `{last or 'none'}`). "
        "That is neither the next patch release nor the title of an open milestone, so the "
        "release guard stopped semantic-release before anything was tagged or published.\n\n"
        "Minor and major versions must come from a `milestone/x.y.0` branch merged with a merge "
        "commit while the GitHub milestone `x.y.0` is open. Find the commit on `main` that "
        "raised the version (a `feat`, `!` or `BREAKING CHANGE` commit pushed or squashed "
        "outside a milestone), then either revert it or open the milestone that matches.\n\n"
        'See CONTRIBUTING.md, section "Milestones, branches and releases".'
    )
    created = request("POST", api_url(f"/repos/{repo}/issues"), {"title": title, "body": body})
    print(f"  opened issue #{(created or {}).get('number')}")


def run_guard(args: argparse.Namespace) -> int:
    last = args.last or None
    try:
        allowed = guard_allows(args.next, last, lambda: open_milestones(args.repo))
    except (ValueError, urllib.error.URLError) as exc:
        print(annotation("error", f"release guard could not decide, refusing to release: {exc}"))
        return 1
    if allowed:
        print(f"  release guard: {args.next} allowed (last release {last or 'none'})")
        return 0
    print(
        annotation(
            "error",
            f"release blocked: computed {args.next} (last {last or 'none'}) is neither the next "
            "patch nor an open milestone",
        )
    )
    if os.environ.get("DRY_RUN") == "true":
        print("  dry run: no issue opened")
    else:
        try:
            open_block_issue(args.repo, args.next, last)
        except urllib.error.URLError as exc:
            print(annotation("warning", f"could not open the blocking issue: {exc}"))
    return 1


# --------------------------------------------------------------------------- classify


def run_classify(args: argparse.Namespace) -> int:
    """Print the impact of every commit in a git range (for local checks)."""
    rules = load_release_rules()
    commits = filter_reverted(git_commits(args.range))
    for c in commits:
        print(f"  {c.hash[:7]} {commit_impact(c, rules) or 'none':5} {_clean(c.header)}")
    print(f"  total: {max_impact(commit_impact(c, rules) for c in commits) or 'none'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="mode", required=True)

    check = sub.add_parser("check", help="check a pull request to main")
    check.add_argument("--repo", required=True)
    check.add_argument("--title", required=True)
    check.add_argument("--head-ref", required=True)
    check.add_argument("--head-repo", required=True)
    check.add_argument("--base-repo", required=True)
    check.add_argument("--base-sha", required=True)
    check.add_argument("--head-sha", required=True)
    check.set_defaults(func=run_check)

    guard = sub.add_parser("guard", help="verify the version semantic-release computed")
    guard.add_argument("--repo", required=True)
    guard.add_argument("--next", required=True)
    guard.add_argument("--last", default="")
    guard.set_defaults(func=run_guard)

    classify = sub.add_parser("classify", help="print the impact of each commit in a git range")
    classify.add_argument("range")
    classify.set_defaults(func=run_classify)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
