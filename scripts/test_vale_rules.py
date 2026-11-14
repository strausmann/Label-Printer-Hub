# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Counter-tests of the Vale rules: a planted rejected term must fail, a planted warning must not.

Runs the pinned Vale from .vale/bin/vale (scripts/vale_setup.sh); skipped when it is not installed.
The old product names are assembled from parts: scripts/brand_guard.py scans this file.
"""

import json
import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VALE = ROOT / ".vale" / "bin" / "vale"
OLD_DISPLAY = "Label Printer " + "Hub"
OLD_CLI = "printer-" + "hub"
DE_DIR = ROOT / "website" / "src" / "content" / "docs" / "de" / "using"
EN_DIR = ROOT / "website" / "src" / "content" / "docs" / "using"


def vale(path: Path, level: str) -> tuple[int, dict[str, list[str]]]:
    """Run Vale on one file; return (exit code, {check: [matches]})."""
    proc = subprocess.run(
        [str(VALE), "--output=JSON", f"--minAlertLevel={level}", str(path.relative_to(ROOT))],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    checks: dict[str, list[str]] = {}
    for alerts in json.loads(proc.stdout or "{}").values():
        for alert in alerts:
            checks.setdefault(alert["Check"], []).append(alert["Match"])
    return proc.returncode, checks


# Locally the tests are skipped without Vale; under CI (the variable is set) a missing Vale is a
# failure, so a workflow edit cannot turn the counter-tests into a silent no-op.
@unittest.skipUnless(VALE.is_file() or os.environ.get("CI"), "run scripts/vale_setup.sh first")
class ValeRuleTests(unittest.TestCase):
    def test_vale_is_installed(self) -> None:
        self.assertTrue(VALE.is_file(), "Vale is missing: run scripts/vale_setup.sh")

    def append_to_real_page(self, rel: str, text: str) -> Path:
        """Append to a tracked page for one test and restore it afterwards."""
        path = ROOT / rel
        original = path.read_bytes()
        self.addCleanup(path.write_bytes, original)
        path.write_bytes(original + text.encode("utf-8"))
        return path

    def plant(self, directory: Path, name: str, body: str) -> Path:
        path = directory / name
        path.write_text(
            "---\ntitle: Counter test\ndescription: A planted page.\n---\n\n" + body,
            encoding="utf-8",
        )
        self.addCleanup(path.unlink)
        return path

    def test_fixture_with_old_names_fails_with_both_error_rules(self) -> None:
        code, checks = vale(ROOT / "scripts" / "fixtures" / "vale" / "rejected-term.md", "error")
        self.assertEqual(code, 1)
        self.assertIn("Vale.Avoid", checks)
        self.assertIn("Labelyard.OldName", checks)

    def test_old_display_name_next_to_the_new_name_is_allowed(self) -> None:
        path = self.plant(
            EN_DIR,
            "zz-subtitle.md",
            f"Labelyard, the self-hosted {OLD_DISPLAY} for all your labels.\n",
        )
        self.assertEqual(vale(path, "error"), (0, {}))

    def test_old_display_name_alone_and_in_code_is_judged_correctly(self) -> None:
        alone = self.plant(EN_DIR, "zz-alone.md", f"The tool was called {OLD_DISPLAY} once.\n")
        self.assertEqual(vale(alone, "error")[1].get("Labelyard.OldName"), [OLD_DISPLAY])
        code = self.plant(
            EN_DIR, "zz-code.md", f"Run `{OLD_DISPLAY}` or:\n\n```\n{OLD_DISPLAY}\n```\n"
        )
        self.assertEqual(vale(code, "error"), (0, {}))

    def test_german_rejected_term_is_an_error(self) -> None:
        path = self.plant(DE_DIR, "zz-reject.md", "Der Druckjob läuft in der Queue.\n")
        code, checks = vale(path, "error")
        self.assertEqual(code, 1)
        self.assertEqual(sorted(checks["Vale.Labelyard-de.Avoid"]), ["Druckjob", "Queue"])

    def test_german_subtitle_and_header_name_are_allowed(self) -> None:
        body = (
            f"Labelyard, der selbst gehostete {OLD_DISPLAY}, und der Header "
            "`X-Label-Hub-Key`, auch als X-Label-Hub-Key.\n"
        )
        self.assertEqual(vale(self.plant(DE_DIR, "zz-subtitle.md", body), "error"), (0, {}))

    def test_rejected_word_inside_a_longer_word_is_not_a_hit(self) -> None:
        path = self.plant(DE_DIR, "zz-substring.md", "Die Jobsuche und das Labelyard-Etikett.\n")
        self.assertEqual(vale(path, "error"), (0, {}))

    def test_english_old_cli_name_is_an_error(self) -> None:
        path = self.plant(EN_DIR, "zz-cli.md", f"Run the {OLD_CLI} command.\n")
        self.assertEqual(vale(path, "error")[1].get("Vale.Avoid"), [OLD_CLI])

    def test_rejected_german_terms_in_the_body_of_the_two_subtitle_pages_are_errors(self) -> None:
        # These pages carry the subtitle in their front matter; the rule must not be off for the
        # body, which an earlier `Avoid = NO` section had done.
        for rel in (
            "website/src/content/docs/de/index.mdx",
            "website/src/content/docs/de/admin/upgrades/from-label-printer-" + "hub.md",
        ):
            with self.subTest(page=rel):
                path = self.append_to_real_page(rel, "\nDer Druckjob liegt in der Queue.\n")
                code, checks = vale(path, "error")
                self.assertEqual(code, 1)
                self.assertEqual(sorted(checks["Vale.Labelyard-de.Avoid"]), ["Druckjob", "Queue"])

    def test_german_label_is_an_error_except_on_exempt_lines_and_in_code(self) -> None:
        path = self.plant(DE_DIR, "zz-label.md", "Das Label klebt.\n\nEin `Label` im Code.\n")
        self.assertEqual(vale(path, "error")[1], {"Labelyard-de.Label": ["Label"]})
        front = self.append_to_real_page(
            "website/src/content/docs/de/index.mdx", "\nDas Label hängt.\n"
        )
        self.assertEqual(vale(front, "error")[1], {"Labelyard-de.Label": ["Label"]})

    def test_tagline_and_formerly_sentence_are_allowed_in_the_readme_only(self) -> None:
        tagline = f"**The self-hosted {OLD_DISPLAY} for all your labels.**\n"
        formerly = f"Formerly *{OLD_DISPLAY}*. See the guide.\n"
        # Elsewhere both are errors.
        other = self.plant(EN_DIR, "zz-tagline.md", tagline + "\n" + formerly)
        self.assertEqual(vale(other, "error")[1], {"Labelyard.OldName": [OLD_DISPLAY] * 2})
        # In the README they are allowed, but the rest of a "Formerly" line is not.
        readme = ROOT / "README.md"
        self.assertEqual(vale(readme, "error"), (0, {}))
        planted = self.append_to_real_page(
            "README.md", f"\nFormerly *{OLD_DISPLAY}*. Also {OLD_DISPLAY}.\n"
        )
        self.assertEqual(vale(planted, "error")[1], {"LabelyardReadme.OldName": [OLD_DISPLAY]})

    def test_long_sentences_and_fillers_are_warnings_only(self) -> None:
        sentence = " ".join(["one", "two"] * 20) + ". It is simply done."
        path = self.plant(EN_DIR, "zz-long.md", sentence + "\n")
        self.assertEqual(vale(path, "error"), (0, {}))
        code, checks = vale(path, "warning")
        self.assertEqual(code, 0)  # warnings do not fail the run
        self.assertIn("Labelyard.SentenceLength", checks)
        self.assertIn("Labelyard.Filler", checks)

    def test_german_long_sentence_is_a_warning_only(self) -> None:
        path = self.plant(DE_DIR, "zz-long.md", " ".join(["eins", "zwei"] * 20) + ".\n")
        self.assertEqual(vale(path, "error"), (0, {}))
        self.assertIn("Labelyard-de.SentenceLength", vale(path, "warning")[1])

    def test_rejected_german_term_also_gets_the_substitution_warning(self) -> None:
        path = self.plant(DE_DIR, "zz-terms.md", "Das Label klebt.\n")
        self.assertEqual(vale(path, "warning")[1].get("Labelyard-de.Terms"), ["Label"])


if __name__ == "__main__":
    unittest.main()
