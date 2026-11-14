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
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ghcr_rules as g

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"


try:  # Python >= 3.11
    from re import _constants as _sre_constants
    from re import _parser as _sre_parse
except ImportError:  # pragma: no cover
    import sre_constants as _sre_constants  # type: ignore[no-redef]
    import sre_parse as _sre_parse  # type: ignore[no-redef]

# The pinned cleanup action rejects patterns with safe-regex2's defaults:
# star height above 1 (every repetition counts, also `?` and `{m,n}`) and more
# than 25 repetitions.
SAFE_REGEX_STAR_LIMIT = 1
SAFE_REGEX_REPETITION_LIMIT = 25


def _walk(items, height: int) -> tuple[int, int]:
    """Return (max star height, repetition count) of a parsed pattern."""
    max_height, count = height, 0
    for op, av in items:
        if op in (_sre_constants.MAX_REPEAT, _sre_constants.MIN_REPEAT):
            h, c = _walk(av[2], height + 1)
            max_height, count = max(max_height, h), count + c + 1
        elif op is _sre_constants.SUBPATTERN:
            h, c = _walk(av[-1], height)
            max_height, count = max(max_height, h), count + c
        elif op is _sre_constants.BRANCH:
            for branch in av[1]:
                h, c = _walk(branch, height)
                max_height, count = max(max_height, h), count + c
    return max_height, count


def safe_regex_metrics(pattern: str) -> tuple[int, int]:
    return _walk(_sre_parse.parse(pattern), 0)


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

    def test_regex_passes_the_actions_regex_validator(self) -> None:
        """The cleanup action runs safe-regex2 over exclude-tags and aborts on
        a rejected pattern. Nested repetitions (`(...)?` or `{0,2}` around
        `[0-9]*`) are rejected, so the pattern must stay flat. Checked with a
        Python model of the star-height and repetition-count rules."""
        pattern = g.keep_regex(["1.5.1-rc.1", "1.6.0-rc.2"])
        height, count = safe_regex_metrics(pattern)
        self.assertLessEqual(height, SAFE_REGEX_STAR_LIMIT, pattern)
        self.assertLessEqual(count, SAFE_REGEX_REPETITION_LIMIT, pattern)

    def test_flat_regex_matches_the_documented_rule(self) -> None:
        """Equivalence with the original nested rule, over generated tags."""
        original = re.compile(
            r"^(dev|latest|1|1\.([4-9]|[1-9][0-9]+)(\.(0|[1-9][0-9]*))?"
            r"|([2-9]|[1-9][0-9]+)(\.(0|[1-9][0-9]*)){0,2})$"
        )
        rule = re.compile(g.keep_regex([]))
        numbers = ["0", "1", "3", "4", "9", "10", "04", "11", "100"]
        tags = {f"{a}.{b}.{c}" for a in numbers for b in numbers for c in ("0", "7", "10")}
        tags |= {f"{a}.{b}" for a in numbers for b in numbers} | set(numbers)
        tags |= {"dev", "latest", "1.2.3.4", "1.4.0.1", "", "x", "1.5.1-rc.1", "v1.4.0"}
        for tag in sorted(tags):
            with self.subTest(tag=tag):
                self.assertEqual(bool(rule.match(tag)), bool(original.match(tag)))

    def test_preview_dots_are_escaped(self) -> None:
        self.assertFalse(re.match(g.keep_regex(["1.5.1-rc.1"]), "1x5x1-rc.1"))

    def test_many_previews_of_one_version_stay_short(self) -> None:
        tags = [f"1.6.0-rc.{i}" for i in range(1, 80)]
        pattern = g.keep_regex(tags)
        self.assertLessEqual(len(pattern), g.MAX_REGEX_LENGTH)
        self.assertTrue(re.match(pattern, "1.6.0-rc.80"))
        self.assertFalse(re.match(pattern, "1.6.1-rc.1"))
        self.assertFalse(re.match(g.keep_regex(tags + ["1.6.0"]), "1.6.0-rc.3"))

    def test_too_many_open_versions_fail_with_a_clear_error(self) -> None:
        tags = [f"1.{minor}.0-rc.1" for minor in range(10, 120)]
        with self.assertRaisesRegex(ValueError, "cleanup action accepts"):
            g.keep_regex(tags)

    def test_repetition_count_does_not_grow_with_open_versions(self) -> None:
        few = safe_regex_metrics(g.keep_regex(["1.5.1-rc.1"]))
        many = safe_regex_metrics(g.keep_regex([f"1.{i}.0-rc.1" for i in range(10, 40)]))
        self.assertEqual(few, many)
        self.assertLessEqual(many[1], SAFE_REGEX_REPETITION_LIMIT)

    def test_pattern_with_several_open_versions_passes_the_validator_model(self) -> None:
        tags = ["1.5.1-rc.1", "1.5.1-rc.2", "1.6.0-rc.1", "2.0.0-rc.4"]
        height, count = safe_regex_metrics(g.keep_regex(tags))
        self.assertLessEqual(height, SAFE_REGEX_STAR_LIMIT)
        self.assertLessEqual(count, SAFE_REGEX_REPETITION_LIMIT)


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


