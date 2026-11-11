"""Unit tests for scripts/release_impact.py.

Run with: python3 -m unittest discover -s scripts -p 'test_*.py' -v
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import release_impact as ri

RULES = ri.load_release_rules()


def impact(message: str) -> str | None:
    return ri.commit_impact(ri.parse_commit(message, "0123456789abcdef"), RULES)


def commits(*messages: str) -> list[ri.Commit]:
    return [ri.parse_commit(m, f"{i:040x}") for i, m in enumerate(messages, start=1)]


def milestones(*titles: str) -> Any:
    return lambda: set(titles)


class ReleaseRulesTest(unittest.TestCase):
    def test_rules_are_read_from_releaserc(self) -> None:
        types = {r.get("type"): r["release"] for r in RULES if "type" in r}
        self.assertEqual(types["feat"], "minor")
        self.assertEqual(types["fix"], "patch")
        self.assertIs(types["chore"], False)
        self.assertIn({"breaking": True, "release": "major"}, RULES)


TYPE_CASES: dict[str, str | None] = {
    "feat: add x": "minor",
    "feat(ui): add x": "minor",
    "fix: repair x": "patch",
    "fix(api): repair x (#12)": "patch",
    "perf: faster": "patch",
    "refactor: move": None,
    "docs: words": None,
    "chore: tidy": None,
    "ci: pipeline": None,
    "test: more": None,
    "style: format": None,
    "build: image": None,
    "chore(release): 1.4.1\n\n[skip ci]": None,
    "Merge pull request #7 from owner/milestone/1.5.0": None,
    "Merge branch 'main' into milestone/1.5.0": None,
    "update readme": None,
    "": None,
}
BREAKING_BANGS = ("feat!: x", "fix(api)!: x", "docs!: x", "chore(deps)!: x")
BREAKING_FOOTERS = (
    "BREAKING CHANGE: gone",
    "BREAKING-CHANGE: gone",
    "breaking change: gone",
    "* BREAKING CHANGE: gone",
)
NON_BREAKING_BODIES = (
    "chore: x\n\nThis is not a BREAKING CHANGE: inline",
    "chore: x\n\nBREAKING CHANGES: plural is not a keyword",
)
DEFAULT_RULE_CASES = (
    "FEAT: shout",
    'Revert "feat: a"\n\nThis reverts commit abc123.',
    "Feat: capitalised type matches no rule",
)


def sample_messages() -> list[str]:
    """Every commit message the impact tests use; scripts/release_dry_run.sh --all replays them."""
    footers = [f"fix: small\n\n{footer}" for footer in BREAKING_FOOTERS]
    messages = [*TYPE_CASES, *BREAKING_BANGS, *footers, *NON_BREAKING_BODIES, *DEFAULT_RULE_CASES]
    return list(dict.fromkeys(messages))


class CommitImpactTest(unittest.TestCase):
    def test_types(self) -> None:
        for message, expected in TYPE_CASES.items():
            with self.subTest(message=message):
                self.assertEqual(impact(message), expected)

    def test_breaking_bang_is_major_for_every_type(self) -> None:
        for message in BREAKING_BANGS:
            with self.subTest(message=message):
                self.assertEqual(impact(message), "major")

    def test_breaking_footers(self) -> None:
        for footer in BREAKING_FOOTERS:
            with self.subTest(footer=footer):
                self.assertEqual(impact(f"fix: small\n\n{footer}"), "major")

    def test_breaking_word_inside_a_sentence_is_not_a_footer(self) -> None:
        for message in NON_BREAKING_BODIES:
            with self.subTest(message=message):
                self.assertIsNone(impact(message))

    def test_default_rules_apply_when_no_custom_rule_matches(self) -> None:
        # commit-analyzer falls back to its default rules (uppercase JSHint types, reverts).
        shout, revert, capitalised = DEFAULT_RULE_CASES
        self.assertEqual(impact(shout), "minor")
        self.assertEqual(impact(revert), "patch")
        self.assertIsNone(impact(capitalised))

    def test_reverted_pair_is_dropped(self) -> None:
        original = ri.parse_commit("feat: a", "abc1234000")
        revert = ri.parse_commit('Revert "feat: a"\n\nThis reverts commit abc1234.', "fff0000")
        self.assertEqual(ri.filter_reverted([revert, original]), [])

    def test_max_impact(self) -> None:
        self.assertEqual(ri.max_impact([None, "patch", "minor", None]), "minor")
        self.assertEqual(ri.max_impact(["minor", "major", "patch"]), "major")
        self.assertIsNone(ri.max_impact([None, None]))


class VersionTest(unittest.TestCase):
    def test_bump(self) -> None:
        self.assertEqual(ri.bump("1.4.1", "patch"), "1.4.2")
        self.assertEqual(ri.bump("1.4.1", "minor"), "1.5.0")
        self.assertEqual(ri.bump("1.4.1", "major"), "2.0.0")
        self.assertIsNone(ri.bump("1.4.1", None))
        self.assertEqual(ri.bump(None, "patch"), "1.0.0")

    def test_last_release_ignores_prereleases_and_other_tags(self) -> None:
        tags = ["v1.2.0", "v1.10.0", "v1.4.1", "v2.0.0-rc.1", "release-9", "v1.9.9"]
        self.assertEqual(ri.last_release_from_tags(tags), "1.10.0")
        self.assertIsNone(ri.last_release_from_tags(["foo"]))


class EvaluatePrTest(unittest.TestCase):
    def evaluate(self, **kw: Any) -> ri.CheckResult:
        args: dict[str, Any] = {
            "title": "fix: x",
            "commits": [],
            "head_ref": "fix/x",
            "same_repo": True,
            "last_release": "1.4.1",
            "base_impact": None,
            "milestones": milestones("1.5.0"),
            "rules": RULES,
        }
        args.update(kw)
        return ri.evaluate_pr(**args)

    def test_fix_from_fix_branch_passes(self) -> None:
        self.assertTrue(self.evaluate(commits=commits("fix: a", "test: b")).ok)

    def test_non_releasing_pr_passes(self) -> None:
        self.assertTrue(self.evaluate(title="docs: a", commits=commits("docs: a")).ok)

    def test_feat_title_on_non_milestone_branch_fails(self) -> None:
        result = self.evaluate(title="feat: new", commits=commits("fix: a"), head_ref="feat/new")
        self.assertFalse(result.ok)
        self.assertIn("PR title", result.errors[0])
        self.assertIn("milestone/1.5.0", result.errors[0])

    def test_feat_commit_hidden_behind_fix_title_fails(self) -> None:
        # A merge commit keeps the commits, so they count even when the title is a fix.
        result = self.evaluate(title="fix: a", commits=commits("fix: a", "feat: sneaky"))
        self.assertFalse(result.ok)
        self.assertIn("feat: sneaky", result.errors[0])

    def test_breaking_change_on_non_milestone_branch_points_to_major_milestone(self) -> None:
        result = self.evaluate(commits=commits("fix: a\n\nBREAKING CHANGE: b"))
        self.assertFalse(result.ok)
        self.assertIn("milestone/2.0.0", result.errors[0])

    def test_milestone_branch_from_fork_is_not_a_milestone(self) -> None:
        result = self.evaluate(title="feat: a", head_ref="milestone/1.5.0", same_repo=False)
        self.assertFalse(result.ok)
        self.assertIsNone(result.milestone)

    def test_matching_milestone_passes(self) -> None:
        result = self.evaluate(
            title="feat: milestone 1.5.0",
            head_ref="milestone/1.5.0",
            commits=commits("feat(ui): a", "fix: b", "Merge branch 'main' into milestone/1.5.0"),
        )
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.computed, "1.5.0")

    def test_milestone_name_that_does_not_match_the_computed_version_fails(self) -> None:
        result = self.evaluate(
            title="feat: a", head_ref="milestone/1.6.0", commits=commits("feat: a"), milestones=milestones("1.6.0")
        )
        self.assertFalse(result.ok)
        self.assertIn("compute version 1.5.0", result.errors[0])
        self.assertIn("milestone/1.6.0", result.errors[0])

    def test_breaking_change_in_minor_milestone_fails(self) -> None:
        result = self.evaluate(title="feat: a", head_ref="milestone/1.5.0", commits=commits("feat!: a"))
        self.assertFalse(result.ok)
        self.assertEqual(result.computed, "2.0.0")

    def test_major_milestone_passes(self) -> None:
        result = self.evaluate(
            title="feat!: v2", head_ref="milestone/2.0.0", commits=commits("feat!: a"), milestones=milestones("2.0.0")
        )
        self.assertTrue(result.ok, result.errors)

    def test_milestone_without_open_github_milestone_fails(self) -> None:
        result = self.evaluate(
            title="feat: a", head_ref="milestone/1.5.0", commits=commits("feat: a"), milestones=milestones("1.6.0")
        )
        self.assertFalse(result.ok)
        self.assertIn("no open GitHub milestone titled '1.5.0'", result.errors[-1])

    def test_milestone_without_releasable_change_fails(self) -> None:
        result = self.evaluate(title="chore: a", head_ref="milestone/1.5.0", commits=commits("docs: a"))
        self.assertFalse(result.ok)
        self.assertIn("no releasable change", result.errors[0])

    def test_unreleased_commits_on_main_count_for_the_milestone(self) -> None:
        result = self.evaluate(
            title="fix: a",
            head_ref="milestone/1.4.2",
            commits=commits("fix: a"),
            base_impact="minor",
            milestones=milestones("1.4.2"),
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.computed, "1.5.0")

    def test_patch_milestone_passes(self) -> None:
        result = self.evaluate(
            title="fix: a", head_ref="milestone/1.4.2", commits=commits("fix: a"), milestones=milestones("1.4.2")
        )
        self.assertTrue(result.ok, result.errors)

    def test_patch_milestone_title_matches_any_patch(self) -> None:
        self.assertTrue(ri.milestone_matches("1.5.x", "1.5.1"))
        self.assertTrue(ri.milestone_matches("1.5.x", "1.5.7"))
        self.assertFalse(ri.milestone_matches("1.5.x", "1.5.0"))
        self.assertFalse(ri.milestone_matches("1.5.x", "1.6.0"))
        self.assertTrue(ri.milestone_matches("1.6.0", "1.6.0"))
        self.assertFalse(ri.milestone_matches("1.6.0", "1.6.1"))
        for bad in ("1.x.x", "1.5", "x", "1.5.x-rc.1"):
            self.assertFalse(ri.milestone_matches(bad, "1.5.1"), bad)
        self.assertFalse(ri.milestone_matches("1.5.x", "1.5.1-rc.1"))

    def test_patch_milestone_branch_with_patch_passes(self) -> None:
        result = self.evaluate(
            title="fix: a",
            head_ref="milestone/1.5.x",
            commits=commits("fix: a"),
            last_release="1.5.0",
            milestones=milestones("1.5.x"),
        )
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.computed, "1.5.1")

    def test_patch_milestone_branch_after_dependabot_release_passes(self) -> None:
        result = self.evaluate(
            title="fix: a",
            head_ref="milestone/1.5.x",
            commits=commits("fix: a"),
            last_release="1.5.2",
            milestones=milestones("1.5.x"),
        )
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.computed, "1.5.3")

    def test_patch_milestone_branch_with_feat_fails(self) -> None:
        result = self.evaluate(
            title="fix: a",
            head_ref="milestone/1.5.x",
            commits=commits("fix: a", "feat: b"),
            last_release="1.5.0",
            milestones=milestones("1.5.x"),
        )
        self.assertFalse(result.ok)
        self.assertIn("minor", result.errors[0])
        self.assertIn("milestone/1.5.x", result.errors[0])

    def test_patch_milestone_branch_with_breaking_change_fails(self) -> None:
        result = self.evaluate(
            title="fix: a",
            head_ref="milestone/1.5.x",
            commits=commits("fix!: b"),
            last_release="1.5.0",
            milestones=milestones("1.5.x"),
        )
        self.assertFalse(result.ok)
        self.assertIn("major", result.errors[0])

    def test_patch_milestone_without_open_github_milestone_fails(self) -> None:
        result = self.evaluate(
            head_ref="milestone/1.5.x", commits=commits("fix: a"), last_release="1.5.0", milestones=milestones("1.6.0")
        )
        self.assertFalse(result.ok)
        self.assertIn("no open GitHub milestone titled '1.5.x'", result.errors[-1])

    def test_minor_milestone_branch_with_feat_passes(self) -> None:
        result = self.evaluate(
            title="feat: a",
            head_ref="milestone/1.6.0",
            commits=commits("feat: a"),
            last_release="1.5.3",
            milestones=milestones("1.6.0"),
        )
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.computed, "1.6.0")

    def test_first_release(self) -> None:
        result = self.evaluate(
            title="feat: a",
            head_ref="milestone/1.0.0",
            commits=commits("feat: a"),
            last_release=None,
            milestones=milestones("1.0.0"),
        )
        self.assertTrue(result.ok, result.errors)

    def test_milestone_pr_title_is_ignored(self) -> None:
        # Milestone PRs are merged with a merge commit, never squashed: the title
        # never reaches main, so only the commits decide the impact.
        result = self.evaluate(title="feat: x", head_ref="milestone/1.5.0", commits=commits("docs: a"))
        self.assertFalse(result.ok)
        self.assertIn("no releasable change", result.errors[0])
        self.assertNotIn("PR title", [e.label for e in result.entries])

    def test_non_milestone_pr_title_counts(self) -> None:
        # Other branches are squash-merged: the title becomes the commit on main.
        result = self.evaluate(title="feat: x", head_ref="fix/x", commits=commits("docs: a"))
        self.assertFalse(result.ok)
        self.assertIn("PR title", result.errors[0])

    def test_malformed_milestone_branch_keeps_the_title(self) -> None:
        # milestone/1.5 is not a milestone branch (MILESTONE_BRANCH_RE): it is squash-merged
        # like any other branch, so its title becomes the commit on main and must be checked.
        result = self.evaluate(title="feat: x", head_ref="milestone/1.5", commits=commits("chore: a"))
        self.assertFalse(result.ok)
        self.assertIn("PR title", result.errors[0])


class GuardTest(unittest.TestCase):
    def test_next_patch_is_allowed_without_milestone(self) -> None:
        self.assertTrue(ri.guard_allows("1.4.2", "1.4.1", milestones()))

    def test_open_milestone_is_allowed(self) -> None:
        self.assertTrue(ri.guard_allows("1.5.0", "1.4.1", milestones("1.5.0")))

    def test_minor_without_milestone_is_blocked(self) -> None:
        self.assertFalse(ri.guard_allows("1.5.0", "1.4.1", milestones("1.6.0")))

    def test_skipped_patch_is_blocked(self) -> None:
        self.assertFalse(ri.guard_allows("1.4.3", "1.4.1", milestones()))

    def test_first_release_needs_a_milestone(self) -> None:
        self.assertFalse(ri.guard_allows("1.0.0", None, milestones()))
        self.assertTrue(ri.guard_allows("1.0.0", None, milestones("1.0.0")))

    def test_invalid_version_raises(self) -> None:
        with self.assertRaises(ValueError):
            ri.guard_allows("1.5.0-rc.1", "1.4.1", milestones())

    def run_guard(self, next_version: str, env: dict[str, str]) -> tuple[int, str, list[Any]]:
        calls: list[Any] = []

        def fake_request(method: str, url: str, body: Any = None) -> Any:
            calls.append((method, url, body))
            if "/milestones" in url:
                return [{"title": "1.6.0"}]
            if method == "GET":
                return []
            return {"number": 99}

        out = io.StringIO()
        with (
            mock.patch.object(ri, "_request", fake_request),
            mock.patch.object(ri, "provenance_violation", lambda *a, **k: None),
            mock.patch.object(ri, "milestone_merges", lambda *a, **k: []),
            mock.patch.dict(os.environ, env, clear=False),
            redirect_stdout(out),
        ):
            code = ri.main(["guard", "--repo", "o/r", "--next", next_version, "--last", "1.4.1"])
        return code, out.getvalue(), calls

    def test_blocked_release_opens_issue(self) -> None:
        code, out, calls = self.run_guard("1.5.0", {"DRY_RUN": "false"})
        self.assertEqual(code, 1)
        self.assertIn("::error::release blocked: computed 1.5.0", out)
        posts = [c for c in calls if c[0] == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0][2]["title"], "release blocked: computed 1.5.0")

    def test_blocked_dry_run_opens_no_issue(self) -> None:
        code, _, calls = self.run_guard("1.5.0", {"DRY_RUN": "true"})
        self.assertEqual(code, 1)
        self.assertFalse([c for c in calls if c[0] == "POST"])

    def test_allowed_release_exits_zero(self) -> None:
        code, _, calls = self.run_guard("1.6.0", {"DRY_RUN": "false"})
        self.assertEqual(code, 0)
        self.assertFalse([c for c in calls if c[0] == "POST"])

    def test_existing_issue_is_not_duplicated(self) -> None:
        def fake_request(method: str, url: str, body: Any = None) -> Any:
            assert method == "GET", "must not create a second issue"
            return [{"title": "release blocked: computed 1.5.0", "number": 5}]

        out = io.StringIO()
        with redirect_stdout(out):
            ri.open_block_issue("o/r", "1.5.0", "1.4.1", request=fake_request)
        self.assertIn("#5", out.getvalue())

    def run_provenance_guard(self, env: dict[str, str], violation: Any) -> tuple[int, str, list[Any]]:
        calls: list[Any] = []

        def fake_request(method: str, url: str, body: Any = None) -> Any:
            calls.append((method, url, body))
            if "/milestones" in url:
                return [{"title": "1.6.0"}]
            return [] if method == "GET" else {"number": 42}

        out = io.StringIO()
        with (
            mock.patch.object(ri, "_request", fake_request),
            mock.patch.object(ri, "provenance_violation", violation),
            mock.patch.object(ri, "milestone_merges", lambda *a, **k: []),
            mock.patch.dict(os.environ, env, clear=False),
            redirect_stdout(out),
        ):
            code = ri.main(["guard", "--repo", "o/r", "--next", "1.6.0", "--last", "1.4.1"])
        return code, out.getvalue(), calls

    def test_provenance_violation_blocks_and_opens_an_issue_naming_the_commits(self) -> None:
        reason = "minor/major commits outside the milestone merge: abc1234"
        code, out, calls = self.run_provenance_guard({"DRY_RUN": "false"}, lambda *a, **k: reason)
        self.assertEqual(code, 1)
        self.assertIn("abc1234", out)
        posts = [c for c in calls if c[0] == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0][2]["title"], "release blocked: computed 1.6.0")
        self.assertIn("abc1234", posts[0][2]["body"])
        self.assertIn("does not come from the milestone merge", posts[0][2]["body"])
        self.assertNotIn("neither the next patch", posts[0][2]["body"])

    def test_provenance_violation_dry_run_opens_no_issue(self) -> None:
        code, out, calls = self.run_provenance_guard({"DRY_RUN": "true"}, lambda *a, **k: "abc1234")
        self.assertEqual(code, 1)
        self.assertIn("dry run", out)
        self.assertFalse([c for c in calls if c[0] == "POST"])

    def test_provenance_is_checked_against_the_repository_owner(self) -> None:
        seen: dict[str, Any] = {}

        def spy(*a: Any, **k: Any) -> None:
            seen.update(k)

        code, _, _ = self.run_provenance_guard({"DRY_RUN": "false"}, spy)
        self.assertEqual(code, 0)
        self.assertEqual(seen.get("owner"), "o")

    def test_git_failure_in_the_provenance_check_refuses_to_release(self) -> None:
        def broken(*a: Any, **k: Any) -> None:
            raise subprocess.CalledProcessError(128, ["git", "log"])

        code, out, _calls = self.run_provenance_guard({"DRY_RUN": "false"}, broken)
        self.assertEqual(code, 1)
        self.assertIn("refusing to release", out)

    def test_api_failure_refuses_to_release(self) -> None:
        def broken(method: str, url: str, body: Any = None) -> Any:
            raise ri.urllib.error.URLError("down")

        out = io.StringIO()
        with mock.patch.object(ri, "_request", broken), redirect_stdout(out):
            code = ri.main(["guard", "--repo", "o/r", "--next", "1.5.0", "--last", "1.4.1"])
        self.assertEqual(code, 1)
        self.assertIn("refusing to release", out.getvalue())


class TempRepoCase(unittest.TestCase):
    """A throw-away git repository: milestone merges are a property of the graph."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.commit("chore: seed")
        self.git("tag", "v1.4.1")

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, message: str) -> str:
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")

    def merge_milestone(self, version: str, number: int = 7) -> None:
        self.git(
            "merge",
            "-q",
            "--no-ff",
            f"milestone/{version}",
            "-m",
            f"Merge pull request #{number} from o/milestone/{version}",
        )


