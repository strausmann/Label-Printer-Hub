"""Guard tests for the release and image-publish workflows (#183).

These tests check the TEXT of the workflow files, not their run: they parse
the YAML and assert the wiring that the release image build depends on. They
cannot prove that a workflow behaves correctly on GitHub; the live run of the
image workflow against a throw-away pre-release tag does that.
"""

from __future__ import annotations

import json
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

    hub = [ln for ln in lines if "docker.io/" in ln and "format(" in ln]
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

    wf = _load("release.yml")
    checkout = _checkout_steps(wf["jobs"]["release"])[0]["with"]
    assert checkout["ssh-key"] == "${{ secrets.SEMANTIC_RELEASE_SSH_KEY }}"
    assert checkout["persist-credentials"] is True


def test_license_scope_is_allowed() -> None:
    text = (REPO_ROOT / "commitlint.config.cjs").read_text(encoding="utf-8")
    assert "'license'" in text
