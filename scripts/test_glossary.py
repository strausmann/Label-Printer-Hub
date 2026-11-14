# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for scripts/glossary.py.

The old product names are assembled from parts on purpose: scripts/brand_guard.py scans this
file, and a literal old name would be reported as a hit.
"""

import io
import re
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import glossary

REPO = Path(__file__).resolve().parent.parent
OLD_DISPLAY = "Label Printer " + "Hub"
OLD_CLI = "printer-" + "hub"

HEADER = "Generated from docs/glossary.toml — edit that file"


def write_toml(directory: Path, body: str) -> Path:
    path = directory / "glossary.toml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


MINIMAL = """
    [[term]]
    id = "job"
    en = "print job"
    de = "Auftrag"
    definition_en = "One request to print."
    definition_de = "Eine Anfrage zu drucken."
    reject_de = ["Job", "Druckjob"]

    [[term]]
    id = "label"
    en = "label"
    de = "Etikett"
    definition_en = "What gets printed."
    definition_de = "Das, was gedruckt wird."
    reject_de = ["Label"]
    exempt = ["X-Label-Hub-Key"]
"""


def po(msgstr: str) -> str:
    return f'msgid "x"\nmsgstr "{msgstr}"\n'


class LoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_every_term_has_both_languages(self) -> None:
        for missing in ("de", "definition_de", "en", "definition_en"):
            with self.subTest(missing=missing):
                body = MINIMAL.replace(f"\n    {missing} = ", f"\n    x_{missing} = ", 1)
                path = write_toml(self.dir, body)
                with self.assertRaises(glossary.GlossaryError) as ctx:
                    glossary.load_glossary(path)
                self.assertIn("job", str(ctx.exception))
                self.assertIn(missing, str(ctx.exception))

    def test_duplicate_id_is_rejected(self) -> None:
        path = write_toml(self.dir, MINIMAL + MINIMAL)
        with self.assertRaises(glossary.GlossaryError) as ctx:
            glossary.load_glossary(path)
        self.assertIn("duplicate", str(ctx.exception))

    def test_unknown_key_is_rejected(self) -> None:
        path = write_toml(
            self.dir, MINIMAL.replace('reject_de = ["Label"]', 'rejekt_de = ["Label"]')
        )
        with self.assertRaises(glossary.GlossaryError) as ctx:
            glossary.load_glossary(path)
        self.assertIn("rejekt_de", str(ctx.exception))

    def test_loads_the_real_glossary(self) -> None:
        terms = glossary.load_glossary(REPO / "docs" / "glossary.toml")
        ids = [t.id for t in terms]
        for wanted in (
            "sheet",
            "cell",
            "sheet-type",
            "inbox",
            "tape",
            "roll",
            "template",
            "printer",
            "tray",
            "calibration",
            "preview",
            "job",
            "batch",
            "queue",
            "label",
            "api-key",
        ):
            self.assertIn(wanted, ids)
        by_id = {t.id: t for t in terms}
        self.assertEqual(by_id["inbox"].de, "Druckeingang")
        self.assertEqual(by_id["job"].reject_de, ("Job", "Druckjob"))
        self.assertEqual(by_id["roll"].de, "Rolle")


class RenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.terms = glossary.load_glossary(write_toml(Path(self._tmp.name), MINIMAL))

    def test_rendered_glossary_pages_pair(self) -> None:
        en = glossary.render(self.terms, "glossary-en")
        de = glossary.render(self.terms, "glossary-de")
        ids = lambda page: re.findall(r'<a id="([^"]+)"></a>', page)  # noqa: E731
        self.assertEqual(ids(en), ids(de))
        self.assertEqual(len(ids(en)), 2)
        self.assertIn("print job", en)
        self.assertIn("Auftrag", de)
        self.assertIn(HEADER, en)
        self.assertIn(HEADER, de)

    def test_pages_name_rejected_terms_only_as_code(self) -> None:
        de = glossary.render(self.terms, "glossary-de")
        self.assertIn("`Job`", de)
        self.assertNotIn(" Job ", de.replace("`Job`", ""))

    def test_reject_list_written(self) -> None:
        reject = glossary.render(self.terms, "reject-de")
        entries = [ln for ln in reject.splitlines() if ln and not ln.startswith("#")]
        # "Label" has exemptions: it is enforced by the line-aware rule, not by reject.txt.
        self.assertEqual(entries, ["Job", "Druckjob"])
        self.assertIn(HEADER, reject)
        self.assertEqual(
            [
                ln
                for ln in glossary.render(self.terms, "reject-en").splitlines()
                if ln and not ln.startswith("#")
            ],
            [],
        )

    def test_term_with_exemptions_gets_a_line_aware_rule(self) -> None:
        rule = glossary.render(self.terms, "vale-exempt-de")
        self.assertIn("extends: script", rule)
        self.assertIn("level: error", rule)
        self.assertIn(glossary.GENERATED, rule)
        self.assertIn("(?:Label)", rule)
        self.assertIn('"X-Label-Hub-Key"', rule)
        self.assertNotIn('"Job"', rule)  # terms without exemptions stay in reject.txt

    def test_accept_list_has_the_canonical_terms(self) -> None:
        accept = glossary.render(self.terms, "accept-de")
        entries = [ln for ln in accept.splitlines() if ln and not ln.startswith("#")]
        # Anchored: an unanchored "printer" would also exempt a rejected word that contains it.
        self.assertEqual(entries, ["^Auftrag$", "^Etikett$"])

    def test_vale_terms_maps_rejected_to_canonical(self) -> None:
        yml = glossary.render(self.terms, "vale-terms-de")
        self.assertIn("extends: substitution", yml)
        self.assertIn("level: warning", yml)
        self.assertIn('  "Job": "Auftrag"', yml)
        self.assertIn('  "Label": "Etikett"', yml)
        self.assertIn(HEADER, yml)

    def test_unknown_target_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            glossary.render(self.terms, "nope")  # type: ignore[arg-type]


class CatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.terms = glossary.load_glossary(write_toml(self.dir, MINIMAL))

    def hits(self, msgstr: str, lang: str = "de") -> list[str]:
        path = self.dir / "messages.po"
        path.write_text(po(msgstr), encoding="utf-8")
        return [h.term_id for h in glossary.check_catalog(self.terms, path, lang)]

    def test_catalog_check_flags_rejected(self) -> None:
        self.assertEqual(self.hits("Der Job läuft"), ["job"])

    def test_catalog_check_ignores_substrings(self) -> None:
        self.assertEqual(self.hits("Die Jobsuche"), [])
        self.assertEqual(self.hits("Der Header X-Label-Hub-Key"), [])
        self.assertEqual(self.hits("Das Etikett"), [])

    def test_catalog_check_ignores_placeholders(self) -> None:
        self.assertEqual(self.hits("{Label} ist zu lang"), [])
        self.assertEqual(self.hits("{label} ist zu lang"), [])
        self.assertEqual(self.hits("{Labels, plural, one {# Etikett} other {# Etiketten}}"), [])

    def test_catalog_check_reads_continuation_lines(self) -> None:
        path = self.dir / "messages.po"
        path.write_text('msgid "x"\nmsgstr ""\n"Der "\n"Job läuft"\n', encoding="utf-8")
        self.assertEqual(
            [h.term_id for h in glossary.check_catalog(self.terms, path, "de")], ["job"]
        )

    def test_catalog_check_skips_obsolete_and_header(self) -> None:
        path = self.dir / "messages.po"
        path.write_text(
            'msgid ""\nmsgstr "Job"\n\n#~ msgid "x"\n#~ msgstr "Job"\n', encoding="utf-8"
        )
        self.assertEqual(glossary.check_catalog(self.terms, path, "de"), [])

    def test_english_catalogue_uses_reject_en(self) -> None:
        self.assertEqual(self.hits("Job", "en"), [])

    def test_product_terms_are_not_part_of_the_catalog_check(self) -> None:
        body = (
            MINIMAL
            + f"""
    [[term]]
    id = "product"
    product = true
    en = "Labelyard"
    de = "Labelyard"
    definition_en = "The product."
    definition_de = "Das Produkt."
    reject_en = ["{OLD_CLI}"]
    reject_de = ["{OLD_CLI}"]
    old_names = ["{OLD_DISPLAY}"]