class ProvenanceTest(TempRepoCase):
    def violation(self, next_version: str = "1.5.0") -> str | None:
        return ri.provenance_violation(next_version, "1.4.1", RULES, cwd=self.repo)

    def test_feat_pushed_to_main_with_open_milestone_blocks(self) -> None:
        sha = self.commit("feat: sneaked in")
        message = self.violation()
        assert message is not None
        self.assertIn("minor/major commits outside the milestone merge", message)
        self.assertIn(sha[:7], message)

    def test_feat_inside_milestone_merge_allows(self) -> None:
        self.git("switch", "-q", "-c", "milestone/1.5.0")
        self.commit("feat: inside")
        self.git("switch", "-q", "main")
        self.commit("fix: on main meanwhile")
        self.merge_milestone("1.5.0")
        self.assertIsNone(self.violation())

    def test_release_without_milestone_merge_blocks(self) -> None:
        self.commit("fix: a")
        message = self.violation()
        assert message is not None
        self.assertIn("no merge of milestone/1.5.0", message)

    def test_feat_on_main_synced_into_milestone_blocks(self) -> None:
        self.git("switch", "-q", "-c", "milestone/1.5.0")
        inside = self.commit("feat: inside")
        self.git("switch", "-q", "main")
        outside = self.commit("feat: pushed to main")
        self.git("switch", "-q", "milestone/1.5.0")
        self.git("merge", "-q", "--no-ff", "main", "-m", "Merge branch 'main' into milestone/1.5.0")
        self.git("switch", "-q", "main")
        self.merge_milestone("1.5.0")
        message = self.violation()
        assert message is not None
        self.assertIn(outside[:7], message)
        self.assertNotIn(inside[:7], message)

    def test_merge_of_another_milestone_does_not_count(self) -> None:
        self.git("switch", "-q", "-c", "milestone/1.6.0")
        self.commit("feat: other")
        self.git("switch", "-q", "main")
        self.merge_milestone("1.6.0")
        self.assertIsNotNone(self.violation("1.5.0"))

    def test_merge_from_another_owner_does_not_count(self) -> None:
        self.git("switch", "-q", "-c", "milestone/1.5.0")
        self.commit("feat: inside")
        self.git("switch", "-q", "main")
        self.git(
            "merge", "-q", "--no-ff", "milestone/1.5.0", "-m", "Merge pull request #7 from fork-owner/milestone/1.5.0"
        )
        self.assertIsNone(ri.provenance_violation("1.5.0", "1.4.1", RULES, cwd=self.repo))
        message = ri.provenance_violation("1.5.0", "1.4.1", RULES, cwd=self.repo, owner="o")
        assert message is not None
        self.assertIn("no merge of milestone/1.5.0", message)

    def test_real_git_failure_raises(self) -> None:
        with self.assertRaises(subprocess.CalledProcessError):
            ri.provenance_violation("1.5.0", "9.9.9", RULES, cwd=self.repo)

    def test_patch_release_needs_no_milestone_merge(self) -> None:
        self.commit("fix: a")
        self.assertIsNone(ri.provenance_violation("1.4.2", "1.4.1", RULES, cwd=self.repo))


