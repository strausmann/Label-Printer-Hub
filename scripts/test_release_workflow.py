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
# (comma-separated asset names) and `api .../releases/tags/...` from GH_FAKE_AFTER,
# applies the --jq filter with jq, and appends every call to GH_FAKE_LOG.
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
    case "$1 $2" in
      "release view")
        doc=$(python3 -c 'import json, os
    names = [n for n in os.environ.get("GH_FAKE_ASSETS", "").split(",") if n]
    print(json.dumps({"isDraft": os.environ["GH_FAKE_DRAFT"] == "true",
                      "assets": [{"name": n} for n in names]}))')
        ;;
      "api "*)
        doc=$(python3 -c 'import json, os
    print(json.dumps({"draft": os.environ.get("GH_FAKE_AFTER", "false") == "true", "immutable": True}))')
        ;;
      "release edit"|"release upload")
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

    def run_script(self, script: str, *, draft: bool, assets: list[str], after_draft: bool = False,
                   version: str = "1.6.1", cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
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
        }
        return subprocess.run(["bash", "-c", script], cwd=cwd or self.tmp, env=env,
                              capture_output=True, text=True, check=False)

    def calls(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines()


class ConfigTest(unittest.TestCase):
    def test_github_plugin_creates_a_draft(self) -> None:
        cfg = json.loads(RELEASERC.read_text(encoding="utf-8"))
        github = [p for p in cfg["plugins"] if isinstance(p, list) and p[0] == "@semantic-release/github"]
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
        # recovery instructions printed by images-missing do not count.
        publishers = []
        for workflow in sorted(WORKFLOWS.glob("*.yml")):
            jobs = yaml.safe_load(workflow.read_text(encoding="utf-8")).get("jobs", {})
            for name, job in jobs.items():
                for step in job.get("steps", []):
                    for line in step.get("run", "").splitlines():
                        if "--draft=false" in line and not line.lstrip().startswith("echo"):
                            publishers.append(f"{workflow.name}:{name}")
        self.assertEqual(publishers, ["release.yml:publish-release"])


class PublishReleaseTest(_FakeGhCase):
    SCRIPT = _step_script("publish-release", "Publish the draft release")

    def test_draft_with_its_sbom_is_published(self) -> None:
        result = self.run_script(self.SCRIPT, draft=True, assets=["labelyard-1.6.1.cdx.json"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("release edit v1.6.1 --draft=false --latest", self.calls())

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
        result = self.run_script(self.SCRIPT, draft=True, assets=["labelyard-1.6.1.cdx.json"], after_draft=True)
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
        result = self.run_script(self.SCRIPT, draft=True, assets=["labelyard-1.6.1.cdx.json"], cwd=self.sbom_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("release upload v1.6.1 ./labelyard-1.6.1.cdx.json --clobber", self.calls())

    def test_published_release_gets_no_upload_attempt(self) -> None:
        result = self.run_script(self.SCRIPT, draft=False, assets=[], cwd=self.sbom_dir)
        self.assertEqual(result.returncode, 1)
        self.assertIn("is not a draft", result.stdout)
        self.assertFalse(any(c.startswith("release upload") for c in self.calls()))


if __name__ == "__main__":
    unittest.main()
