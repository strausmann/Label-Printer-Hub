# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for the draft-first release flow (immutable releases).

The repository has GitHub immutable releases enabled: once a release is published, its
assets and tag are locked. The release workflow therefore creates the release as a draft
(``draftRelease`` in .releaserc.json), attaches the SBOM to the draft and publishes it in
a last job. These tests check that wiring and run the real shell of the two jobs that
touch the release against a stand-in ``gh`` that records its calls, so they need neither
network nor a token.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
RELEASERC = REPO_ROOT / ".releaserc.json"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
RELEASE_YML = WORKFLOWS / "release.yml"


def _release_jobs() -> dict:
    return yaml.safe_load(RELEASE_YML.read_text(encoding="utf-8"))["jobs"]


def _step_script(job: str, step_name: str) -> str:
    for step in _release_jobs()[job]["steps"]:
        if step.get("name") == step_name:
            return step["run"]
    raise AssertionError(f"step {step_name!r} not found in job {job!r}")


# Stand-in for gh. It answers `release view` from GH_FAKE_DRAFT / GH_FAKE_ASSETS
# (comma-separated asset names), `api .../releases/tags/...` from GH_FAKE_AFTER and
# `api .../releases?...` (the release list) from GH_FAKE_RELEASES (comma-separated
# tag names of published releases), applies the --jq filter with jq, and appends
# every call to GH_FAKE_LOG.
FAKE_GH = textwrap.dedent(
    """\
    #!/usr/bin/env bash
    set -euo pipefail
    printf '%s\\n' "$*" >> "$GH_FAKE_LOG"
    jq_filter=""
    args=("$@")
    for i in "${!args[@]}"; do
      if [ "${args[$i]}" = "--jq" ]; then jq_filter="${args[$((i + 1))]}"; fi
    done
    case "$*" in
      "release view "*)
        doc=$(python3 -c 'import json, os
    names = [n for n in os.environ.get("GH_FAKE_ASSETS", "").split(",") if n]
    print(json.dumps({"isDraft": os.environ["GH_FAKE_DRAFT"] == "true",
                      "assets": [{"name": n} for n in names]}))')
        ;;
      "api "*/releases/tags/*)
        doc=$(python3 -c 'import json, os
    print(json.dumps({"draft": os.environ.get("GH_FAKE_AFTER", "false") == "true", "immutable": True}))')
        ;;
      "api "*"/releases?"*)
        doc=$(python3 -c 'import json, os
    tags = [t for t in os.environ.get("GH_FAKE_RELEASES", "").split(",") if t]
    print(json.dumps([{"tag_name": t, "draft": False} for t in tags] + [{"tag_name": "v99.0.0", "draft": True}]))')
        ;;
      "release edit "*|"release upload "*)
        exit 0
        ;;
      *)
        echo "fake gh: unexpected call: $*" >&2
        exit 2
        ;;
    esac
    if [ -n "$jq_filter" ]; then jq -r "$jq_filter" <<< "$doc"; else printf '%s\\n' "$doc"; fi
    """
)