class MilestoneMergesTest(TempRepoCase):
    def merges(self) -> list[str]:
        return ri.milestone_merges("v1.5.0..HEAD", cwd=self.repo)

    def setUp(self) -> None:
        super().setUp()
        self.git("tag", "-d", "v1.4.1")
        self.git("tag", "v1.5.0")

    def test_merges_inside_the_milestone_are_not_milestone_merges(self) -> None:
        self.git("switch", "-q", "-c", "milestone/1.5.x")
        # a feature PR merged into the milestone, and an R1 sync of main
        self.git("switch", "-q", "-c", "ci/topic")
        self.commit("fix: topic")
        self.git("switch", "-q", "milestone/1.5.x")
        self.git("merge", "-q", "--no-ff", "ci/topic", "-m", "Merge pull request #269 from o/ci/topic")
        self.git("switch", "-q", "main")
        self.commit("fix: released from main")
        self.git("switch", "-q", "milestone/1.5.x")
        self.git("merge", "-q", "--no-ff", "main", "-m", "Merge branch 'main' into milestone/1.5.x")
        self.git("switch", "-q", "main")
        self.assertEqual(self.merges(), [])
        self.merge_milestone("1.5.x", number=300)
        self.assertEqual(self.merges(), ["1.5.x"])

    def test_milestone_merge_on_a_side_branch_is_not_on_the_first_parent_line(self) -> None:
        # The merge subject matches, but it sits on a topic branch that main later merged.
        self.git("switch", "-q", "-c", "milestone/1.5.x")
        self.commit("fix: inside")
        self.git("switch", "-q", "main")
        self.git("switch", "-q", "-c", "side")
        self.git("merge", "-q", "--no-ff", "milestone/1.5.x", "-m", "Merge pull request #9 from o/milestone/1.5.x")
        self.git("switch", "-q", "main")
        self.commit("fix: on main")
        self.git("merge", "-q", "--no-ff", "side", "-m", "Merge pull request #10 from o/side")
        self.assertEqual(self.merges(), [])

    def test_unmatched_merge_subject_is_not_a_milestone_merge(self) -> None:
        self.git("switch", "-q", "-c", "milestone/1.5.x")
        self.commit("fix: inside")
        self.git("switch", "-q", "main")
        self.git(
            "merge", "-q", "--no-ff", "milestone/1.5.x", "-m", "Merge remote-tracking branch 'origin/milestone/1.5.x'"
        )
        self.assertEqual(self.merges(), [])

    def test_local_merge_subject_is_a_milestone_merge(self) -> None:
        self.git("switch", "-q", "-c", "milestone/1.6.0")
        self.commit("fix: inside")
        self.git("switch", "-q", "main")
        self.git("merge", "-q", "--no-ff", "milestone/1.6.0", "-m", "Merge branch 'milestone/1.6.0'")
        self.assertEqual(self.merges(), ["1.6.0"])

    def test_rebased_or_squashed_milestone_has_no_merge(self) -> None:
        self.commit("fix: squashed milestone (#300)")
        self.assertEqual(self.merges(), [])


