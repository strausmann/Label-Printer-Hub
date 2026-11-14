"""Guard tests for the release and image-publish workflows (#183).

These tests check the TEXT of the workflow files, not their run: they parse
the YAML and assert the wiring that the release image build depends on. They
cannot prove that a workflow behaves correctly on GitHub; the live run of the
image workflow against a throw-away pre-release tag does that.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
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


def test_prerelease_never_floats() -> None:
    text = _text("docker-publish.yml")
    guard = "!contains(steps.tag.outputs.tag, '-')"
    lines = text.splitlines()
    for needle in ("pattern={{major}}.{{minor}}", "pattern={{major}},", "value=latest"):
        matched = [ln for ln in lines if needle in ln]
        assert matched, f"tag line {needle!r} not found"
        assert all(guard in ln for ln in matched), f"{needle!r} not guarded against pre-releases"


def test_docker_hub_gets_every_flavor_but_branch() -> None:
    lines = _text("docker-publish.yml").splitlines()
    hub = [ln for ln in lines if re.search(r"docker\.io/", ln) and "format(" in ln]
    assert len(hub) == 1, "exactly one Docker Hub image line"
    line = hub[0]
    # The whole line is pinned: a narrower condition (e.g. also excluding dev) must fail.
    assert line.strip() == (
        "${{ (steps.tag.outputs.flavor != 'branch' && secrets.DOCKERHUB_USERNAME "
        "&& secrets.DOCKERHUB_TOKEN) "
        "&& format('docker.io/{0}/labelyard', secrets.DOCKERHUB_USERNAME) || '' }}"
    )
    assert "format('docker.io/{0}/labelyard', secrets.DOCKERHUB_USERNAME)" in line
    assert "steps.tag.outputs.flavor != 'branch'" in line
    # Pre-releases (previews) reach Docker Hub too; only their floating tags are refused.
    assert "contains(steps.tag.outputs.tag, '-')" not in line
    assert "flavor == 'release'" not in line


TAGLINE = "Labelyard — the self-hosted Label Printer Hub for all your labels"


def _image_steps(wf: dict[str, Any]) -> dict[str, dict[str, Any]]:
    found = {}
    for job_name in ("build", "merge"):
        steps = [s for s in wf["jobs"][job_name]["steps"] if s.get("id") == "image"]
        assert len(steps) == 1, f"{job_name}: exactly one step with id image"
        found[job_name] = steps[0]
    return found


def test_image_ref_is_explicit() -> None:
    wf = _load("docker-publish.yml")
    assert wf["env"]["IMAGE_NAME"] == "labelyard"
    for job_name, step in _image_steps(wf).items():
        run = step["run"]
        assert "ref=${{ env.REGISTRY_GHCR }}/strausmann/${{ env.IMAGE_NAME }}" in run, job_name
        blob = json.dumps(step)
        assert "github.repository" not in blob, job_name
        assert "REPO" not in blob, job_name
        assert ",," not in run, job_name
    # No image address anywhere is derived from the repository name.
    for line in _text("docker-publish.yml").splitlines():
        if not line.lstrip().startswith("#"):
            assert "github.repository" not in line, line


def test_preview_passes_docker_hub_secrets() -> None:
    job = _load("preview-image.yml")["jobs"]["publish"]
    assert job["uses"] == "./.github/workflows/docker-publish.yml"
    assert job["secrets"] == {
        "DOCKERHUB_USERNAME": "${{ secrets.DOCKERHUB_USERNAME }}",
        "DOCKERHUB_TOKEN": "${{ secrets.DOCKERHUB_TOKEN }}",
    }
    assert "secrets: inherit" not in _text("preview-image.yml")
    assert "DOCKERHUB_ADMIN_TOKEN" not in _text("preview-image.yml")


def test_preview_reads_the_labelyard_package() -> None:
    steps = _load("preview-image.yml")["jobs"]["next-tag"]["steps"]
    envs = {k: v for s in steps for k, v in (s.get("env") or {}).items()}
    assert envs["IMAGE_PATH"] == "strausmann/labelyard"


def test_cleanup_targets_labelyard_only() -> None:
    assert not (WORKFLOWS / "ghcr-cleanup.yml").exists()
    wf = _load("registry-cleanup.yml")
    text = _text("registry-cleanup.yml")
    assert "label-printer-hub" not in text
    assert set(wf["jobs"]) == {"ghcr", "dockerhub"}
    prune = [
        s for s in wf["jobs"]["ghcr"]["steps"] if "ghcr-cleanup-action" in str(s.get("uses", ""))
    ]
    assert len(prune) == 1
    assert prune[0]["with"]["package"] == "labelyard"
    # The action fails on a package that does not exist yet; only a dry run reaches it then.
    assert prune[0]["if"] == "steps.keep.outputs.empty != 'true'"
    triggers = wf.get("on", wf.get(True))
    assert "dry-run" in triggers["workflow_dispatch"]["inputs"]
    for job in wf["jobs"].values():
        envs = {k: v for s in job["steps"] for k, v in (s.get("env") or {}).items()}
        assert envs["IMAGE_PATH"] == "strausmann/labelyard"
    assert wf["jobs"]["dockerhub"]["steps"][-1]["env"]["HUB_REPOSITORY"] == "labelyard"
    # Errors of select-deletions reach the log, not only foreign.txt (F-R4-2).
    hub_run = wf["jobs"]["dockerhub"]["steps"][-1]["run"]
    select = hub_run[hub_run.index("select-deletions") :]
    assert select.split("\n", 2)[1].strip() == "|| { cat foreign.txt >&2; exit 1; }"
    assert "cat foreign.txt >&2" in select.split("\n", 3)[2]
    # The admin token reaches only the Docker Hub job.
    assert "DOCKERHUB_ADMIN_TOKEN" not in json.dumps(wf["jobs"]["ghcr"])
    assert "DOCKERHUB_ADMIN_TOKEN" in json.dumps(wf["jobs"]["dockerhub"])


def _oci_values(block: str) -> dict[str, str]:
    values = {}
    for line in block.splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key.startswith("org.opencontainers.image."):
            values[key.removeprefix("org.opencontainers.image.")] = value
    return values


def test_oci_title_matches_dockerfile() -> None:
    dockerfile = (REPO_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    labels = dict(re.findall(r'org\.opencontainers\.image\.([a-z.]+)="([^"]*)"', dockerfile))
    wf = _load("docker-publish.yml")
    build_meta = next(s for s in wf["jobs"]["build"]["steps"] if s.get("id") == "meta")
    merge_meta = next(s for s in wf["jobs"]["merge"]["steps"] if s.get("id") == "meta")
    blocks = {
        "labels": _oci_values(build_meta["with"]["labels"]),
        "annotations": _oci_values(merge_meta["with"]["annotations"]),
    }
    assert labels["title"] == "Labelyard"
    for name, values in blocks.items():
        for key in ("title", "description", "url", "documentation", "source"):
            assert values[key] == labels[key], f"{name}: {key}"
    assert labels["description"] == TAGLINE
    assert labels["url"] == "https://labelyard.app"
    assert labels["documentation"] == "https://labelyard.app/"
    assert labels["source"] == "https://github.com/strausmann/labelyard"


def test_dockerhub_description_workflow() -> None:
    wf = _load("dockerhub-description.yml")
    # Forks skip the job instead of failing on missing secrets.
    assert [job.get("if") for job in wf["jobs"].values()] == [
        "github.repository_owner == 'strausmann'"
    ]
    triggers = wf.get("on", wf.get(True))
    assert "workflow_dispatch" in triggers
    assert triggers["push"]["branches"] == ["main"]
    assert triggers["push"]["paths"] == [".github/dockerhub/README.md"]
    steps = [s for j in wf["jobs"].values() for s in j["steps"]]
    action = [
        s for s in steps if str(s.get("uses", "")).startswith("peter-evans/dockerhub-description@")
    ]
    assert len(action) == 1
    with_ = action[0]["with"]
    assert with_["password"] == "${{ secrets.DOCKERHUB_ADMIN_TOKEN }}"
    assert with_["repository"] == "${{ secrets.DOCKERHUB_USERNAME }}/labelyard"
    assert with_["readme-filepath"] == ".github/dockerhub/README.md"
    assert with_["short-description"] == TAGLINE
    assert len(with_["short-description"].encode()) <= 100
    readme = REPO_ROOT / ".github" / "dockerhub" / "README.md"
    assert len(readme.read_bytes()) <= 25_000
    text = readme.read_text(encoding="utf-8")
    for needle in (
        "docker pull ghcr.io/strausmann/labelyard",
        "docker pull docker.io/",
        "https://labelyard.app",
    ):
        assert needle in text, needle
    # Docker Hub resolves no relative paths: every image is an absolute URL.
    images = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)
    images += re.findall(r'<img[^>]+src="([^"]+)"', text)
    assert images
    for target in images:
        assert target.startswith("https://raw.githubusercontent.com/"), target


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
        "registry-cleanup.yml",
        "preview-image.yml",
        "dockerhub-description.yml",
    ):
        for job_name, job in _load(name)["jobs"].items():
            for step in job.get("steps", []):
                uses = step.get("uses")
                if uses:
                    assert sha.match(uses), (
                        f"{name}/{job_name}: {uses} is not pinned to a 40-character commit SHA"
                    )


# Legacy major-tag actions in ci.yml; any other action there must be SHA-pinned.
_CI_MAJOR_TAG_ALLOWED = {
    "actions/checkout@v6",
    "actions/setup-python@v6",
    "actions/setup-node@v6",
    "actions/upload-artifact@v7",
    "pnpm/action-setup@v4",
    "codecov/codecov-action@v7",
    "codecov/test-results-action@v1",
    "docker/setup-buildx-action@v4",
    "docker/build-push-action@v7",
}


def test_ci_new_actions_are_sha_pinned() -> None:
    sha = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
    for job_name, job in _load("ci.yml")["jobs"].items():
        for step in job.get("steps", []):
            uses = step.get("uses")
            if uses and uses not in _CI_MAJOR_TAG_ALLOWED:
                assert sha.match(uses), f"ci.yml/{job_name}: {uses} must be SHA-pinned"


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


# The semver check as a whole-string bash match: `printf | grep -Eq` tests every
# line on its own and accepts "1.1.0\nx" (F-B6-2).
_SEMVER_CHECK = "semver='^v?[0-9]+\\.[0-9]+\\.[0-9]+(-[0-9A-Za-z.-]+)?$'"


def _run_bash(script: str, **env: str) -> int:
    """Run a workflow step script with only PATH and ``env`` set."""
    result = subprocess.run(
        ["bash", "-c", script],
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), **env},
        capture_output=True,
        check=False,
    )
    return result.returncode


def test_release_tag_regex_accepts_only_semver() -> None:
    wf = _load("docker-publish.yml")
    for job_name in ("build", "merge"):
        steps = wf["jobs"][job_name]["steps"]
        names = [str(s.get("name", s.get("uses", ""))) for s in steps]
        validate = names.index("Validate release tag input")
        checkout = next(i for i, s in enumerate(steps) if "actions/checkout" in str(s.get("uses")))
        assert validate < checkout, f"{job_name}: tag must be validated before the checkout"
        run = steps[validate]["run"]
        assert "grep -E" not in run, f"{job_name}: a line-based grep accepts a value with a newline"
        assert _SEMVER_CHECK in run, job_name
        # Empty means "not a release build" and passes.
        for ok in ("", "1.1.0", "v1.1.0", "0.0.0-ci.1", "2.0.0-rc.1"):
            assert _run_bash(run, INPUT_TAG=ok) == 0, repr(ok)
        bad_tags = (
            "1.1",
            "latest",
            "1.1.0;rm",
            "1.1.0 ",
            "../1.1.0",
            "v1.1.0\nx",
            "1.1.0\n",
            "1.1.0-",
        )
        for bad in bad_tags:
            assert _run_bash(run, INPUT_TAG=bad) != 0, repr(bad)


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
    assert wf["jobs"]["release-sbom"]["permissions"] == {"contents": "write"}
    assert _load("docker-publish.yml")["jobs"]["sbom"]["permissions"] == {
        "contents": "read",
        "packages": "read",
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


def _publish_build_step() -> dict[str, Any]:
    steps = _load("docker-publish.yml")["jobs"]["build"]["steps"]
    found = [s for s in steps if str(s.get("uses", "")).startswith("docker/build-push-action@")]
    assert len(found) == 1
    return found[0]


def test_provenance_max() -> None:
    with_ = _publish_build_step()["with"]
    # Explicit, not the default: mode=max records the build arguments, which here are only
    # VERSION, REVISION and BUILD_DATE.
    assert with_["provenance"] == "mode=max"
    assert with_["sbom"] is True


def test_ci_image_check() -> None:
    job = _load("ci.yml")["jobs"]["docker-build"]
    # A required status check in the main ruleset: the display name must not change.
    assert job["name"] == "Docker — build smoke test"
    assert job["env"]["IMAGE"] == "labelyard:ci"
    steps = job["steps"]
    build = [s for s in steps if str(s.get("uses", "")).startswith("docker/build-push-action@")]
    assert len(build) == 1
    assert build[0]["with"]["load"] is True
    assert build[0]["with"]["tags"] == "${{ env.IMAGE }}"
    syft = [s for s in steps if "download-syft" in str(s.get("uses", ""))]
    assert len(syft) == 1
    assert re.match(r"^[^@\s]+@[0-9a-f]{40}$", syft[0]["uses"]), syft[0]["uses"]
    assert syft[0]["with"]["syft-version"] == "v1.55.0"
    gate = next(s for s in steps if "+sbom-cataloger" in str(s.get("run", "")))
    assert "jq -e" in gate["run"]
    assert not gate.get("continue-on-error")
    info = next(s for s in steps if s.get("name") == "Default catalogue (informational)")
    assert info["continue-on-error"] is True
    runs = "\n".join(str(s.get("run", "")) for s in steps)
    assert "+sbom-cataloger" in runs
    for needle in ("backend.json", "frontend.json", "frontend.cdx.json", "agpl-3.0.txt"):
        assert needle in runs, needle


def test_sbom_job_is_read_only() -> None:
    wf = _load("docker-publish.yml")
    job = wf["jobs"]["sbom"]
    assert job["permissions"] == {"contents": "read", "packages": "read"}
    assert job["needs"] == "merge"
    assert job["if"] == "inputs.tag != ''"
    # The image build never writes to a release; only release.yml attaches the asset.
    assert "gh release" not in _text("docker-publish.yml")
    assert job["outputs"]["asset"]


def test_sbom_uses_merge_image_ref() -> None:
    wf = _load("docker-publish.yml")
    merge = wf["jobs"]["merge"]
    assert merge["outputs"]["image-ref"] == "${{ steps.image.outputs.ref }}"
    assert merge["outputs"]["tag"] == "${{ steps.tag.outputs.tag }}"
    assert any(s.get("id") == "image" for s in merge["steps"])
    assert any(s.get("id") == "tag" for s in merge["steps"])
    sbom = json.dumps(wf["jobs"]["sbom"])
    assert "needs.merge.outputs.image-ref" in sbom
    assert "ghcr.io/" not in sbom
    assert "docker.io/" not in sbom
    steps = wf["jobs"]["sbom"]["steps"]
    runs = "\n".join(str(s.get("run", "")) for s in steps)
    assert "${{" not in runs, "expressions reach run: only through env:"
    assert "--select-catalogers +sbom-cataloger" in runs
    assert "--platform linux/amd64" in runs
    assert "jq -e" in runs
    for name in ("react", "brother-ql", "tini"):
        assert f'index("{name}")' in runs, name
    upload = [s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
    assert len(upload) == 1
    assert upload[0]["with"]["name"] == "release-sbom"
    assert upload[0]["with"]["retention-days"] == 30


def test_release_sbom_job() -> None:
    wf = _load("release.yml")
    job = wf["jobs"]["release-sbom"]
    images = wf["jobs"]["images"]
    assert {"release", "images"} <= set(job["needs"])
    assert job["if"] == images["if"]
    assert job["permissions"] == {"contents": "write"}
    steps = job["steps"]
    assert not _checkout_steps(job), "the job needs no repository contents"
    for step in steps:
        assert "${{ inputs." not in str(step.get("run", ""))
        assert "${{ needs." not in str(step.get("run", ""))
    text = json.dumps(job)
    assert "secrets." not in text
    env = {k: v for s in steps for k, v in (s.get("env") or {}).items()}
    assert env["GH_REPO"] == "${{ github.repository }}"
    assert env["GH_TOKEN"] == "${{ github.token }}"
    assert env["VERSION"] == "${{ needs.release.outputs.new-release-version }}"
    runs = "\n".join(str(s.get("run", "")) for s in steps)
    assert _SEMVER_CHECK in runs
    assert "grep -E" not in runs
    check = runs[: runs.index('VERSION="${VERSION#v}"')]
    assert _run_bash(check, VERSION="1.6.0") == 0
    for bad in ("1.6.0\nx", "1.6", "latest"):
        assert _run_bash(check, VERSION=bad) != 0, repr(bad)
    assert 'gh release upload "v${VERSION}" ./*.cdx.json --clobber' in runs
    # The release carries exactly one SBOM afterwards (F-B6-1).
    assert 'select(endswith(".cdx.json"))] | length' in runs
    assert 'test "$count" -eq 1' in runs
    download = [s for s in steps if str(s.get("uses", "")).startswith("actions/download-artifact@")]
    assert len(download) == 1
    assert download[0]["with"]["name"] == "release-sbom"


# Keyless cosign signing (#311). Pins re-resolved on 2026-11-14.
_COSIGN_INSTALLER = "sigstore/cosign-installer@756fe2d284c7292c4e9b62c8a28f1e5629c59532"
_DIGEST_CHECK = "^sha256:[0-9a-f]{64}$"
# The refs that are signed; the certificate identity in docs/supply-chain.md ends with the same
# group (test_licence_metadata.COSIGN_IDENTITY_REGEXP).
SIGNED_REFS = r"^refs/(heads/main|heads/milestone/[0-9]+\.[0-9]+\.(0|x))$"


def _merge_steps() -> list[dict[str, Any]]:
    steps = _load("docker-publish.yml")["jobs"]["merge"]["steps"]
    assert isinstance(steps, list)
    return steps


def _signing_step_index(steps: list[dict[str, Any]]) -> int:
    found = [i for i, s in enumerate(steps) if "cosign sign" in str(s.get("run", ""))]
    assert len(found) == 1, "exactly one signing step in job merge"
    return found[0]


def test_merge_signs_index_digest() -> None:
    steps = _merge_steps()
    installers = [
        (i, s)
        for i, s in enumerate(steps)
        if str(s.get("uses", "")).startswith("sigstore/cosign-installer@")
    ]
    assert len(installers) == 1
    installer_index, installer = installers[0]
    assert installer["uses"] == _COSIGN_INSTALLER
    assert re.match(r"^v\d+\.\d+\.\d+$", str(installer["with"]["cosign-release"]))

    sign_index = _signing_step_index(steps)
    sign = steps[sign_index]
    run = str(sign["run"])
    # The digest, never a tag: one `cosign sign` per repository, `<repo>@<digest>`.
    assert re.search(r'cosign sign --yes "\$\{?repo\}?@\$\{?DIGEST\}?"', run), run
    assert ":${" not in run, "a tag must not be signed"
    assert "${{" not in run, "expressions reach run: only through env:"
    assert sign["env"]["TAGS"] == "${{ steps.meta.outputs.tags }}"

    creates = [i for i, s in enumerate(steps) if "imagetools create" in str(s.get("run", ""))]
    assert len(creates) == 1
    create_index = creates[0]
    assert "--metadata-file" in str(steps[create_index]["run"])
    verifies = [i for i, s in enumerate(steps) if s.get("name") == "Verify multi-arch manifest"]
    assert len(verifies) == 1
    # Signed only after the index was pushed and checked for both platforms.
    assert create_index < verifies[0] < installer_index < sign_index


def test_signing_is_keyless() -> None:
    text = _text("docker-publish.yml")
    for needle in ("COSIGN_KEY", "COSIGN_PASSWORD", "--key"):
        assert needle not in text, needle
    wf = _load("docker-publish.yml")
    assert wf["permissions"]["id-token"] == "write"
    merge_permissions = wf["jobs"]["merge"].get("permissions")
    assert merge_permissions is None or merge_permissions.get("id-token") == "write"
    # The caller caps the permissions of the called workflow.
    assert _load("release.yml")["jobs"]["images"]["permissions"]["id-token"] == "write"
    assert _load("preview-image.yml")["jobs"]["publish"]["permissions"]["id-token"] == "write"


def test_digest_is_validated() -> None:
    steps = _merge_steps()
    run = str(steps[_signing_step_index(steps)]["run"])
    assert _DIGEST_CHECK in run
    assert run.index(_DIGEST_CHECK) < run.index("cosign sign")
    assert "containerimage.descriptor" in run


def test_cleanup_keeps_signature_children() -> None:
    steps = _load("registry-cleanup.yml")["jobs"]["ghcr"]["steps"]
    prune = [
        s for s in steps if str(s.get("uses", "")).startswith("dataaxiom/ghcr-cleanup-action@")
    ]
    assert len(prune) == 1
    # Guards only the pin: the GHCR signature tag `sha256-<digest>` survives because this action
    # version treats it as a child of its image (src/utils.ts:50-54 parentDigestFromReferrerTag,
    # src/package-repo.ts:193-203, src/manifest-analyzer.ts:133-151). A new SHA must re-check them.
    assert (
        prune[0]["uses"] == "dataaxiom/ghcr-cleanup-action@d52806a0dc70b430571a37da1fde39733ffd640f"
    )
    assert prune[0]["with"]["delete-orphaned-images"] is True


def test_signing_only_on_publishing_refs() -> None:
    steps = _merge_steps()
    sign = steps[_signing_step_index(steps)]
    run = str(sign["run"])
    assert sign["env"]["REF"] == "${{ github.ref }}"
    assert f"signed_refs='{SIGNED_REFS}'" in run
    gate = run.index('[[ "$REF" =~ $signed_refs ]]')
    assert gate < run.index("cosign sign")
    # The gate as bash runs it: a ref outside the list exits 0 before any cosign call.
    check = run[: run.index("DIGEST=")]
    for ref in (
        "refs/heads/main",
        "refs/heads/milestone/1.6.0",
        "refs/heads/milestone/1.5.x",
    ):
        result = subprocess.run(
            ["bash", "-c", check + "\necho SIGN"],
            env={**os.environ, "REF": ref},
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0 and "SIGN" in result.stdout, ref
    for ref in (
        "refs/heads/feat/x",
        "refs/heads/main-x",
        "refs/heads/milestone/1.6.1",
        # Tags are not a publishing ref (no tag ruleset; releases are built on main).
        "refs/tags/v1.6.0",
        "refs/tags/v1.6.0-rc.1",
        "refs/tags/v1.6",
        "refs/pull/1/merge",
        "",
    ):
        result = subprocess.run(
            ["bash", "-c", check + "\necho SIGN"],
            env={**os.environ, "REF": ref},
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0 and "SIGN" not in result.stdout, ref
    # Same refs as the identity users verify against.
    doc = (REPO_ROOT / "docs" / "supply-chain.md").read_text(encoding="utf-8")
    identities = set(re.findall(r"--certificate-identity-regexp '([^']*)'", doc))
    assert identities
    for identity in identities:
        assert identity.endswith("docker-publish\\.yml@" + SIGNED_REFS[1:]), identity