class SelectDeletionsTest(unittest.TestCase):
    """One retention rule for GHCR and Docker Hub (Labelyard Task 4)."""

    def test_select_keeps_releases_latest_dev(self) -> None:
        tags = ["1.6.0", "1.6", "1", "latest", "dev"]
        self.assertEqual(g.select_deletions(tags, {"1.6.0"}), [])

    def test_select_keeps_open_preview(self) -> None:
        self.assertEqual(g.select_deletions(["1.6.0", "1.7.0-rc.2"], {"1.6.0"}), [])

    def test_select_deletes_closed_preview(self) -> None:
        tags = ["1.6.0-rc.1", "1.6.0", "1.6.0-rc.3", "1.7.0-rc.1"]
        self.assertEqual(g.select_deletions(tags, {"1.6.0"}), ["1.6.0-rc.1", "1.6.0-rc.3"])

    def test_released_set_closes_a_preview_without_its_release_tag(self) -> None:
        # The release may be known from the other registry only.
        self.assertEqual(g.select_deletions(["1.6.0-rc.1"], {"1.6.0"}), ["1.6.0-rc.1"])

    def test_select_ignores_foreign_tags(self) -> None:
        tags = ["sha-abc", "feat-x", "1.6.0-rc.1", "0.0.0-ci.1", "1.04.0"]
        self.assertEqual(g.select_deletions(tags, {"1.6.0"}), ["1.6.0-rc.1"])
        self.assertEqual(g.foreign_tags(tags), ["sha-abc", "feat-x", "0.0.0-ci.1", "1.04.0"])

    def test_select_agrees_with_keep_regex(self) -> None:
        tags = [
            "dev", "latest", "1", "1.6", "1.6.0", "1.5.1", "1.4", "1.3.9", "1.0.1", "2", "2.0",
            "1.6.0-rc.1", "1.6.0-rc.2", "1.7.0-rc.1", "1.5.2-rc.4", "1.5.1-rc.1",
        ]
        released = set(g.released_versions(tags))
        rule = re.compile(g.keep_regex(tags))
        expected = [t for t in tags if not rule.match(t)]
        self.assertEqual(g.select_deletions(tags, released), expected)
        self.assertIn("1.6.0-rc.1", expected)
        self.assertNotIn("1.7.0-rc.1", expected)

    def test_duplicates_are_listed_once(self) -> None:
        self.assertEqual(g.select_deletions(["1.6.0-rc.1", "1.6.0-rc.1"], {"1.6.0"}), ["1.6.0-rc.1"])

    def test_signature_tag_is_never_selected(self) -> None:
        # cosign's fallback tag on GHCR (no referrers API): `sha256-<index hex>`.
        signature = "sha256-" + "0123456789abcdef" * 4
        tags = [signature, "1.6.0", "1.6.0-rc.1"]
        self.assertEqual(g.select_deletions(tags, {"1.6.0"}), ["1.6.0-rc.1"])
        self.assertEqual(g.select_deletions([signature], set()), [])




