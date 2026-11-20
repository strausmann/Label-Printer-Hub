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
        self.assertEqual(out.splitlines(), ["  - packbits: MIT → Apache-2.0"])

    def test_a_new_package_is_reported_but_does_not_fail_by_default(self) -> None:
        self.write_snapshot(SNAPSHOT)
        extra = [*BACKEND, {"name": "newpkg", "version": "1.0", "license": "BSD-3-Clause"}]
        code, out, _ = self.run_cli("check", *self.lists(extra, FRONTEND))
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), ["  - newpkg: (new) → BSD-3-Clause"])

    def test_a_new_package_fails_in_strict_mode(self) -> None:
        self.write_snapshot(SNAPSHOT)
        extra = [*BACKEND, {"name": "newpkg", "version": "1.0", "license": "BSD-3-Clause"}]
        code, out, _ = self.run_cli("check", "--strict", *self.lists(extra, FRONTEND))
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines(), ["  - newpkg: (new) → BSD-3-Clause"])

    def test_a_removed_package_is_reported_but_does_not_fail_by_default(self) -> None:
        self.write_snapshot(SNAPSHOT)
        code, out, _ = self.run_cli("check", *self.lists(BACKEND[:1], FRONTEND))
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), ["  - brother-ql-next: GPL-3.0-only → (removed)"])

    def test_a_removed_package_fails_in_strict_mode(self) -> None:
        self.write_snapshot(SNAPSHOT)
        code, _, _ = self.run_cli("check", "--strict", *self.lists(BACKEND[:1], FRONTEND))
        self.assertEqual(code, 1)

    def test_a_licence_move_next_to_a_new_package_still_fails_by_default(self) -> None:
        self.write_snapshot(SNAPSHOT)
        changed = [dict(BACKEND[0], license="Apache-2.0"), BACKEND[1]]
        extra = [*changed, {"name": "newpkg", "version": "1.0", "license": "MIT"}]
        code, out, _ = self.run_cli("check", *self.lists(extra, FRONTEND))
        self.assertEqual(code, 1)
        self.assertIn("  - newpkg: (new) → MIT", out.splitlines())

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
        self.assertIn("- `packbits`: `MIT` → `Apache-2.0`", text)

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
        self.assertIn("- `packbits`: `MIT` → `Apache-2.0`", out)
        self.assertIn("- `extra`: `(new)` → `MIT`", out)
        self.assertIn("- `react`: `MIT` → `(removed)`", out)

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


HOSTILE = "::error::pwn\n::stop-commands::x"