def issue(number: int, *labels: str, pr: bool = False) -> dict[str, Any]:
    row: dict[str, Any] = {"number": number, "labels": [{"name": n} for n in labels]}
    if pr:
        row["pull_request"] = {"url": "x"}
    return row


class MilestoneIssuesTest(unittest.TestCase):
    def getter(self, rows: list[dict[str, Any]], milestone: str = "1.5.x") -> Any:
        urls: list[str] = []

        def get(url: str) -> Any:
            urls.append(url)
            if "/milestones" in url:
                return [{"title": "1.4.0", "number": 3}, {"title": milestone, "number": 12}]
            page = int(url.rsplit("page=", 1)[1])
            return rows[(page - 1) * 100 : page * 100]

        get.urls = urls  # type: ignore[attr-defined]
        return get

    def test_open_pull_request_in_milestone_is_ignored(self) -> None:
        found = ri.milestone_issues("o/r", "1.5.x", get=self.getter([issue(4, pr=True), issue(5)]))
        assert found is not None
        self.assertEqual(found.open, [5])

    def test_issue_pages_are_read(self) -> None:
        rows = [issue(n) for n in range(1, 102)]
        get = self.getter(rows)
        found = ri.milestone_issues("o/r", "1.5.x", get=get)
        assert found is not None
        self.assertIn(101, found.open)
        self.assertEqual(len(found.open), 101)
        self.assertTrue(any("milestone=12" in u and "state=open" in u for u in get.urls))

    def test_waived_issues_are_separated_and_sorted(self) -> None:
        found = ri.milestone_issues(
            "o/r", "1.5.x", get=self.getter([issue(9), issue(150, ri.WAIVER_LABEL), issue(3, "bug", ri.WAIVER_LABEL)])
        )
        self.assertEqual(found, ri.MilestoneIssues(open=[9], waived=[3, 150]))

    def test_milestone_title_with_surrounding_spaces_is_found(self) -> None:
        found = ri.milestone_issues("o/r", "1.5.x", get=self.getter([issue(5)], milestone=" 1.5.x "))
        assert found is not None
        self.assertEqual(found.open, [5])

    def test_unknown_milestone_is_none(self) -> None:
        self.assertIsNone(ri.milestone_issues("o/r", "9.9.x", get=self.getter([issue(1)])))

    def test_closed_milestone_is_found(self) -> None:
        get = self.getter([])
        ri.milestone_issues("o/r", "1.5.x", get=get)
        self.assertIn("state=all", get.urls[0])