class _Response(io.BytesIO):
    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _opener(list_status: int, tags: list[str] | None = None, link: str | None = None):
    def opener(request: urllib.request.Request) -> _Response:
        if "/token" in request.full_url:
            return _Response(json.dumps({"token": "t"}).encode())
        if list_status != 200:
            raise urllib.error.HTTPError(request.full_url, list_status, "x", {}, None)  # type: ignore[arg-type]
        response = _Response(json.dumps({"tags": tags}).encode())
        response.headers = {"Link": link} if link else {}  # type: ignore[attr-defined]
        return response

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

    def test_paginated_answer_is_an_error(self) -> None:
        opener = _opener(200, ["1.5.0"], link='</v2/o/i/tags/list?last=1.5.0&n=10000>; rel="next"')
        with self.assertRaisesRegex(RuntimeError, "paginated"):
            g.fetch_tags("o/i", "a", "s", opener=opener)

    def test_other_link_relation_is_fine(self) -> None:
        opener = _opener(200, ["1.5.0"], link='</x>; rel="prev"')
        self.assertEqual(g.fetch_tags("o/i", "a", "s", opener=opener), ["1.5.0"])

    def test_credentials_not_in_urls(self) -> None:
        seen: list[urllib.request.Request] = []

        def opener(request: urllib.request.Request) -> _Response:
            seen.append(request)
            return _opener(200, [])(request)

        g.fetch_tags("o/i", "actor", "secret-value", opener=opener)
        self.assertTrue(all("secret-value" not in r.full_url for r in seen))


def _hub_opener(pages: dict[str, tuple[int, object]], seen: list | None = None):
    """Fake Docker Hub: maps a URL to (status, JSON payload); OSError for 'down'."""

    def opener(request: urllib.request.Request) -> _Response:
        if seen is not None:
            seen.append(request)
        status, payload = pages[request.full_url]
        if status == -1:
            raise urllib.error.URLError("connection refused")
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, "x", {}, None)  # type: ignore[arg-type]
        response = _Response(b"" if payload is None else json.dumps(payload).encode())
        response.status = status  # type: ignore[attr-defined]
        return response

    return opener


HUB = "https://hub.docker.com/v2"
TAGS_URL = f"{HUB}/namespaces/ns/repositories/labelyard/tags?page_size=100"