class HostileNameTest(SnapshotCase):
    """Names and licences come from third-party metadata and reach the runner's stdout.

    The runner reads workflow commands (``::error::``, ``::stop-commands::``) from stdout, so
    an entry that could start one is rejected outright: the run fails with exit 2 and says
    which entry. Neutralising it instead would hide a hostile package from the maintainer.
    """

    def check_rejected(self, entry: dict) -> None:
        self.write_snapshot(SNAPSHOT)
        code, out, err = self.run_cli("check", *self.lists([entry], FRONTEND))
        self.assertEqual(code, 2)
        self.assertNotIn("::", out)
        self.assertIn("error:", err)

    def test_the_reviewers_fixture_is_rejected_and_never_reaches_stdout(self) -> None:
        self.check_rejected({"name": HOSTILE, "version": "1", "license": "MIT"})

    def test_a_leading_double_colon_is_rejected(self) -> None:
        self.check_rejected({"name": "::add-mask::x", "version": "1", "license": "MIT"})

    def test_leading_whitespace_before_a_command_is_rejected(self) -> None:
        # The runner trims leading whitespace before it looks for "::", so " ::error::x" is a
        # command even though the name does not start with "::".
        for prefix in (" ", "  ", "\u2003", "\u00a0"):
            with self.subTest(prefix=repr(prefix)):
                name = f"{prefix}::error::x"
                self.check_rejected({"name": name, "version": "1", "license": "MIT"})

    def test_control_characters_in_a_name_are_rejected(self) -> None:
        for char in ("\r", "\n", "\x00", "\x1b", "\x7f", "\u2028", "\x85"):
            with self.subTest(char=repr(char)):
                self.check_rejected({"name": f"a{char}b", "version": "1", "license": "MIT"})

    def test_control_characters_in_a_licence_are_rejected(self) -> None:
        self.check_rejected({"name": "ok", "version": "1", "license": "MIT\n::error::x"})

    def test_a_hostile_name_without_a_licence_never_starts_an_output_line_with_a_command(
        self,
    ) -> None:
        # The message for a missing licence used to repeat the name before it was vetted, so a
        # line break in the name put "::error::..." at the start of a line (run-30, note 8a).
        self.write_snapshot(SNAPSHOT)
        for licence in ("", None):
            with self.subTest(licence=licence):
                entry = {"name": HOSTILE, "version": "1", "license": licence}
                code, out, err = self.run_cli("check", *self.lists([entry], FRONTEND))
                self.assertEqual(code, 2)
                for line in (out + err).splitlines():
                    self.assertFalse(line.strip().startswith("::"), line)

    def test_a_missing_licence_names_the_package_as_a_quoted_string(self) -> None:
        self.write_snapshot(SNAPSHOT)
        code, _, err = self.run_cli(
            "check", *self.lists([{"name": "plain", "version": "1", "license": ""}], FRONTEND)
        )
        self.assertEqual(code, 2)
        self.assertIn("package 'plain' has no declared licence", err)

    def test_a_hostile_snapshot_is_rejected_by_notes(self) -> None:
        good = self.write("good.json", {"packages": SNAPSHOT})
        bad = self.write("bad.json", {"packages": {HOSTILE: "MIT"}})
        code, out, err = self.run_cli("notes", "--old", str(good), "--new", str(bad))
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("error:", err)

    def test_no_line_on_stdout_starts_with_a_package_name(self) -> None:
        # Even a name the vetting lets through must sit behind a fixed prefix that the
        # runner's trimming cannot reduce to "::".
        self.write_snapshot({})
        entries = [{"name": n, "version": "1", "license": "MIT"} for n in ("a", "pkg::x", "@s/p")]
        code, out, _ = self.run_cli("check", "--strict", *self.lists(entries, []))
        self.assertEqual(code, 1)
        for line in out.splitlines():
            self.assertTrue(line.startswith("  - "), line)
            self.assertFalse(line.strip().startswith("::"), line)

    def test_a_double_colon_inside_a_name_is_fine(self) -> None:
        # Only a leading "::" can start a workflow command.
        entry = {"name": "pkg::inner", "version": "1", "license": "MIT"}
        packages = ls.read_lists(self.write("b.json", [entry]), self.write("f.json", FRONTEND))
        self.assertEqual(packages["pkg::inner"], "MIT")