class GuardDecisionTest(unittest.TestCase):
    def test_no_merge_needs_no_milestone(self) -> None:
        self.assertEqual(ri.guard_decision("1.5.1", "1.5.0", [], set(), {}), (True, [], []))

    def test_open_issues_block_in_ascending_order(self) -> None:
        issues = {"1.5.x": ri.MilestoneIssues(open=[3, 7], waived=[])}
        allowed, errors, warnings = ri.guard_decision("1.5.1", "1.5.0", ["1.5.x"], {"1.5.x"}, issues)
        self.assertFalse(allowed)
        self.assertEqual(errors, ["release blocked: milestone 1.5.x has open issues: #3, #7"])
        self.assertEqual(warnings, [])

    def test_waived_only_allows_with_warning(self) -> None:
        issues = {"1.5.x": ri.MilestoneIssues(open=[], waived=[150])}
        self.assertEqual(
            ri.guard_decision("1.5.1", "1.5.0", ["1.5.x"], {"1.5.x"}, issues),
            (True, [], ["release proceeds with waived issues: #150"]),
        )

    def test_waived_and_unwaived_lists_only_the_unwaived_as_blocking(self) -> None:
        issues = {"1.5.x": ri.MilestoneIssues(open=[9], waived=[150])}
        allowed, errors, _ = ri.guard_decision("1.5.1", "1.5.0", ["1.5.x"], {"1.5.x"}, issues)
        self.assertFalse(allowed)
        self.assertIn("#9", errors[0])
        self.assertNotIn("#150", errors[0])

    def test_merged_title_must_match_version(self) -> None:
        issues = {"1.5.x": ri.MilestoneIssues(open=[], waived=[])}
        allowed, errors, _ = ri.guard_decision("1.6.0", "1.5.3", ["1.5.x"], {"1.6.0"}, issues)
        self.assertFalse(allowed)
        self.assertIn("1.5.x", errors[0])
        self.assertIn("1.6.0", errors[0])

    def test_missing_milestone_blocks(self) -> None:
        allowed, errors, _ = ri.guard_decision("1.5.1", "1.5.0", ["1.5.x"], {"1.5.x"}, {"1.5.x": None})
        self.assertFalse(allowed)
        self.assertIn("1.5.x", errors[0])

    def test_neither_patch_nor_open_milestone_blocks(self) -> None:
        allowed, errors, _ = ri.guard_decision("1.6.0", "1.5.3", [], set(), {})
        self.assertFalse(allowed)
        self.assertIn("neither the next patch nor an open milestone", errors[0])

    def test_patch_milestone_title_opens_its_patch_releases(self) -> None:
        self.assertTrue(ri.guard_allows("1.5.4", "1.5.0", milestones("1.5.x")))
        self.assertFalse(ri.guard_allows("1.6.0", "1.5.0", milestones("1.5.x")))