class DockerHubTest(unittest.TestCase):
    def test_token_is_requested_with_the_secret_in_the_body(self) -> None:
        seen: list[urllib.request.Request] = []
        opener = _hub_opener({f"{HUB}/auth/token": (200, {"access_token": "jwt"})}, seen)
        self.assertEqual(g.dockerhub_token("User", "pat-secret", opener=opener), "jwt")
        self.assertEqual(seen[0].get_method(), "POST")
        self.assertEqual(json.loads(seen[0].data), {"identifier": "User", "secret": "pat-secret"})
        self.assertNotIn("pat-secret", seen[0].full_url)

    def test_token_401_is_an_error(self) -> None:
        opener = _hub_opener({f"{HUB}/auth/token": (401, None)})
        with self.assertRaises(urllib.error.HTTPError):
            g.dockerhub_token("u", "s", opener=opener)

    def test_tags_follow_next(self) -> None:
        page2 = f"{TAGS_URL}&page=2"
        opener = _hub_opener({
            TAGS_URL: (200, {"results": [{"name": "1.6.0"}], "next": page2}),
            page2: (200, {"results": [{"name": "dev"}], "next": None}),
        })
        self.assertEqual(g.fetch_dockerhub_tags("ns", "labelyard", "jwt", opener=opener), ["1.6.0", "dev"])

    def test_tags_404_is_empty_with_a_warning(self) -> None:
        opener = _hub_opener({TAGS_URL: (404, None)})
        err = io.StringIO()
        with mock.patch("sys.stderr", err):
            self.assertEqual(g.fetch_dockerhub_tags("ns", "labelyard", "jwt", opener=opener), [])
        self.assertIn("::warning::Docker Hub repository ns/labelyard not found", err.getvalue())

    def test_empty_repository_has_no_warning(self) -> None:
        opener = _hub_opener({TAGS_URL: (200, {"results": [], "next": None})})
        err = io.StringIO()
        with mock.patch("sys.stderr", err):
            self.assertEqual(g.fetch_dockerhub_tags("ns", "labelyard", "jwt", opener=opener), [])
        self.assertEqual(err.getvalue(), "")

    def test_tags_404_on_a_later_page_is_an_error(self) -> None:
        page2 = f"{TAGS_URL}&page=2"
        opener = _hub_opener({
            TAGS_URL: (200, {"results": [{"name": "1.6.0"}], "next": page2}),
            page2: (404, None),
        })
        with self.assertRaises(urllib.error.HTTPError):
            g.fetch_dockerhub_tags("ns", "labelyard", "jwt", opener=opener)

    def test_tags_500_is_an_error(self) -> None:
        opener = _hub_opener({TAGS_URL: (500, None)})
        with self.assertRaises(urllib.error.HTTPError):
            g.fetch_dockerhub_tags("ns", "labelyard", "jwt", opener=opener)

    def test_tags_network_error_is_raised(self) -> None:
        opener = _hub_opener({TAGS_URL: (-1, None)})
        with self.assertRaises(urllib.error.URLError):
            g.fetch_dockerhub_tags("ns", "labelyard", "jwt", opener=opener)

    def test_next_page_on_a_foreign_host_is_refused(self) -> None:
        opener = _hub_opener({TAGS_URL: (200, {"results": [], "next": "https://evil.example/x"})})
        with self.assertRaisesRegex(RuntimeError, "next"):
            g.fetch_dockerhub_tags("ns", "labelyard", "jwt", opener=opener)

    def test_delete_uses_the_tag_endpoint(self) -> None:
        seen: list[urllib.request.Request] = []
        url = f"{HUB}/repositories/ns/labelyard/tags/1.6.0-rc.1/"
        g.delete_dockerhub_tag("ns", "labelyard", "1.6.0-rc.1", "jwt", opener=_hub_opener({url: (204, None)}, seen))
        self.assertEqual(seen[0].get_method(), "DELETE")
        self.assertEqual(seen[0].get_header("Authorization"), "Bearer jwt")

    def test_delete_404_means_already_gone(self) -> None:
        url = f"{HUB}/repositories/ns/labelyard/tags/1.6.0-rc.1/"
        g.delete_dockerhub_tag("ns", "labelyard", "1.6.0-rc.1", "jwt", opener=_hub_opener({url: (404, None)}))

    def test_delete_403_is_an_error(self) -> None:
        url = f"{HUB}/repositories/ns/labelyard/tags/1.6.0-rc.1/"
        with self.assertRaises(urllib.error.HTTPError):
            g.delete_dockerhub_tag("ns", "labelyard", "1.6.0-rc.1", "jwt", opener=_hub_opener({url: (403, None)}))

    def test_delete_network_error_is_raised(self) -> None:
        url = f"{HUB}/repositories/ns/labelyard/tags/1.6.0-rc.1/"
        with self.assertRaises(urllib.error.URLError):
            g.delete_dockerhub_tag("ns", "labelyard", "1.6.0-rc.1", "jwt", opener=_hub_opener({url: (-1, None)}))

    def test_delete_refuses_a_tag_that_is_not_a_tag(self) -> None:
        for bad in ["../x", "a/b", "", "1.6.0\n"]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                g.delete_dockerhub_tag("ns", "labelyard", bad, "jwt", opener=_hub_opener({}))