"""
        )
        terms = glossary.load_glossary(write_toml(self.dir, body))
        path = self.dir / "messages.po"
        path.write_text(po(OLD_CLI), encoding="utf-8")
        self.assertEqual(glossary.check_catalog(terms, path, "de"), [])
        # ...but the reject list carries them, and the substitution map does not.
        self.assertIn(OLD_CLI, glossary.render(terms, "reject-de"))
        self.assertNotIn(OLD_CLI, glossary.render(terms, "vale-terms-de"))
        self.assertNotIn(OLD_DISPLAY, glossary.render(terms, "reject-de"))
        self.assertNotIn(OLD_CLI, glossary.render(terms, "glossary-de"))


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "docs").mkdir()
        write_toml(self.root / "docs", MINIMAL)

    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = glossary.main(["--root", str(self.root), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_write_then_check_is_clean_and_drift_is_found(self) -> None:
        code, _, _ = self.run_cli("write")
        self.assertEqual(code, 0)
        for rel in glossary.OUTPUTS.values():
            self.assertTrue((self.root / rel).is_file(), rel)
        self.assertEqual(self.run_cli("write", "--check")[0], 0)
        target = self.root / glossary.OUTPUTS["reject-de"]
        target.write_text(target.read_text(encoding="utf-8") + "Extra\n", encoding="utf-8")
        code, _, err = self.run_cli("write", "--check")
        self.assertEqual(code, 1)
        self.assertIn(glossary.OUTPUTS["reject-de"], err)

    def test_check_catalog_exit_codes(self) -> None:
        (self.root / "locales" / "de").mkdir(parents=True)
        good = self.root / "locales" / "de" / "good.po"
        good.write_text(po("Der Auftrag läuft"), encoding="utf-8")
        bad = self.root / "locales" / "de" / "bad.po"
        bad.write_text(po("Der Job läuft"), encoding="utf-8")
        self.assertEqual(self.run_cli("check-catalog", str(good))[0], 0)
        code, out, err = self.run_cli("check-catalog", str(bad))
        self.assertEqual(code, 1)
        self.assertIn("job", out + err)
        self.assertIn("Auftrag", out + err)

    def test_catalog_language_comes_from_the_path(self) -> None:
        self.assertEqual(glossary.catalog_language(Path("a/locales/de/messages.po")), "de")
        self.assertEqual(glossary.catalog_language(Path("a/locales/en/messages.po")), "en")
        with self.assertRaises(ValueError):
            glossary.catalog_language(Path("messages.po"))


if __name__ == "__main__":
    unittest.main()
