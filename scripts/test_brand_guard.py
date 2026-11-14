"""Tests for scripts/brand_guard.py.

The old names are assembled from parts on purpose: this file is scanned by the
guard itself, and a literal old name would be reported as a hit.
"""

import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import brand_guard  # noqa: E402

# Old names, split so this file never contains them as one literal.
SLUG = "label-printer-" + "hub"
DISPLAY = "Label Printer " + "Hub"
CLI = "printer-" + "hub"
NICK_DASH = "Print-" + "Hub"
NICK_CAMEL = "Print" + "Hub"
NICK_FLAT = "printer" + "hub"
NICK_SPACED = "Label " + "Hub"
NICK_HYPHEN = "Label-" + "Hub"
ENV_PREFIX = "PRINTER_" + "HUB_"
ENV_OTHER = "PRINT" + "HUB_"


class BrandGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)

    def add(self, rel: str, content: str | bytes) -> None:
        target = self.root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")
        subprocess.run(["git", "add", "--", rel], cwd=self.root, check=True)

    def rules(self, rel: str | None = None) -> list[str]:
        hits = brand_guard.find_hits(self.root)
        return [h.rule for h in hits if rel is None or h.path == rel]

    # --- slug -------------------------------------------------------------

    def test_slug_hit(self) -> None:
        self.add("README.md", f"image: ghcr.io/x/{SLUG}-backend\n")
        self.assertEqual(self.rules(), ["slug"])

    def test_slug_is_case_insensitive(self) -> None:
        self.add("README.md", f"{SLUG.upper()}\n")
        self.assertEqual(self.rules(), ["slug"])

    def test_sheet_type_format_allowed(self) -> None:
        self.add("docs/formats.md", f"format `{SLUG}.sheet-type`\n")
        self.assertEqual(self.rules(), [])

    def test_sheet_type_not_a_cli_hit(self) -> None:
        # no hit of ANY rule: the cli lookbehind keeps the slug's tail out
        self.add("docs/formats.md", f"{SLUG}.sheet-type\n")
        self.assertEqual(brand_guard.find_hits(self.root), [])

    def test_slug_next_to_sheet_type_still_hit(self) -> None:
        # counter-test: only the exact format suffix is allowed
        self.add("docs/formats.md", f"{SLUG}.sheet and {SLUG}-backend\n")
        self.assertEqual(self.rules(), ["slug"])

    def test_readme_hero_lines_allowed(self) -> None:
        self.add(
            "README.md",
            f"**The self-hosted {DISPLAY} for all your labels.**\n\n"
            f"Formerly *{DISPLAY}*. See the [guide](docs/migration/labelyard.md).\n",
        )
        self.assertEqual(self.rules(), [])

    def test_readme_hero_text_elsewhere_or_changed_still_hit(self) -> None:
        # counter-test: same text in another file, or an edited sentence in the README
        self.add("docs/site/a.md", f"**The self-hosted {DISPLAY} for all your labels.**\n")
        self.add("docs/site/b.md", f"Formerly *{DISPLAY}*.\n")
        self.add("README.md", f"The self-hosted {DISPLAY} for all your labels, and more.\n")
        hits = sorted(h.path for h in brand_guard.find_hits(self.root))
        self.assertEqual(hits, ["README.md", "docs/site/a.md", "docs/site/b.md"])

    def test_slug_allowed_in_migration_guide_and_rename_adr(self) -> None:
        self.add("docs/migration/labelyard.md", f"image: ghcr.io/strausmann/{SLUG}-backend\n")
        self.add("docs/decisions/0099-rename-to-labelyard.md", f"repo strausmann/{SLUG}\n")
        self.assertEqual(self.rules(), [])

    def test_slug_still_hit_in_other_docs_and_old_adrs(self) -> None:
        # counter-test: the allowance names exactly two files, not their directories
        self.add("docs/migration/other.md", f"{SLUG}-backend\n")
        self.add("docs/site/guide.md", f"{SLUG}\n")
        self.add("docs/decisions/0099-something-else.md", f"{SLUG}\n")
        self.add("README.md", f"{SLUG}-backend\n")
        hits = {h.path for h in brand_guard.find_hits(self.root)}
        self.assertEqual(hits, {"docs/migration/other.md", "docs/site/guide.md", "README.md"})

    def test_website_upgrade_guide_may_name_the_old_names(self) -> None:
        # The site's upgrade guide (both languages) must show the old image, command and prefix,
        # and the upgrades overview links to the guide, whose slug carries the old name.
        for lang in ("", "de/"):
            base = f"website/src/content/docs/{lang}admin/upgrades/"
            self.add(
                base + "from-" + SLUG + ".md",
                f"image {SLUG}-backend, command `{CLI}`, prefix `{ENV_PREFIX}`, `{ENV_OTHER}X`\n",
            )
            self.add(base + "index.md", f"[guide](/{lang}admin/upgrades/from-{SLUG}/)\n")
        self.assertEqual(self.rules(), [])

    def test_website_allowance_is_limited_to_the_upgrade_pages(self) -> None:
        # counter-test: the old names stay hits on every other site page
        self.add("website/src/content/docs/admin/backups.md", f"{SLUG} {CLI} {ENV_PREFIX}X\n")
        self.add(
            "website/src/content/docs/admin/upgrades/index.md", f"`{CLI}` and `{ENV_PREFIX}X`\n"
        )
        rules = sorted(self.rules())
        self.assertEqual(rules, ["cli", "cli", "env-prefix", "env-prefix", "slug"])

    def test_slug_not_reported_twice(self) -> None:
        self.add("README.md", f"{SLUG}-backend\n")
        self.assertEqual(self.rules(), ["slug"])

    # --- display ----------------------------------------------------------

    def test_display_alone_is_hit(self) -> None:
        self.add("README.md", f"# {DISPLAY}\n")
        self.assertEqual(self.rules(), ["display"])

    def test_display_with_labelyard_allowed(self) -> None:
        self.add("README.md", f"# Labelyard — the self-hosted {DISPLAY}\n")
        self.assertEqual(self.rules(), [])

    def test_labelyard_on_another_line_does_not_help(self) -> None:
        self.add("README.md", f"# Labelyard\n{DISPLAY}\n")
        self.assertEqual(self.rules(), ["display"])

    def test_subtitle_phrases_allowed(self) -> None:
        lines = [
            f"tagline: msg`The self-hosted {DISPLAY} for all your labels`,",
            f'msgid "the self-hosted {DISPLAY} for all your labels"',
            f'msgstr "Der selbst gehostete {DISPLAY} für all deine Etiketten"',
            f"und der selbst gehostete {DISPLAY} für all deine Etiketten",
            f'"description": "{DISPLAY} — print labels, scan codes and watch your label printers.",',
        ]
        self.add("frontend/x.ts", "\n".join(lines) + "\n")
        self.assertEqual(self.rules(), [])

    def test_changed_subtitle_phrase_is_hit(self) -> None:
        for i, line in enumerate(
            (
                f"The self-hosted {DISPLAY} for labels",
                f"A self-hosted {DISPLAY} for all your labels",
                f"Der selbst gehostete {DISPLAY} für alle Etiketten",
                f'"description": "{DISPLAY} — print labels and scan codes.",',
                f"{DISPLAY} — print labels, scan codes and watch your label printers",
            )
        ):
            with self.subTest(line=line):
                self.add(f"frontend/changed{i}.ts", line + "\n")
                self.assertEqual(self.rules(f"frontend/changed{i}.ts"), ["display"])

    def test_subtitle_phrase_outside_the_web_app_is_hit(self) -> None:
        self.add("docs/x.md", f"The self-hosted {DISPLAY} for all your labels\n")
        self.assertEqual(self.rules(), ["display"])

    def test_bare_name_next_to_subtitle_phrase_is_hit(self) -> None:
        self.add("frontend/x.ts", f"{DISPLAY}: The self-hosted {DISPLAY} for all your labels\n")
        self.assertEqual(self.rules(), ["display"])

    # --- nickname ---------------------------------------------------------

    def test_nicknames_are_hits(self) -> None:
        for nick in (NICK_DASH, NICK_CAMEL, NICK_FLAT, NICK_SPACED, NICK_HYPHEN):
            with self.subTest(nick=nick):
                self.add("docs/a.md", f"call it {nick} here\n")
                self.assertEqual(self.rules(), ["nickname"])

    def test_header_name_allowed(self) -> None:
        self.add("docs/api.md", "send X-Label-Hub-Key: abc\n")
        self.assertEqual(self.rules(), [])

    def test_bare_hyphenated_nickname_is_hit(self) -> None:
        # counter-test: proves the header allowance is load-bearing
        self.add("docs/api.md", f"the {NICK_HYPHEN} repo\n")
        self.assertEqual(self.rules(), ["nickname"])

    def test_header_name_does_not_shield_other_nickname(self) -> None:
        self.add("docs/api.md", f"X-Label-Hub-Key and {NICK_DASH}\n")
        self.assertEqual(self.rules(), ["nickname"])

    # --- cli --------------------------------------------------------------

    def test_cli_hit(self) -> None:
        self.add("docs/run.md", f"{CLI} admin create-key\n")
        self.assertEqual(self.rules(), ["cli"])

    def test_db_file_allowed(self) -> None:
        self.add("docs/run.md", f"/data/{CLI}.db\n")
        self.assertEqual(self.rules(), [])

    def test_cli_allowed_in_legacy_file(self) -> None:
        self.add("backend/pyproject.toml", f'{CLI} = "app.cli:main"\n')
        self.assertEqual(self.rules(), [])

    # --- env --------------------------------------------------------------

    def test_env_prefix_hit_outside_legacy_file(self) -> None:
        self.add("docs/run.md", f"{ENV_PREFIX}SECRET_KEY=x\n")
        self.assertEqual(self.rules(), ["env-prefix"])

    def test_env_prefix_allowed_in_legacy_file(self) -> None:
        self.add("backend/app/config_legacy.py", f'P = "{ENV_PREFIX}"\n')
        self.assertEqual(self.rules(), [])

    def test_env_prefix_allowed_in_rename_adr_by_glob(self) -> None:
        self.add("docs/decisions/0031-rename-to-labelyard.md", f"{ENV_PREFIX}X\n")
        self.assertEqual(self.rules(), [])

    def test_moved_migration_guide_keeps_only_the_slug_allowance(self) -> None:
        # The guide moved to the website; the pointer at its old path may name the guide's slug
        # (in the link), but no longer the old prefix or command.
        self.add("docs/migration/labelyard.md", f"{ENV_PREFIX}X {CLI}\n")
        self.assertEqual(sorted(self.rules()), ["cli", "env-prefix"])

    def test_env_other_hit_and_legacy_allowed(self) -> None:
        self.add("docs/run.md", f"{ENV_OTHER}X=1\n")
        self.add("backend/app/page_render/pdf.py", f"{ENV_OTHER}FONT\n")
        self.assertEqual(self.rules("docs/run.md"), ["env-other"])
        self.assertEqual(self.rules("backend/app/page_render/pdf.py"), [])

    def test_legacy_env_file_still_checked_for_other_rules(self) -> None:
        # counter-test: the env allowance is per rule, not per file
        self.add("backend/app/config_legacy.py", f"# {DISPLAY}\n")
        self.assertEqual(self.rules(), ["display"])

    # --- exclusions -------------------------------------------------------

    def test_history_excluded(self) -> None:
        for rel in (
            "CHANGELOG.md",
            "docs/decisions/0007-image-name.md",
            "docs/decisions/0024-something.md",
            "docs/superpowers/plans/x.md",
            "docs/plans/x.md",
            "docs/designs/x.md",
            "docs/research/x.md",
            "docs/migration/v-next-single-container.md",
            "frontend/pnpm-lock.yaml",
            "docs/glossary.toml",
            ".vale/styles/Labelyard/OldName.yml",
            ".vale/styles/config/vocabularies/Labelyard/reject.txt",
            "scripts/fixtures/vale/bad.md",
        ):
            with self.subTest(rel=rel):
                self.add(rel, f"{DISPLAY} {SLUG}\n")
        self.assertEqual(brand_guard.find_hits(self.root), [])

    def test_rename_adr_not_excluded(self) -> None:
        # the number is deliberately not 0025: the rule is by file name
        self.add("docs/decisions/0031-rename-to-labelyard.md", f"{DISPLAY}\n")
        self.assertEqual(self.rules(), ["display"])

    def test_unnumbered_decisions_file_not_excluded(self) -> None:
        self.add("docs/decisions/README.md", f"{DISPLAY}\n")
        self.assertEqual(self.rules(), ["display"])

    def test_non_history_docs_not_excluded(self) -> None:
        self.add("docs/migration/other.md", f"{DISPLAY}\n")
        self.add("docs/other/CHANGELOG.md", f"{DISPLAY}\n")
        self.assertEqual(len(brand_guard.find_hits(self.root)), 2)

    def test_binary_file_skipped(self) -> None:
        self.add("logo.png", b"\x89PNG\x00\x00" + SLUG.encode())
        self.assertEqual(brand_guard.find_hits(self.root), [])

    # --- hit format and exit code -----------------------------------------

    def test_hit_carries_position_and_text(self) -> None:
        self.add("a/b.md", f"ok\nsecond {DISPLAY} line\n")
        (hit,) = brand_guard.find_hits(self.root)
        self.assertEqual((hit.path, hit.line, hit.rule), ("a/b.md", 2, "display"))
        self.assertIn(DISPLAY, hit.text)

    def test_one_hit_per_line_and_rule(self) -> None:
        self.add("a.md", f"{DISPLAY} {DISPLAY}\n")
        self.assertEqual(len(brand_guard.find_hits(self.root)), 1)

    def test_exit_code(self) -> None:
        self.add("README.md", "# Labelyard\n")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(brand_guard.main(["--root", str(self.root)]), 0)
        self.assertEqual(out.getvalue(), "")
        self.add("docs/x.md", f"{DISPLAY}\n")
        with redirect_stdout(out):
            self.assertEqual(brand_guard.main(["--root", str(self.root)]), 1)
        self.assertRegex(out.getvalue(), r"^docs/x\.md:1: display: ")

    def test_missing_git_repo_exits_2(self) -> None:
        with tempfile.TemporaryDirectory() as plain:
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = brand_guard.main(["--root", plain])
        self.assertEqual(code, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(len(err.getvalue().strip().splitlines()), 1)
        self.assertIn("brand_guard: error:", err.getvalue())


if __name__ == "__main__":
    unittest.main()