class FetchTagsCliTest(unittest.TestCase):
    ENV = {"IMAGE_PATH": "O/I", "ACTOR": "a", "GHCR_TOKEN": "s"}

    def run_fetch(self, argv: list[str], tags: list[str]) -> tuple[int, str]:
        out = io.StringIO()
        err = io.StringIO()
        with (
            mock.patch.dict("os.environ", self.ENV),
            mock.patch.object(g, "fetch_tags", return_value=tags),
            mock.patch("sys.stderr", err),
        ):
            code = g.main(["fetch-tags", *argv], stdout=out)
        return code, out.getvalue() + err.getvalue()

    def test_empty_list_aborts_a_real_cleanup(self) -> None:
        code, text = self.run_fetch(["--on-empty=fail"], [])
        self.assertEqual(code, 1)
        self.assertIn("::error::", text)

    def test_empty_list_only_warns_in_a_dry_run(self) -> None:
        code, text = self.run_fetch(["--on-empty=warn"], [])
        self.assertEqual(code, 0)
        self.assertIn("::warning::", text)

    def test_empty_list_is_fine_for_a_preview(self) -> None:
        self.assertEqual(self.run_fetch([], []), (0, ""))

    def test_non_empty_list_passes_in_every_mode(self) -> None:
        for mode in ("allow", "warn", "fail"):
            with self.subTest(mode=mode):
                code, text = self.run_fetch([f"--on-empty={mode}"], ["1.5.0"])
                self.assertEqual((code, text), (0, "1.5.0\n"))


