"""Tests for the helpers of the release-tools workflow.

- scripts/release_tools_scope.sh decides whether the dry run is needed.
- scripts/release_dry_run.sh must never hand a token or CI variable to semantic-release
  and must remove its temp directory.

Both are checked by running the real scripts. The dry run uses a stand-in for
semantic-release (installed under a copy of the repository layout) that records the
environment it was started with, so the test needs neither node nor network.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

SCRIPTS = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS.parent

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


def _git(cwd: Path, *args: str) -> str:
    env = {**os.environ, **GIT_ENV}
    out = subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


class ScopeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)
        _git(self.repo, "init", "-q", "-b", "main")
        self._commit({"README.md": "x\n"})
        self.base = _git(self.repo, "rev-parse", "HEAD")

    def _commit(self, files: dict[str, str]) -> str:
        for name, text in files.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            _git(self.repo, "add", name)
        _git(self.repo, "commit", "-q", "-m", "change")
        return _git(self.repo, "rev-parse", "HEAD")

    def _scope(self, base: str, head: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(SCRIPTS / "release_tools_scope.sh"), base, head],
            cwd=self.repo,
            env={**os.environ, **GIT_ENV},
            capture_output=True,
            text=True,
        )

    def test_unrelated_change_is_not_touched(self) -> None:
        head = self._commit({"backend/app/x.py": "x = 1\n", "docs/a.md": "a\n"})
        result = self._scope(self.base, head)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "false"))

    def test_every_listed_path_is_touched(self) -> None:
        listed = [
            ".github/release-tools/package-lock.json",
            ".github/release-tools/package.json",
            ".github/workflows/release-tools.yml",
            ".releaserc.json",
            "scripts/release_dry_run.sh",
            "scripts/release_impact.py",
            "scripts/release_tools_scope.sh",
            "scripts/test_release_impact.py",
        ]
        for name in listed:
            with self.subTest(path=name):
                head = self._commit({name: f"changed {name}\n"})
                result = self._scope(self.base, head)
                self.assertEqual(result.stdout.strip(), "true", name)
                self.base = head

    def test_similar_paths_outside_the_list_are_not_touched(self) -> None:
        head = self._commit(
            {
                "scripts/release_impact_notes.py": "x\n",
                ".github/workflows/ci.yml": "x\n",
                "docs/.releaserc.json": "x\n",
            }
        )
        self.assertEqual(self._scope(self.base, head).stdout.strip(), "false")

    def test_any_commit_in_the_range_counts(self) -> None:
        self._commit({".releaserc.json": "{}\n"})
        head = self._commit({"docs/a.md": "a\n"})
        self.assertEqual(self._scope(self.base, head).stdout.strip(), "true")

    def test_unknown_or_empty_base_counts_as_touched(self) -> None:
        head = self._commit({"docs/a.md": "a\n"})
        for base in ("", "0" * 40, "f" * 40):
            with self.subTest(base=base):
                result = self._scope(base, head)
                self.assertEqual((result.returncode, result.stdout.strip()), (0, "true"))

    def test_diff_failure_counts_as_touched(self) -> None:
        # Resolvable base, unresolvable head: git diff fails; the check must not pass silently.
        result = self._scope(self.base, "f" * 40)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "true"))

    def test_no_merge_base_counts_as_touched(self) -> None:
        _git(self.repo, "checkout", "-q", "--orphan", "other")
        head = self._commit({"docs/a.md": "a\n"})
        result = self._scope(self.base, head)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "true"))

    def test_rename_away_from_a_listed_path_is_touched(self) -> None:
        self.base = self._commit({"scripts/release_impact.py": "x = 1\n" * 20})
        (self.repo / "docs").mkdir()
        _git(self.repo, "mv", "scripts/release_impact.py", "docs/moved.py")
        _git(self.repo, "commit", "-q", "-m", "move")
        head = _git(self.repo, "rev-parse", "HEAD")
        self.assertEqual(self._scope(self.base, head).stdout.strip(), "true")

    def test_wrong_argument_count_fails(self) -> None:
        result = subprocess.run(
            [str(SCRIPTS / "release_tools_scope.sh"), "only-one"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage", result.stderr)


class DryRunEnvironmentTest(unittest.TestCase):
    """The dry run starts semantic-release without any token or CI variable."""

    SECRETS: ClassVar[dict[str, str]] = {
        "GITHUB_TOKEN": "ghs_dummy",
        "GH_TOKEN": "gho_dummy",
        "NPM_TOKEN": "npm_dummy",
        "GITHUB_REPOSITORY": "example/example",
        "GITHUB_ACTIONS": "true",
        "CI": "true",
    }

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name) / "repo"
        (root / "scripts").mkdir(parents=True)
        shutil.copy(SCRIPTS / "release_dry_run.sh", root / "scripts" / "release_dry_run.sh")
        shutil.copy(REPO_ROOT / ".releaserc.json", root / ".releaserc.json")
        self.root = root
        self.dump = Path(self._tmp.name) / "sr-env.txt"
        self.scratch = Path(self._tmp.name) / "scratch"
        self.scratch.mkdir()
        bin_dir = root / ".github" / "release-tools" / "node_modules" / ".bin"
        bin_dir.mkdir(parents=True)
        fake = bin_dir / "semantic-release"
        fake.write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\n"
            'env > "$SR_ENV_DUMP"\n'
            # semantic-release fetches the remote's HEAD first; a bare remote whose HEAD
            # points at a branch that was never pushed makes that fail (seen on CI, where
            # init.defaultBranch is not set).
            "url=$(python3 -c \"import json;print(json.load(open('.releaserc.json'))"
            "['repositoryUrl'])\")\n"
            'git fetch --tags -- "$url"\n'
            'echo "[semantic-release] The next release version is 1.0.1"\n',
            encoding="utf-8",
        )
        fake.chmod(0o755)

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            **GIT_ENV,
            **self.SECRETS,
            "SR_ENV_DUMP": str(self.dump),
            # A git without init.defaultBranch, like a CI runner: new repositories get `master`.
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "init.defaultBranch",
            "GIT_CONFIG_VALUE_0": "master",
            "TMPDIR": str(self.scratch),
        }
        return subprocess.run(
            [str(self.root / "scripts" / "release_dry_run.sh"), *args],
            env=env,
            capture_output=True,
            text=True,
        )

    def test_tokens_and_ci_variables_do_not_reach_semantic_release(self) -> None:
        result = self._run("fix: x")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1.0.1")
        seen = {line.split("=", 1)[0] for line in self.dump.read_text().splitlines()}
        self.assertIn("SR_ENV_DUMP", seen)  # the dump is the real environment, not empty
        for name in self.SECRETS:
            self.assertNotIn(name, seen, f"{name} reached semantic-release")

    def test_remote_head_follows_the_pushed_branch(self) -> None:
        result = self._run("fix: x")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_temp_dir_is_removed_on_success(self) -> None:
        self.assertEqual(self._run("fix: x").returncode, 0)
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_temp_dir_is_removed_on_failure(self) -> None:
        fake = self.root / ".github/release-tools/node_modules/.bin/semantic-release"
        fake.write_text("#!/usr/bin/env bash\necho boom >&2\nexit 1\n", encoding="utf-8")
        result = self._run("fix: x")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("boom", result.stderr)
        self.assertEqual(list(self.scratch.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