class _FakeGhCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        gh = self.tmp / "bin" / "gh"
        gh.parent.mkdir()
        gh.write_text(FAKE_GH, encoding="utf-8")
        gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
        self.log = self.tmp / "gh.log"
        self.log.touch()

    def run_script(
        self,
        script: str,
        *,
        draft: bool,
        assets: list[str],
        after_draft: bool = False,
        version: str = "1.6.1",
        releases: tuple[str, ...] = ("v1.6.0", "v1.5.2"),
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": f"{self.tmp / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(self.tmp),
            "VERSION": version,
            "GH_REPO": "owner/repo",
            "GH_TOKEN": "not-a-token",
            "GH_FAKE_LOG": str(self.log),
            "GH_FAKE_DRAFT": "true" if draft else "false",
            "GH_FAKE_ASSETS": ",".join(assets),
            "GH_FAKE_AFTER": "true" if after_draft else "false",
            "GH_FAKE_RELEASES": ",".join(releases),
        }
        return subprocess.run(
            ["bash", "-c", script],
            cwd=cwd or self.tmp,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def calls(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines()


class ConfigTest(unittest.TestCase):
    def test_github_plugin_creates_a_draft(self) -> None:
        cfg = json.loads(RELEASERC.read_text(encoding="utf-8"))
        github = [
            p for p in cfg["plugins"] if isinstance(p, list) and p[0] == "@semantic-release/github"
        ]
        self.assertEqual(len(github), 1)
        self.assertIs(github[0][1].get("draftRelease"), True)

    def test_publish_runs_after_images_and_sbom_without_always(self) -> None:
        job = _release_jobs()["publish-release"]
        self.assertEqual(set(job["needs"]), {"release", "images", "release-sbom"})
        # always() or failure() would publish a release whose images or SBOM failed.
        self.assertNotIn("always()", job["if"])
        self.assertNotIn("failure()", job["if"])
        self.assertIn("!inputs.dry_run", job["if"])
        self.assertEqual(job["permissions"], {"contents": "write"})

    def test_sbom_is_attached_before_publishing(self) -> None:
        self.assertEqual(set(_release_jobs()["release-sbom"]["needs"]), {"release", "images"})

    def test_only_publish_release_publishes_a_draft(self) -> None:
        # Counted in the parsed `run:` scripts, not in the file text, so comments and the
        # recovery instructions printed by release-unfinished do not count.
        publishers = []
        for workflow in sorted(WORKFLOWS.glob("*.yml")):
            jobs = yaml.safe_load(workflow.read_text(encoding="utf-8")).get("jobs", {})
            for name, job in jobs.items():
                for step in job.get("steps", []):
                    for line in step.get("run", "").splitlines():
                        if "--draft=false" in line and not line.lstrip().startswith("echo"):
                            publishers.append(f"{workflow.name}:{name}")
        self.assertEqual(publishers, ["release.yml:publish-release"])


# --------------------------------------------------------------------------- job `if:`
# A small evaluator for the subset of GitHub expressions the release jobs use: paths,
# 'strings', ==, !=, !, &&, || and the status functions always() and success(). As on
# GitHub, an `if:` without a status function is `success() && (<expr>)`, and success()
# is true only when every job in `needs` succeeded.

_TOKEN = re.compile(r"\s*(&&|\|\||==|!=|!|\(|\)|'[^']*'|[A-Za-z_][\w.-]*\(\)|[A-Za-z_][\w.-]*)")


def _tokens(expr: str) -> list[str]:
    out, pos = [], 0
    expr = expr.strip()
    while pos < len(expr):
        match = _TOKEN.match(expr, pos)
        if not match:
            raise ValueError(f"cannot parse {expr[pos:]!r}")
        out.append(match.group(1))
        pos = match.end()
    return out


def evaluate_if(expr: str, ctx: dict[str, object], needs: list[str]) -> bool:
    toks = _tokens(expr)
    if not any(t in ("always()", "success()", "failure()", "cancelled()") for t in toks):
        toks = ["success()", "&&", "(", *toks, ")"]
    pos = 0

    def peek() -> str | None:
        return toks[pos] if pos < len(toks) else None

    def take() -> str:
        nonlocal pos
        pos += 1
        return toks[pos - 1]

    def primary() -> object:
        tok = take()
        if tok == "(":
            value = disjunction()
            assert take() == ")"
            return value
        if tok.startswith("'"):
            return tok[1:-1]
        if tok == "always()":
            return True
        if tok == "success()":
            return all(ctx[f"needs.{n}.result"] == "success" for n in needs)
        if tok in ("failure()", "cancelled()"):
            raise ValueError(f"{tok} is not modelled")
        return ctx[tok]

    def comparison() -> object:
        left = primary()
        if peek() in ("==", "!="):
            op, right = take(), primary()
            equal = str(left).lower() == str(right).lower()
            return equal if op == "==" else not equal
        return left

    def unary() -> object:
        if peek() == "!":
            take()
            return not _truthy(unary())
        return comparison()

    def conjunction() -> object:
        value = unary()
        while peek() == "&&":
            take()
            right = unary()
            value = _truthy(value) and _truthy(right)
        return value

    def disjunction() -> object:
        value = conjunction()
        while peek() == "||":
            take()
            right = conjunction()
            value = _truthy(value) or _truthy(right)
        return value

    result = disjunction()
    assert pos == len(toks), f"trailing tokens in {expr!r}"
    return _truthy(result)


def _truthy(value: object) -> bool:
    return value not in (None, False, "", 0)


def _ctx(
    images: str = "success",
    sbom: str = "success",
    publish: str = "success",
    published: str = "true",
    dry_run: object = None,
) -> dict[str, object]:
    return {
        "needs.release.result": "success",
        "needs.release.outputs.new-release-published": published,
        "needs.images.result": images,
        "needs.release-sbom.result": sbom,
        "needs.publish-release.result": publish,
        "inputs.dry_run": dry_run,
    }


class JobConditionTest(unittest.TestCase):
    def _runs(self, job: str, ctx: dict[str, object]) -> bool:
        spec = _release_jobs()[job]
        needs = spec["needs"] if isinstance(spec["needs"], list) else [spec["needs"]]
        return evaluate_if(str(spec["if"]), ctx, needs)

    def test_publish_runs_only_when_images_and_sbom_succeeded(self) -> None:
        self.assertTrue(self._runs("publish-release", _ctx()))
        self.assertFalse(self._runs("publish-release", _ctx(images="failure", sbom="skipped")))
        self.assertFalse(self._runs("publish-release", _ctx(sbom="failure")))
        self.assertFalse(self._runs("publish-release", _ctx(dry_run=True)))
        self.assertFalse(self._runs("publish-release", _ctx(published="false")))

    def test_unpublished_release_is_reported_whichever_job_failed(self) -> None:
        cases = {
            "images": _ctx(images="failure", sbom="skipped", publish="skipped"),
            "images cancelled": _ctx(images="cancelled", sbom="skipped", publish="skipped"),
            "sbom": _ctx(sbom="failure", publish="skipped"),
            "publish": _ctx(publish="failure"),
        }
        for name, ctx in cases.items():
            with self.subTest(failed=name):
                self.assertTrue(self._runs("release-unfinished", ctx))

    def test_no_report_when_published_or_nothing_was_released(self) -> None:
        self.assertFalse(self._runs("release-unfinished", _ctx()))
        self.assertFalse(
            self._runs(
                "release-unfinished",
                _ctx(published="false", images="skipped", sbom="skipped", publish="skipped"),
            )
        )
        self.assertFalse(
            self._runs(
                "release-unfinished",
                _ctx(dry_run=True, images="skipped", sbom="skipped", publish="skipped"),
            )
        )

    def test_evaluator_applies_implicit_success(self) -> None:
        # Guards the evaluator itself: without a status function a failed need skips the job.
        self.assertFalse(
            evaluate_if("inputs.x == 'a'", {"inputs.x": "a", "needs.a.result": "failure"}, ["a"])
        )
        self.assertTrue(
            evaluate_if(
                "always() && inputs.x == 'a'", {"inputs.x": "a", "needs.a.result": "failure"}, ["a"]
            )
        )


class PublishReleaseTest(_FakeGhCase):
    SCRIPT = _step_script("publish-release", "Publish the draft release")

    def test_draft_with_its_sbom_is_published(self) -> None:
        result = self.run_script(self.SCRIPT, draft=True, assets=["labelyard-1.6.1.cdx.json"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("release edit v1.6.1 --draft=false --latest", self.calls())

    def _edit_calls(self) -> list[str]:
        return [c for c in self.calls() if c.startswith("release edit")]

    def test_rerun_of_an_older_run_is_not_marked_latest(self) -> None:
        # `gh run rerun --failed` of the 1.6.1 run after 1.7.0 was published. The fake
        # list also carries a draft v99.0.0, which must not count.
        result = self.run_script(
            self.SCRIPT,
            draft=True,
            assets=["labelyard-1.6.1.cdx.json"],
            releases=("v1.7.0", "v1.6.0"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._edit_calls(), ["release edit v1.6.1 --draft=false --latest=false"])
        self.assertIn("not the highest published version (1.7.0)", result.stdout)

    def test_versions_compare_numerically_not_as_text(self) -> None:
        result = self.run_script(
            self.SCRIPT,
            draft=True,
            assets=["labelyard-1.10.0.cdx.json"],
            version="1.10.0",
            releases=("v1.9.0", "v1.6.0"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._edit_calls(), ["release edit v1.10.0 --draft=false --latest"])

    def test_highest_published_version_is_found_numerically(self) -> None:
        # As text, 1.9.0 sorts above 1.10.0 and 1.9.1 would wrongly become latest.
        result = self.run_script(
            self.SCRIPT,
            draft=True,
            assets=["labelyard-1.9.1.cdx.json"],
            version="1.9.1",
            releases=("v1.9.0", "v1.10.0"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._edit_calls(), ["release edit v1.9.1 --draft=false --latest=false"])

    def test_first_release_is_latest(self) -> None:
        result = self.run_script(
            self.SCRIPT, draft=True, assets=["labelyard-1.6.1.cdx.json"], releases=()
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._edit_calls(), ["release edit v1.6.1 --draft=false --latest"])

    def test_non_release_tags_do_not_count(self) -> None:
        result = self.run_script(
            self.SCRIPT,
            draft=True,
            assets=["labelyard-1.6.1.cdx.json"],
            releases=("v2.0.0-rc.1", "nightly", "v1.6.0"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._edit_calls(), ["release edit v1.6.1 --draft=false --latest"])

    def test_pre_release_is_never_latest(self) -> None:
        result = self.run_script(
            self.SCRIPT,
            draft=True,
            assets=["labelyard-1.7.0-rc.1.cdx.json"],
            version="1.7.0-rc.1",
            releases=("v1.6.0",),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self._edit_calls(), ["release edit v1.7.0-rc.1 --draft=false --latest=false"]
        )

    def test_draft_without_sbom_is_not_published(self) -> None:
        result = self.run_script(self.SCRIPT, draft=True, assets=[])
        self.assertEqual(result.returncode, 1)
        self.assertIn("not a draft with exactly one labelyard-1.6.1.cdx.json", result.stdout)
        self.assertFalse(any(c.startswith("release edit") for c in self.calls()))

    def test_draft_with_an_sbom_of_another_version_is_not_published(self) -> None:
        result = self.run_script(self.SCRIPT, draft=True, assets=["labelyard-1.6.0.cdx.json"])
        self.assertEqual(result.returncode, 1)
        self.assertFalse(any(c.startswith("release edit") for c in self.calls()))

    def test_already_published_release_with_sbom_is_left_alone(self) -> None:
        result = self.run_script(self.SCRIPT, draft=False, assets=["labelyard-1.6.1.cdx.json"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(c.startswith("release edit") for c in self.calls()))

    def test_published_release_without_sbom_fails(self) -> None:
        result = self.run_script(self.SCRIPT, draft=False, assets=[])
        self.assertEqual(result.returncode, 1)
        self.assertFalse(any(c.startswith("release edit") for c in self.calls()))

    def test_release_still_a_draft_after_edit_fails(self) -> None:
        result = self.run_script(
            self.SCRIPT, draft=True, assets=["labelyard-1.6.1.cdx.json"], after_draft=True
        )
        self.assertEqual(result.returncode, 1)

    def test_invalid_version_is_refused_before_gh_runs(self) -> None:
        result = self.run_script(self.SCRIPT, draft=True, assets=[], version="1.6.1\nx")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not a semantic version", result.stdout)
        self.assertEqual(self.calls(), [])


class ReleaseSbomTest(_FakeGhCase):
    SCRIPT = _step_script("release-sbom", "Attach the SBOM to the release")

    def setUp(self) -> None:
        super().setUp()
        self.sbom_dir = self.tmp / "sbom"
        self.sbom_dir.mkdir()
        (self.sbom_dir / "labelyard-1.6.1.cdx.json").write_text("{}", encoding="utf-8")

    def test_sbom_is_uploaded_to_the_draft(self) -> None:
        result = self.run_script(
            self.SCRIPT, draft=True, assets=["labelyard-1.6.1.cdx.json"], cwd=self.sbom_dir
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("release upload v1.6.1 ./labelyard-1.6.1.cdx.json --clobber", self.calls())

    def test_published_release_gets_no_upload_attempt(self) -> None:
        result = self.run_script(self.SCRIPT, draft=False, assets=[], cwd=self.sbom_dir)
        self.assertEqual(result.returncode, 1)
        self.assertIn("is not a draft", result.stdout)
        self.assertFalse(any(c.startswith("release upload") for c in self.calls()))


if __name__ == "__main__":
    unittest.main()
