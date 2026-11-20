# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for scripts/licence_snapshot.py.

Run with: python3 -m unittest discover -s scripts -p 'test_*.py' -v
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import licence_snapshot as ls

BACKEND = [
    {"name": "packbits", "version": "0.4.0", "license": "MIT", "licenseText": "x"},
    {"name": "brother-ql-next", "version": "0.12.0", "license": "GPL-3.0-only"},
]
FRONTEND = [
    {"name": "react", "version": "19.0.0", "license": "MIT", "licenseText": "y"},
    {"name": "@scope/pkg", "version": "1.0.0", "license": "Apache-2.0"},
]
SNAPSHOT = {
    "@scope/pkg": "Apache-2.0",
    "brother-ql-next": "GPL-3.0-only",
    "packbits": "MIT",
    "react": "MIT",
}


class SnapshotCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.snapshot = self.dir / "snapshot.json"

    def write(self, name: str, data: object) -> Path:
        path = self.dir / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def write_snapshot(self, packages: dict[str, str]) -> None:
        self.snapshot.write_text(json.dumps({"packages": packages}), encoding="utf-8")

    def run_cli(self, *args: str, env: dict[str, str] | None = None) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.dict(os.environ, env or {}, clear=False),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            code = ls.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def lists(self, backend: list[dict], frontend: list[dict]) -> list[str]:
        return [
            "--backend",
            str(self.write("backend.json", backend)),
            "--frontend",
            str(self.write("frontend.json", frontend)),
            "--snapshot",
            str(self.snapshot),
        ]


class CheckTest(SnapshotCase):
    def test_unchanged_lists_pass(self) -> None:
        self.write_snapshot(SNAPSHOT)
        code, out, _ = self.run_cli("check", *self.lists(BACKEND, FRONTEND))
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")

    def test_a_changed_licence_fails_with_name_old_and_new(self) -> None:
        self.write_snapshot(SNAPSHOT)
        changed = [dict(BACKEND[0], license="Apache-2.0"), BACKEND[1]]
        code, out, _ = self.run_cli("check", *self.lists(changed, FRONTEND))
        self.assertEqual(code, 1)
        self.assertEqual(out.strip().splitlines(), ["packbits: MIT → Apache-2.0"])

    def test_a_new_package_is_reported(self) -> None:
        self.write_snapshot(SNAPSHOT)
        extra = [*BACKEND, {"name": "newpkg", "version": "1.0", "license": "BSD-3-Clause"}]
        code, out, _ = self.run_cli("check", *self.lists(extra, FRONTEND))
        self.assertEqual(code, 1)
        self.assertEqual(out.strip().splitlines(), ["newpkg: (new) → BSD-3-Clause"])

    def test_a_removed_package_is_reported(self) -> None:
        self.write_snapshot(SNAPSHOT)
        code, out, _ = self.run_cli("check", *self.lists(BACKEND[:1], FRONTEND))
        self.assertEqual(code, 1)
        self.assertEqual(out.strip().splitlines(), ["brother-ql-next: GPL-3.0-only → (removed)"])

    def test_versions_of_one_package_with_different_licences_are_joined(self) -> None:
        frontend = [
            *FRONTEND,
            {"name": "react", "version": "18.0.0", "license": "Apache-2.0"},
        ]
        packages = ls.read_lists(
            self.write("backend.json", BACKEND), self.write("frontend.json", frontend)
        )
        self.assertEqual(packages["react"], "Apache-2.0 / MIT")

    def test_the_summary_file_gets_the_lines(self) -> None:
        self.write_snapshot(SNAPSHOT)
        summary = self.dir / "summary.md"
        changed = [dict(BACKEND[0], license="Apache-2.0"), BACKEND[1]]
        code, _, _ = self.run_cli(
            "check", *self.lists(changed, FRONTEND), env={"GITHUB_STEP_SUMMARY": str(summary)}
        )
        self.assertEqual(code, 1)
        text = summary.read_text(encoding="utf-8")
        self.assertIn("packbits: MIT → Apache-2.0", text)

    def test_a_missing_snapshot_fails(self) -> None:
        code, _, err = self.run_cli("check", *self.lists(BACKEND, FRONTEND))
        self.assertEqual(code, 1)
        self.assertIn("snapshot", err)

    def test_a_list_without_licence_field_is_an_error(self) -> None:
        self.write_snapshot(SNAPSHOT)
        broken = [{"name": "packbits", "version": "0.4.0"}]
        code, _, err = self.run_cli("check", *self.lists(broken, FRONTEND))
        self.assertEqual(code, 2)
        self.assertIn("packbits", err)