class MilestoneRuleGuardTest(unittest.TestCase):
    """run_guard end to end with a faked API, as ``test_blocked_release_opens_issue`` does."""

    def run_guard(
        self,
        merged: list[str],
        rows: list[dict[str, Any]],
        *,
        next_version: str = "1.5.1",
        last: str = "1.5.0",
        env: dict[str, str] | None = None,
        broken_issues: bool = False,
        merges_fn: Any = None,
    ) -> tuple[int, str, list[Any], str]:
        calls: list[Any] = []

        def fake_request(method: str, url: str, body: Any = None) -> Any:
            calls.append((method, url, body))
            if "/milestones" in url:
                return [{"title": "1.5.x", "number": 12}, {"title": "1.6.0", "number": 13}]
            if method == "GET" and "milestone=" in url:
                if broken_issues:
                    raise ri.urllib.error.URLError("down")
                page = int(url.rsplit("page=", 1)[1])
                return rows[(page - 1) * 100 : page * 100]
            return [] if method == "GET" else {"number": 99}

        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / "summary.md"
            summary.write_text("")
            with (
                mock.patch.object(ri, "_request", fake_request),
                mock.patch.object(ri, "provenance_violation", lambda *a, **k: None),
                mock.patch.object(ri, "milestone_merges", merges_fn or (lambda *a, **k: merged)),
                mock.patch.dict(os.environ, {"DRY_RUN": "false", "GITHUB_STEP_SUMMARY": str(summary), **(env or {})}),
                redirect_stdout(out),
            ):
                code = ri.main(["guard", "--repo", "o/r", "--next", next_version, "--last", last])
            text = summary.read_text()
        return code, out.getvalue(), calls, text

    def test_range_passed_to_milestone_merges(self) -> None:
        for last, expected in (("1.5.0", "v1.5.0..HEAD"), ("", "HEAD")):
            seen: list[str] = []

            def spy(rev_range: str, *a: Any, **k: Any) -> list[str]:
                seen.append(rev_range)
                return []

            self.run_guard(["1.5.x"], [], last=last, next_version="1.5.1" if last else "1.6.0", merges_fn=spy)
            self.assertEqual(seen, [expected])

    def test_fix_only_release_ignores_open_milestone(self) -> None:
        # The range holds a Dependabot commit and a fix, but no milestone merge.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            for args in (
                ["init", "-q", "-b", "main"],
                ["config", "user.name", "T"],
                ["config", "user.email", "t@example.invalid"],
                ["config", "commit.gpgsign", "false"],
                ["commit", "-q", "--allow-empty", "-m", "chore: seed"],
                ["tag", "v1.5.0"],
                ["commit", "-q", "--allow-empty", "-m", "chore(deps): bump x"],
                ["commit", "-q", "--allow-empty", "-m", "fix: y"],
            ):
                subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
            calls: list[Any] = []

            def fake_request(method: str, url: str, body: Any = None) -> Any:
                calls.append(url)
                return [{"title": "1.5.x", "number": 12}] if "/milestones" in url else []

            out = io.StringIO()
            with (
                mock.patch.object(ri, "_request", fake_request),
                mock.patch.object(ri, "provenance_violation", lambda *a, **k: None),
                mock.patch.object(ri, "REPO_ROOT", repo),
                redirect_stdout(out),
            ):
                code = ri.main(["guard", "--repo", "o/r", "--next", "1.5.1", "--last", "1.5.0"])
        self.assertEqual(code, 0, out.getvalue())
        self.assertFalse([u for u in calls if "milestone=" in u], calls)

    def test_milestone_merge_with_open_issue_blocks(self) -> None:
        code, out, calls, _ = self.run_guard(["1.5.x"], [issue(7), issue(3)])
        self.assertEqual(code, 1)
        self.assertIn("#3, #7", out)
        posts = [c for c in calls if c[0] == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertIn("#3, #7", posts[0][2]["body"])

    def test_milestone_merge_with_open_issue_dry_run_opens_no_issue(self) -> None:
        code, _, calls, _ = self.run_guard(["1.5.x"], [issue(7)], env={"DRY_RUN": "true"})
        self.assertEqual(code, 1)
        self.assertFalse([c for c in calls if c[0] == "POST"])

    def test_milestone_merge_with_empty_milestone_allows(self) -> None:
        code, _, calls, _ = self.run_guard(["1.5.x"], [])
        self.assertEqual(code, 0)
        self.assertFalse([c for c in calls if c[0] == "POST"])

    def test_milestone_merge_with_waived_issue_allows_with_warning(self) -> None:
        code, out, _, summary = self.run_guard(["1.5.x"], [issue(150, ri.WAIVER_LABEL)])
        self.assertEqual(code, 0)
        self.assertIn("::warning::release proceeds with waived issues: #150", out)
        self.assertIn("#150", summary)

    def test_waived_and_unwaived_blocks(self) -> None:
        code, out, _, _ = self.run_guard(["1.5.x"], [issue(150, ri.WAIVER_LABEL), issue(9)])
        self.assertEqual(code, 1)
        self.assertIn("#9", out)
        self.assertNotIn("#150", out)

    def test_merged_milestone_title_must_match_version(self) -> None:
        code, out, _, _ = self.run_guard(["1.5.x"], [], next_version="1.6.0", last="1.5.3")
        self.assertEqual(code, 1)
        self.assertIn("1.5.x", out)

    def test_api_error_blocks_release(self) -> None:
        code, out, _, _ = self.run_guard(["1.5.x"], [], broken_issues=True)
        self.assertEqual(code, 1)
        self.assertIn("refusing to release", out)

    def test_git_error_reading_milestone_merges_blocks_release(self) -> None:
        def broken(*a: Any, **k: Any) -> list[str]:
            raise subprocess.CalledProcessError(128, ["git", "log"])

        out = io.StringIO()
        with (
            mock.patch.object(ri, "_request", lambda *a, **k: [{"title": "1.5.x", "number": 12}]),
            mock.patch.object(ri, "provenance_violation", lambda *a, **k: None),
            mock.patch.object(ri, "milestone_merges", broken),
            redirect_stdout(out),
        ):
            code = ri.main(["guard", "--repo", "o/r", "--next", "1.5.1", "--last", "1.5.0"])
        self.assertEqual(code, 1)
        self.assertIn("refusing to release", out.getvalue())


class MilestonePaginationTest(unittest.TestCase):
    def test_all_pages_are_read(self) -> None:
        pages = {1: [{"title": str(i)} for i in range(100)], 2: [{"title": "1.5.0"}]}

        def get(url: str) -> Any:
            page = int(url.rsplit("page=", 1)[1])
            return pages.get(page, [])

        titles = ri.open_milestones("o/r", get=get)
        self.assertIn("1.5.0", titles)
        self.assertEqual(len(titles), 101)


class OutputTest(unittest.TestCase):
    def test_annotation_escapes_newlines(self) -> None:
        self.assertEqual(ri.annotation("error", "a%b\nc"), "::error::a%25b%0Ac")

    def test_markdown_cells_escape_pipes(self) -> None:
        table = ri.summary_table([ri.Entry("abc1234", "feat: a | b `c`", "minor")])
        self.assertIn("feat: a \\| b 'c'", table)


if __name__ == "__main__":
    unittest.main()
