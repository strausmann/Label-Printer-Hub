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


class CommitImpactTest(unittest.TestCase):
    def test_types(self) -> None:
        cases = {
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
        for message, expected in cases.items():
            with self.subTest(message=message):
                self.assertEqual(impact(message), expected)

    def test_breaking_bang_is_major_for_every_type(self) -> None:
        for message in ("feat!: x", "fix(api)!: x", "docs!: x", "chore(deps)!: x"):
            with self.subTest(message=message):
                self.assertEqual(impact(message), "major")

    def test_breaking_footers(self) -> None:
        for footer in (
            "BREAKING CHANGE: gone",
            "BREAKING-CHANGE: gone",
            "breaking change: gone",
            "* BREAKING CHANGE: gone",
        ):
            with self.subTest(footer=footer):
                self.assertEqual(impact(f"fix: small\n\n{footer}"), "major")

    def test_breaking_word_inside_a_sentence_is_not_a_footer(self) -> None:
        self.assertIsNone(impact("chore: x\n\nThis is not a BREAKING CHANGE: inline"))
        self.assertIsNone(impact("chore: x\n\nBREAKING CHANGES: plural is not a keyword"))

    def test_default_rules_apply_when_no_custom_rule_matches(self) -> None:
        # commit-analyzer falls back to its default rules (uppercase JSHint types, reverts).
        self.assertEqual(impact("FEAT: shout"), "minor")
        self.assertEqual(impact('Revert "feat: a"\n\nThis reverts commit abc123.'), "patch")
        self.assertIsNone(impact("Feat: capitalised type matches no rule"))

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

    def test_provenance_violation_blocks_an_allowed_version(self) -> None:
        out = io.StringIO()
        with (
            mock.patch.object(ri, "_request", lambda *a, **k: [{"title": "1.6.0"}]),
            mock.patch.object(
                ri, "provenance_violation", lambda *a, **k: "minor/major commits outside the milestone merge: abc1234"
            ),
            redirect_stdout(out),
        ):
            code = ri.main(["guard", "--repo", "o/r", "--next", "1.6.0", "--last", "1.4.1"])
        self.assertEqual(code, 1)
        self.assertIn("abc1234", out.getvalue())

    def test_api_failure_refuses_to_release(self) -> None:
        def broken(method: str, url: str, body: Any = None) -> Any:
            raise ri.urllib.error.URLError("down")

        out = io.StringIO()
        with mock.patch.object(ri, "_request", broken), redirect_stdout(out):
            code = ri.main(["guard", "--repo", "o/r", "--next", "1.5.0", "--last", "1.4.1"])
        self.assertEqual(code, 1)
        self.assertIn("refusing to release", out.getvalue())


class ProvenanceTest(unittest.TestCase):
    """The guard needs a real history: milestone merges are a property of the graph."""

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
        return subprocess.run(
            ["git", *args], cwd=self.repo, check=True, capture_output=True, text=True
        ).stdout.strip()

    def commit(self, message: str) -> str:
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")

    def merge_milestone(self, version: str, number: int = 7) -> None:
        self.git(
            "merge", "-q", "--no-ff", f"milestone/{version}", "-m", f"Merge pull request #{number} from o/milestone/{version}"
        )

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

    def test_patch_release_needs_no_milestone_merge(self) -> None:
        self.commit("fix: a")
        self.assertIsNone(ri.provenance_violation("1.4.2", "1.4.1", RULES, cwd=self.repo))


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