class UpdateTest(SnapshotCase):
    def test_update_writes_sorted_output(self) -> None:
        code, _, _ = self.run_cli("update", *self.lists(BACKEND, FRONTEND))
        self.assertEqual(code, 0)
        raw = self.snapshot.read_text(encoding="utf-8")
        data = json.loads(raw)
        self.assertEqual(list(data["packages"]), sorted(data["packages"]))
        self.assertEqual(data["packages"], SNAPSHOT)
        self.assertTrue(raw.endswith("\n"))

    def test_check_passes_right_after_update(self) -> None:
        self.run_cli("update", *self.lists(BACKEND, FRONTEND))
        code, _, _ = self.run_cli("check", *self.lists(BACKEND, FRONTEND))
        self.assertEqual(code, 0)


class NotesTest(SnapshotCase):
    def test_notes_lists_the_changes_between_two_snapshots(self) -> None:
        old = self.write("old.json", {"packages": SNAPSHOT})
        new_packages = dict(SNAPSHOT, packbits="Apache-2.0", extra="MIT")
        del new_packages["react"]
        new = self.write("new.json", {"packages": new_packages})
        code, out, _ = self.run_cli("notes", "--old", str(old), "--new", str(new))
        self.assertEqual(code, 0)
        self.assertIn("## Licence changes", out)
        self.assertIn("- packbits: MIT → Apache-2.0", out)
        self.assertIn("- extra: (new) → MIT", out)
        self.assertIn("- react: MIT → (removed)", out)

    def test_notes_prints_nothing_when_nothing_changed(self) -> None:
        old = self.write("old.json", {"packages": SNAPSHOT})
        code, out, _ = self.run_cli("notes", "--old", str(old), "--new", str(old))
        self.assertEqual(code, 0)
        self.assertEqual(out, "")

    def test_notes_without_a_previous_snapshot_prints_nothing(self) -> None:
        # A first release has no previous snapshot: no section, no failure.
        new = self.write("new.json", {"packages": SNAPSHOT})
        code, out, _ = self.run_cli(
            "notes", "--old", str(self.dir / "absent.json"), "--new", str(new)
        )
        self.assertEqual(code, 0)
        self.assertEqual(out, "")


ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
SHA_PIN = re.compile(r"^[^@\s]+@[0-9a-f]{40}(\s+#.*)?$")


def _workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _runs(job: dict) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


class WorkflowWiringTest(unittest.TestCase):
    """The workflows call the tool the way these tests exercise it."""

    def test_the_image_job_runs_check_against_the_files_copied_from_the_image(self) -> None:
        script = _runs(_workflow("ci.yml")["jobs"]["docker-build"])
        self.assertIn("docker cp", script)
        self.assertIn("/opt/app/web/licenses/backend.json", script)
        self.assertIn("/opt/app/web/licenses/frontend.json", script)
        self.assertRegex(script, r"licence_snapshot\.py check --backend \S+ --frontend \S+")

    def test_the_weekly_workflow_is_scheduled_read_only_and_pinned(self) -> None:
        wf = _workflow("licence-weekly.yml")
        triggers = wf.get("on", wf.get(True))
        self.assertEqual(triggers["schedule"], [{"cron": "17 4 * * 1"}])
        self.assertIn("workflow_dispatch", triggers)
        self.assertEqual(wf["permissions"], {"contents": "read"})
        for job in wf["jobs"].values():
            for step in job["steps"]:
                if "uses" in step:
                    self.assertRegex(step["uses"], SHA_PIN)
        self.assertIn("licence_snapshot.py check", _runs(wf["jobs"]["snapshot"]))

    def test_the_release_appends_the_notes_section_to_the_draft(self) -> None:
        job = _workflow("release.yml")["jobs"]["release-sbom"]
        steps = {step.get("name"): step for step in job["steps"]}
        script = steps["Add the licence changes to the release notes"]["run"]
        self.assertIn("licence_snapshot.py notes", script)
        self.assertIn("gh release edit", script)
        self.assertNotIn("--draft=false", script)

    def test_the_scripts_job_lints_with_the_pinned_ruff(self) -> None:
        script = _runs(_workflow("ci.yml")["jobs"]["scripts"])
        self.assertRegex(script, r"ruff==\d+\.\d+\.\d+")
        self.assertIn("ruff check scripts/", script)
        self.assertIn("ruff format --check scripts/", script)


if __name__ == "__main__":
    unittest.main()
