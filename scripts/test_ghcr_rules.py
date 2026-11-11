"""Unit tests for scripts/ghcr_rules.py.

Run with: python3 -m unittest discover -s scripts -p 'test_*.py' -v
"""

from __future__ import annotations

import io
import json
import re
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ghcr_rules as g

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"


def kept(tag: str, tags: list[str] | None = None) -> bool:
    return re.match(g.keep_regex(tags or [tag]), tag) is not None


class KeepRegexTest(unittest.TestCase):
    def test_kept_tags(self) -> None:
        for tag in ["1.4.0", "1.10.0", "1.4", "1", "2.0.0", "dev", "latest"]:
            with self.subTest(tag=tag):
                self.assertTrue(kept(tag))

    def test_dropped_tags(self) -> None:
        for tag in [
            "1.3.9",
            "1.0.1",
            "0.0.0-ci.1",
            "ci-release-images-deploy-key",
            "ci-licence-gate",
            "fix-ci-green-main",
            "1.04.0",
        ]:
            with self.subTest(tag=tag):
                self.assertFalse(kept(tag))

    def test_open_preview_kept_until_release_exists(self) -> None:
        self.assertTrue(kept("1.5.1-rc.1", ["1.5.1-rc.1"]))
        self.assertFalse(kept("1.5.1-rc.1", ["1.5.1-rc.1", "1.5.1"]))

    def test_preview_dots_are_escaped(self) -> None:
        self.assertFalse(re.match(g.keep_regex(["1.5.1-rc.1"]), "1x5x1-rc.1"))


class NextPreviewTest(unittest.TestCase):
    def test_patch_milestone_after_release(self) -> None:
        self.assertEqual(g.next_preview_tag("1.5.x", ["1.5.0", "1.5.2"], ["1.5.0", "1.5.2"]), "1.5.3-rc.1")

    def test_patch_milestone_counts_up(self) -> None:
        tags = ["1.5.2", "1.5.3-rc.1"]
        self.assertEqual(g.next_preview_tag("1.5.x", tags, ["1.5.2"]), "1.5.3-rc.2")

    def test_minor_milestone(self) -> None:
        self.assertEqual(g.next_preview_tag("1.6.0", [], []), "1.6.0-rc.1")
        self.assertEqual(g.next_preview_tag("1.6.0", ["1.6.0-rc.1"], []), "1.6.0-rc.2")

    def test_refuses_released_version(self) -> None:
        with self.assertRaises(ValueError):
            g.next_preview_tag("1.5.1", ["1.5.1"], ["1.5.1"])

    def test_refuses_malformed(self) -> None:
        for bad in ["1.5", "v1.5.0", "1.5.x.x", "01.5.0"]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                g.next_preview_tag(bad, [], [])


class _Response(io.BytesIO):
    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _opener(list_status: int, tags: list[str] | None = None):
    def opener(request: urllib.request.Request) -> _Response:
        if "/token" in request.full_url:
            return _Response(json.dumps({"token": "t"}).encode())
        if list_status != 200:
            raise urllib.error.HTTPError(request.full_url, list_status, "x", {}, None)  # type: ignore[arg-type]
        return _Response(json.dumps({"tags": tags}).encode())

    return opener


class FetchTagsTest(unittest.TestCase):
    def fetch(self, status: int, tags: list[str] | None = None) -> list[str]:
        return g.fetch_tags("o/i", "a", "s", opener=_opener(status, tags))

    def test_ok(self) -> None:
        self.assertEqual(self.fetch(200, ["1.5.0"]), ["1.5.0"])

    def test_null_tags_is_empty(self) -> None:
        self.assertEqual(self.fetch(200, None), [])

    def test_403_is_empty_list(self) -> None:
        self.assertEqual(self.fetch(403), [])

    def test_404_is_empty_list(self) -> None:
        self.assertEqual(self.fetch(404), [])

    def test_500_is_an_error(self) -> None:
        with self.assertRaises(urllib.error.HTTPError):
            self.fetch(500)

    def test_401_is_an_error(self) -> None:
        with self.assertRaises(urllib.error.HTTPError):
            self.fetch(401)

    def test_credentials_not_in_urls(self) -> None:
        seen: list[urllib.request.Request] = []

        def opener(request: urllib.request.Request) -> _Response:
            seen.append(request)
            return _opener(200, [])(request)

        g.fetch_tags("o/i", "actor", "secret-value", opener=opener)
        self.assertTrue(all("secret-value" not in r.full_url for r in seen))


class CliTest(unittest.TestCase):
    def run_cli(self, argv: list[str], stdin: str) -> tuple[int, str]:
        out = io.StringIO()
        code = g.main(argv, stdin=io.StringIO(stdin), stdout=out)
        return code, out.getvalue()

    def test_keep_regex(self) -> None:
        code, out = self.run_cli(["keep-regex"], "1.5.1-rc.1\n1.4.0\n")
        self.assertEqual(code, 0)
        self.assertIn(r"1\.5\.1-rc\.1", out)

    def test_next_preview_reads_released_from_tags(self) -> None:
        code, out = self.run_cli(["next-preview", "1.5.x"], "1.5.0\n1.5.1\n")
        self.assertEqual((code, out.strip()), (0, "1.5.2-rc.1"))

    def test_next_preview_refuses_released(self) -> None:
        code, _ = self.run_cli(["next-preview", "1.5.1"], "1.5.1\n")
        self.assertEqual(code, 1)

    def test_unknown_command(self) -> None:
        code, _ = self.run_cli(["nope"], "")
        self.assertEqual(code, 2)


class WorkflowsCallTheScriptTest(unittest.TestCase):
    """Source-text guard: checks characters, not behaviour. It cannot see whether
    the call is reachable; no behaviour test is possible without running the
    workflows on GitHub. Reports the file and line of each violation."""

    def test_workflows_call_the_script(self) -> None:
        for name, needles in {
            "ghcr-cleanup.yml": ["scripts/ghcr_rules.py fetch-tags", "scripts/ghcr_rules.py keep-regex"],
            "preview-image.yml": ["scripts/ghcr_rules.py fetch-tags", "scripts/ghcr_rules.py next-preview"],
        }.items():
            text = (WORKFLOWS / name).read_text()
            for needle in needles:
                with self.subTest(file=name, needle=needle):
                    self.assertIn(needle, text, f"{name}: missing call '{needle}'")

    def test_no_inline_keep_regex_or_tag_curl(self) -> None:
        for name in ["ghcr-cleanup.yml", "preview-image.yml"]:
            for number, line in enumerate((WORKFLOWS / name).read_text().splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                with self.subTest(file=name, line=number):
                    self.assertNotIn("tags/list", line, f"{name}:{number}: inline tag-list request")
                    self.assertNotIn("1\\.([4-9]", line, f"{name}:{number}: inline keep regex")
                    self.assertNotIn("BASH_REMATCH", line, f"{name}:{number}: inline preview loop")


if __name__ == "__main__":
    unittest.main()