class CliTest(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def run_cli(self, argv: list[str], stdin: str) -> tuple[int, str]:
        out = io.StringIO()
        code = g.main(argv, stdin=io.StringIO(stdin), stdout=out)
        return code, out.getvalue()

    def test_keep_regex(self) -> None:
        code, out = self.run_cli(["keep-regex"], "1.5.1-rc.1\n1.4.0\n")
        self.assertEqual(code, 0)
        self.assertIn(r"(1\.5\.1)-rc\.[0-9]+", out)

    def test_next_preview_reads_released_from_tags(self) -> None:
        code, out = self.run_cli(["next-preview", "1.5.x"], "1.5.0\n1.5.1\n")
        self.assertEqual((code, out.strip()), (0, "1.5.2-rc.1"))

    def test_next_preview_refuses_released(self) -> None:
        code, _ = self.run_cli(["next-preview", "1.5.1"], "1.5.1\n")
        self.assertEqual(code, 1)

    def test_select_deletions(self) -> None:
        released = Path(self.tmp.name) / "released.txt"
        released.write_text("1.6.0\n")
        err = io.StringIO()
        with mock.patch("sys.stderr", err):
            code, out = self.run_cli(
                ["select-deletions", "--released", str(released)], "1.6.0\n1.6.0-rc.1\nfeat-x\n1.7.0-rc.1\n"
            )
        self.assertEqual((code, out), (0, "1.6.0-rc.1\n"))
        self.assertIn("feat-x", err.getvalue())
        self.assertNotIn("1.6.0-rc.1", err.getvalue())

    def test_released(self) -> None:
        code, out = self.run_cli(["released"], "1.6.0\n1.6.0-rc.1\ndev\n1.6\n1.5.1\n1.6.0\n")
        self.assertEqual((code, out), (0, "1.6.0\n1.5.1\n"))

    def test_dockerhub_delete_deletes_each_tag(self) -> None:
        env = {"DOCKERHUB_USERNAME": "User", "DOCKERHUB_ADMIN_TOKEN": "pat", "HUB_REPOSITORY": "labelyard"}
        with (
            mock.patch.dict("os.environ", env),
            mock.patch.object(g, "dockerhub_token", return_value="jwt") as token,
            mock.patch.object(g, "delete_dockerhub_tag") as delete,
        ):
            code, out = self.run_cli(["dockerhub-delete"], "1.6.0-rc.1\n1.6.0-rc.2\n")
        self.assertEqual(code, 0)
        token.assert_called_once_with("User", "pat")
        self.assertEqual(
            delete.call_args_list,
            [mock.call("user", "labelyard", "1.6.0-rc.1", "jwt"), mock.call("user", "labelyard", "1.6.0-rc.2", "jwt")],
        )
        self.assertNotIn("pat", out)

    def test_dockerhub_delete_with_nothing_to_do_does_not_log_in(self) -> None:
        with mock.patch.object(g, "dockerhub_token") as token:
            code, out = self.run_cli(["dockerhub-delete"], "")
        self.assertEqual((code, out), (0, ""))
        token.assert_not_called()

    def test_dockerhub_delete_stops_at_the_first_error(self) -> None:
        env = {"DOCKERHUB_USERNAME": "u", "DOCKERHUB_ADMIN_TOKEN": "p", "HUB_REPOSITORY": "labelyard"}
        error = urllib.error.HTTPError("x", 403, "x", {}, None)  # type: ignore[arg-type]
        with (
            mock.patch.dict("os.environ", env),
            mock.patch.object(g, "dockerhub_token", return_value="jwt"),
            mock.patch.object(g, "delete_dockerhub_tag", side_effect=error) as delete,
            self.assertRaises(urllib.error.HTTPError),
        ):
            self.run_cli(["dockerhub-delete"], "1.6.0-rc.1\n1.6.0-rc.2\n")
        self.assertEqual(delete.call_count, 1)

    def test_dockerhub_tags(self) -> None:
        env = {"DOCKERHUB_USERNAME": "User", "DOCKERHUB_ADMIN_TOKEN": "pat", "HUB_REPOSITORY": "labelyard"}
        with (
            mock.patch.dict("os.environ", env),
            mock.patch.object(g, "dockerhub_token", return_value="jwt"),
            mock.patch.object(g, "fetch_dockerhub_tags", return_value=["dev", "1.6.0"]) as fetch,
        ):
            code, out = self.run_cli(["dockerhub-tags"], "")
        self.assertEqual((code, out), (0, "dev\n1.6.0\n"))
        fetch.assert_called_once_with("user", "labelyard", "jwt")

    def test_select_deletions_needs_the_released_file(self) -> None:
        code, _ = self.run_cli(["select-deletions"], "1.6.0-rc.1\n")
        self.assertEqual(code, 2)

    def test_unknown_command(self) -> None:
        code, _ = self.run_cli(["nope"], "")
        self.assertEqual(code, 2)


class WorkflowsCallTheScriptTest(unittest.TestCase):
    """Source-text guard: checks characters, not behaviour. It cannot see whether
    the call is reachable; no behaviour test is possible without running the
    workflows on GitHub. Reports the file and line of each violation."""

    def test_workflows_call_the_script(self) -> None:
        for name, needles in {
            "registry-cleanup.yml": [
                "scripts/ghcr_rules.py fetch-tags",
                "scripts/ghcr_rules.py keep-regex",
                "scripts/ghcr_rules.py dockerhub-tags",
                "scripts/ghcr_rules.py released",
                "scripts/ghcr_rules.py select-deletions --released",
                "scripts/ghcr_rules.py dockerhub-delete",
            ],
            "preview-image.yml": ["scripts/ghcr_rules.py fetch-tags", "scripts/ghcr_rules.py next-preview"],
        }.items():
            text = (WORKFLOWS / name).read_text()
            for needle in needles:
                with self.subTest(file=name, needle=needle):
                    self.assertIn(needle, text, f"{name}: missing call '{needle}'")

    def test_cleanup_aborts_on_an_empty_tag_list(self) -> None:
        text = (WORKFLOWS / "registry-cleanup.yml").read_text()
        self.assertIn("fetch-tags --on-empty=", text, "registry-cleanup.yml: fetch-tags without --on-empty")
        self.assertIn("on_empty=fail", text)

    def test_no_inline_keep_regex_or_tag_curl(self) -> None:
        for name in ["registry-cleanup.yml", "preview-image.yml"]:
            for number, line in enumerate((WORKFLOWS / name).read_text().splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                with self.subTest(file=name, line=number):
                    self.assertNotIn("tags/list", line, f"{name}:{number}: inline tag-list request")
                    self.assertNotIn("1\\.([4-9]", line, f"{name}:{number}: inline keep regex")
                    self.assertNotIn("BASH_REMATCH", line, f"{name}:{number}: inline preview loop")


if __name__ == "__main__":
    unittest.main()
