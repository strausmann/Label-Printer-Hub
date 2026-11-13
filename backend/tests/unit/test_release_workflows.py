"""Guard tests for the release and image-publish workflows (#183).

These tests check the TEXT of the workflow files, not their run: they parse
the YAML and assert the wiring that the release image build depends on. They
cannot prove that a workflow behaves correctly on GitHub; the live run of the
image workflow against a throw-away pre-release tag does that.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def _load(name: str) -> dict[str, Any]:
    data = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _text(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def _checkout_steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout")]


def test_release_builds_from_tag() -> None:
    wf = _load("docker-publish.yml")
    for job_name in ("build", "merge"):
        job = wf["jobs"][job_name]
        checkouts = _checkout_steps(job)
        assert checkouts, f"{job_name} has no actions/checkout step"
        refs = [str(c.get("with", {}).get("ref", "")) for c in checkouts]
        assert any("inputs.tag" in r for r in refs), f"{job_name} checkout ref ignores inputs.tag"
        assert "github.sha" not in json.dumps(job), (
            f"{job_name} still references github.sha (revision must come from the checked-out tag)"
        )


def test_release_concurrency_is_separate() -> None:
    wf = _load("docker-publish.yml")
    group = wf["concurrency"]["group"]
    assert "inputs.tag" in group
    assert "github.ref" in group  # dev/branch builds keep their per-ref group


def test_prerelease_never_floats_or_reaches_docker_hub() -> None:
    text = _text("docker-publish.yml")
    guard = "!contains(steps.tag.outputs.tag, '-')"
    lines = text.splitlines()

    hub = [ln for ln in lines if re.search(r"docker\.io/", ln) and "format(" in ln]
    assert hub, "Docker Hub image line not found"
    assert all(guard in ln for ln in hub)

    for needle in ("pattern={{major}}.{{minor}}", "pattern={{major}},", "value=latest"):
        matched = [ln for ln in lines if needle in ln]
        assert matched, f"tag line {needle!r} not found"
        assert all(guard in ln for ln in matched), f"{needle!r} not guarded against pre-releases"


def test_images_job_skips_dry_run() -> None:
    wf = _load("release.yml")
    job = wf["jobs"]["images"]
    cond = str(job["if"])
    assert "new-release-published == 'true'" in cond
    assert "!inputs.dry_run" in cond
    assert job["uses"] == "./.github/workflows/docker-publish.yml"
    assert "needs.release.outputs.new-release-version" in str(job["with"]["tag"])


def test_semantic_release_pushes_over_ssh() -> None:
    releaserc = json.loads((REPO_ROOT / ".releaserc.json").read_text(encoding="utf-8"))
    assert releaserc["repositoryUrl"] == "git@github.com:strausmann/Label-Printer-Hub.git"

    steps = _load("release.yml")["jobs"]["release"]["steps"]
    load = next(s for s in steps if "Load deploy key" in str(s.get("name", "")))
    assert load["env"]["SSH_KEY"] == "${{ secrets.SEMANTIC_RELEASE_SSH_KEY }}"
    script = load["run"]
    # The key reaches the agent through stdin, never a file or a command line.
    assert "ssh-add -" in script
    assert "$SSH_KEY" in script and "> key" not in script
    # The host key of github.com is pinned, not trusted on first use.
    assert "StrictHostKeyChecking=yes" in script
    assert "github.com ssh-ed25519 " in script


def test_deploy_key_is_not_persisted_and_loaded_after_install() -> None:
    wf = _load("release.yml")
    steps = wf["jobs"]["release"]["steps"]
    checkout = _checkout_steps(wf["jobs"]["release"])[0]["with"]
    assert checkout["persist-credentials"] is False
    assert "ssh-key" not in checkout

    names = [str(s.get("name", s.get("uses", ""))) for s in steps]
    install = next(i for i, n in enumerate(names) if n.startswith("Install semantic-release"))
    load = next(i for i, n in enumerate(names) if n.startswith("Load deploy key"))
    run = next(i for i, n in enumerate(names) if n == "semantic-release")
    assert install < load < run, "dependency code must be installed before the key is loadable"
    assert "--ignore-scripts" in steps[install]["run"]
    assert steps[install]["run"].startswith("npm ci")
    assert (REPO_ROOT / ".github" / "release-tools" / "package-lock.json").is_file()

    # Only the load step may read the secret.
    for i, step in enumerate(steps):
        if i != load:
            assert "SEMANTIC_RELEASE_SSH_KEY" not in json.dumps(step)


def test_key_never_reaches_images_job_or_called_workflow() -> None:
    images = _load("release.yml")["jobs"]["images"]
    blob = json.dumps(images)
    assert "SEMANTIC_RELEASE_SSH_KEY" not in blob
    assert "ssh-key" not in blob
    assert images["secrets"] != "inherit"
    # The called workflow does not know the key either.
    assert "SEMANTIC_RELEASE_SSH_KEY" not in _text("docker-publish.yml")


def test_actions_are_pinned_to_full_commit_shas() -> None:
    sha = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
    for name in (
        "release.yml",
        "release-tools.yml",
        "docker-publish.yml",
        "licence-gate.yml",
        "licence-backend.yml",
        "website.yml",
        "prose.yml",
    ):
        for job_name, job in _load(name)["jobs"].items():
            for step in job.get("steps", []):
                uses = step.get("uses")
                if uses:
                    assert sha.match(uses), (
                        f"{name}/{job_name}: {uses} is not pinned to a 40-character commit SHA"
                    )


def test_release_version_output_chain_is_wired() -> None:
    """exec plugin -> $GITHUB_OUTPUT -> steps.semantic.outputs.version -> images.if.

    A rename anywhere in this chain would publish releases with no images and
    keep the run green, which is #183 again.
    """
    releaserc = json.loads((REPO_ROOT / ".releaserc.json").read_text(encoding="utf-8"))
    names = [p[0] if isinstance(p, list) else p for p in releaserc["plugins"]]
    exec_cfg = next(p[1] for p in releaserc["plugins"] if p[0] == "@semantic-release/exec")
    # publishCmd runs as soon as the release exists; it must come after the GitHub release.
    assert names.index("@semantic-release/exec") > names.index("@semantic-release/github")
    assert "successCmd" not in exec_cfg
    assert exec_cfg["publishCmd"] == 'echo "version=${nextRelease.version}" >> "$GITHUB_OUTPUT"'

    wf = _load("release.yml")
    job = wf["jobs"]["release"]
    step_ids = [s.get("id") for s in job["steps"]]
    assert "semantic" in step_ids
    assert job["outputs"]["new-release-version"] == "${{ steps.semantic.outputs.version }}"
    assert "steps.semantic.outputs.version" in job["outputs"]["new-release-published"]

    images = wf["jobs"]["images"]
    assert "needs.release.outputs.new-release-published" in images["if"]
    assert images["with"]["tag"] == "${{ needs.release.outputs.new-release-version }}"
    assert "release" in str(images["needs"])


def test_release_tag_regex_accepts_only_semver() -> None:
    wf = _load("docker-publish.yml")
    for job_name in ("build", "merge"):
        steps = wf["jobs"][job_name]["steps"]
        names = [str(s.get("name", s.get("uses", ""))) for s in steps]
        validate = names.index("Validate release tag input")
        checkout = next(i for i, s in enumerate(steps) if "actions/checkout" in str(s.get("uses")))
        assert validate < checkout, f"{job_name}: tag must be validated before the checkout"
        match = re.search(r"grep -Eq '([^']+)'", steps[validate]["run"])
        assert match
        pattern = re.compile(match.group(1))
        for ok in ("1.1.0", "v1.1.0", "0.0.0-ci.1", "2.0.0-rc.1"):
            assert pattern.match(ok), ok
        for bad in ("", "1.1", "latest", "1.1.0;rm", "1.1.0 ", "../1.1.0", "v1.1.0\nx", "1.1.0-"):
            if bad == "":
                continue  # empty means "not a release build" and is handled before the grep
            assert not pattern.match(bad), repr(bad)


def test_dependabot_covers_release_toolchain() -> None:
    cfg = yaml.safe_load((REPO_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    entries = [
        u
        for u in cfg["updates"]
        if u["package-ecosystem"] == "npm" and u["directory"] == "/.github/release-tools"
    ]
    assert entries, "release toolchain pins would never receive updates"


def test_release_jobs_declare_minimal_permissions() -> None:
    wf = _load("release.yml")
    assert wf["permissions"] == {"contents": "read"}
    assert wf["jobs"]["release"]["permissions"] == {
        "contents": "write",
        "issues": "write",
        "pull-requests": "write",
    }
    assert wf["jobs"]["images"]["permissions"] == {
        "contents": "write",
        "packages": "write",
        "id-token": "write",
    }


def test_release_toolchain_is_locked_to_exact_versions() -> None:
    pkg = json.loads(
        (REPO_ROOT / ".github" / "release-tools" / "package.json").read_text(encoding="utf-8")
    )
    exact = re.compile(r"^\d+\.\d+\.\d+$")
    for name, version in pkg["dependencies"].items():
        assert exact.match(version), f"{name} is not pinned to an exact version: {version}"


def test_license_scope_is_allowed() -> None:
    text = (REPO_ROOT / "commitlint.config.cjs").read_text(encoding="utf-8")
    assert "'license'" in text


def test_release_tools_check_always_reports_and_is_read_only() -> None:
    """The check must exist on every PR (it is meant to become a required check)."""
    wf = _load("release-tools.yml")
    # YAML parses the key `on` as the boolean True.
    triggers = wf.get("on", wf.get(True))
    assert set(triggers) == {"pull_request", "push"}
    for event in ("pull_request", "push"):
        assert triggers[event]["branches"] == ["main", "milestone/**"]
        # A paths filter would skip the check on unrelated PRs and block them once required.
        assert "paths" not in triggers[event]
        assert "paths-ignore" not in triggers[event]

    assert wf["permissions"] == {}
    assert list(wf["jobs"]) == ["dry-run"]
    job = wf["jobs"]["dry-run"]
    assert job["name"] == "release-tools dry run"  # the name the operator ruleset needs
    assert job["permissions"] == {"contents": "read"}
    assert "if" not in job  # a skipped job reports nothing

    text = _text("release-tools.yml")
    assert "secrets." not in text
    assert "github.token" not in text and "GITHUB_TOKEN" not in text
    checkout = _checkout_steps(job)
    assert len(checkout) == 1
    assert checkout[0]["with"]["persist-credentials"] is False
    assert checkout[0]["with"]["fetch-depth"] == 0  # the scope check diffs base...head


def test_release_tools_steps_gate_on_the_scope_check() -> None:
    job = _load("release-tools.yml")["jobs"]["dry-run"]
    steps = job["steps"]
    scope = next(s for s in steps if s.get("id") == "scope")
    assert "release_tools_scope.sh" in scope["run"]
    assert "if" not in scope  # it always runs; the later steps depend on it

    heavy = [
        s
        for s in steps
        if s is not scope and not str(s.get("uses", "")).startswith("actions/checkout")
    ]
    runs = " ".join(str(s.get("run", "")) for s in heavy)
    for needed in (
        "npm ci --ignore-scripts",
        "release_dry_run.sh --all",
        "release_dry_run.sh --notes",
    ):
        assert needed in runs, f"missing step: {needed}"
    assert "### Features" in runs
    for step in heavy:
        assert step["if"] == "steps.scope.outputs.touched == 'true'", step.get("name")
    install = next(s for s in heavy if "npm ci" in str(s.get("run", "")))
    assert install["working-directory"] == ".github/release-tools"
    node = next(s for s in heavy if str(s.get("uses", "")).startswith("actions/setup-node"))
    assert (
        node["with"]["node-version"]
        == next(
            st
            for st in _load("release.yml")["jobs"]["release"]["steps"]
            if str(st.get("uses", "")).startswith("actions/setup-node")
        )["with"]["node-version"]
    )
