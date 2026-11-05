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
    for job in _load("release.yml")["jobs"].values():
        for step in job.get("steps", []):
            uses = step.get("uses")
            if uses:
                assert sha.match(uses), f"{uses} is not pinned to a 40-character commit SHA"


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