class MarkdownTest(SnapshotCase):
    """Names and licences are code spans wherever markdown is written."""

    SCOPED = {"@babel/types": "MIT", "pkg[x](http://evil)": "MIT", "a_b*c": "MIT"}

    def test_code_span_uses_a_longer_fence_than_any_backtick_run_inside(self) -> None:
        self.assertEqual(ls.code_span("abc"), "`abc`")
        self.assertEqual(ls.code_span("a`b"), "``a`b``")
        self.assertEqual(ls.code_span("a``b`c"), "```a``b`c```")

    def test_code_span_pads_a_value_that_starts_or_ends_with_a_backtick(self) -> None:
        self.assertEqual(ls.code_span("`a"), "`` `a ``")
        self.assertEqual(ls.code_span("a`"), "`` a` ``")

    def test_a_backtick_cannot_break_out_of_the_span(self) -> None:
        # Parse the span the way CommonMark does: the content ends at the first run of
        # backticks that is as long as the opening fence.
        for value in ("a`b", "`", "``", "a`` b", "`x`y`"):
            with self.subTest(value=value):
                span = ls.code_span(value)
                fence = len(span) - len(span.lstrip("`"))
                body = span[fence:]
                runs = [len(r) for r in re.findall(r"`+", body)]
                self.assertEqual(runs.count(fence), 1)
                self.assertEqual(runs[-1], fence)

    def test_the_step_summary_wraps_names_and_licences(self) -> None:
        self.write_snapshot({})
        summary = self.dir / "summary.md"
        entries = [{"name": n, "version": "1", "license": lic} for n, lic in self.SCOPED.items()]
        code, out, _ = self.run_cli(
            "check", "--strict", *self.lists(entries, []), env={"GITHUB_STEP_SUMMARY": str(summary)}
        )
        self.assertEqual(code, 1)
        text = summary.read_text(encoding="utf-8")
        self.assertIn("- `@babel/types`: `(new)` → `MIT`", text)
        self.assertNotRegex(text, r"(?m)^- @")
        self.assertIn("`pkg[x](http://evil)`", text)
        # stdout stays plain: it is read by humans and by no markdown renderer.
        self.assertIn("  - @babel/types: (new) → MIT", out)

    def test_the_release_notes_wrap_names_and_licences(self) -> None:
        old = self.write("old.json", {"packages": {}})
        new = self.write("new.json", {"packages": self.SCOPED})
        code, out, _ = self.run_cli("notes", "--old", str(old), "--new", str(new))
        self.assertEqual(code, 0)
        self.assertIn("- `@babel/types`: `(new)` → `MIT`", out)
        self.assertNotRegex(out, r"(?m)^- @")

    def test_a_backtick_in_a_licence_keeps_the_release_notes_line_intact(self) -> None:
        old = self.write("old.json", {"packages": {"p": "MIT"}})
        new = self.write("new.json", {"packages": {"p": "Foo`Bar"}})
        _, out, _ = self.run_cli("notes", "--old", str(old), "--new", str(new))
        self.assertIn("- `p`: `MIT` → ``Foo`Bar``", out)


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
        # Pull requests fail on a licence move only; the weekly run is the strict one.
        self.assertNotIn("--strict", script)

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
        self.assertIn("licence_snapshot.py check --strict", _runs(wf["jobs"]["snapshot"]))

    def test_the_release_appends_the_notes_section_to_the_draft(self) -> None:
        job = _workflow("release.yml")["jobs"]["release-sbom"]
        steps = {step.get("name"): step for step in job["steps"]}
        script = steps["Add the licence changes to the release notes"]["run"]
        self.assertIn("licence_snapshot.py notes", script)
        self.assertIn("gh release edit", script)
        self.assertNotIn("--draft=false", script)

    def test_the_notes_step_fails_hard_on_a_missing_tag_and_skips_only_a_missing_file(
        self,
    ) -> None:
        job = _workflow("release.yml")["jobs"]["release-sbom"]
        steps = {step.get("name"): step for step in job["steps"]}
        script = steps["Add the licence changes to the release notes"]["run"]
        # The tag and the previous tag must resolve; neither lookup may be swallowed.
        self.assertIn('git rev-parse -q --verify "refs/tags/v${VERSION}^{commit}"', script)
        self.assertNotRegex(script, r"git describe[^\n]*\|\|\s*true")
        self.assertRegex(script, r"git describe[^\n]*\|\| \{")
        # A missing snapshot at an existing previous tag is a soft skip with one log line.
        self.assertIn('git cat-file -e "${prev}:licences/snapshot.json"', script)
        self.assertIn("::notice::", script)

    def test_the_release_sbom_comment_does_not_claim_there_is_no_checkout(self) -> None:
        text = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
        head = text.split("  release-sbom:\n", 1)[0]
        comment = head[head.rindex("# Attaches the CycloneDX SBOM") :]
        self.assertNotIn("no checkout", comment)
        self.assertIn("persist-credentials", comment)

    def test_contributing_says_where_the_update_lists_come_from(self) -> None:
        text = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        self.assertIn("licence_snapshot.py update", text)
        self.assertIn("docker cp", text)
        self.assertIn("/opt/app/web/licenses/backend.json", text)

    def test_the_scripts_job_lints_with_the_pinned_ruff(self) -> None:
        script = _runs(_workflow("ci.yml")["jobs"]["scripts"])
        self.assertRegex(script, r"ruff==\d+\.\d+\.\d+")
        self.assertIn("ruff check scripts/", script)
        self.assertIn("ruff format --check scripts/", script)


if __name__ == "__main__":
    unittest.main()
