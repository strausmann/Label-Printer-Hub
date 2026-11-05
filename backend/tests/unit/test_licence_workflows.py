"""Guard tests for the licence gate workflows.

These check the TEXT of the workflow files, not their run. The live behaviour (a disallowed
direct or transitive dependency turns the check red, a Markdown-only change stays green) was
proven on throw-away pull requests; these tests keep the wiring that proof depends on.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def _load(name: str) -> dict[Any, Any]:
    data = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _triggers(workflow: dict[Any, Any]) -> dict[str, Any]:
    # PyYAML reads the bare key `on` as the boolean True.
    triggers = workflow[True] if True in workflow else workflow["on"]
    assert isinstance(triggers, dict)
    return triggers


def test_gate_runs_on_every_pull_request_to_main() -> None:
    pull_request = _triggers(_load("licence-gate.yml"))["pull_request"]
    assert pull_request["branches"] == ["main"]
    # A required check that a paths filter skips never reports and blocks docs-only PRs.
    assert "paths" not in pull_request
    assert "paths-ignore" not in pull_request


def test_gate_job_is_named_dependency_review_and_reads_the_one_policy() -> None:
    workflow = _load("licence-gate.yml")
    job = workflow["jobs"]["dependency-review"]
    assert job["name"] == "Dependency review"
    review = next(s for s in job["steps"] if "dependency-review-action" in s.get("uses", ""))
    assert review["with"]["config-file"] == "./licence-policy.yml"
    assert workflow["permissions"] == {"contents": "read"}


def test_gate_refuses_dependencies_with_an_undetectable_licence() -> None:
    steps = _load("licence-gate.yml")["jobs"]["dependency-review"]["steps"]
    review = next(s for s in steps if "dependency-review-action" in s.get("uses", ""))
    refuse = next(s for s in steps if "could not be detected" in s.get("name", ""))
    assert steps.index(refuse) > steps.index(review)
    assert "always()" in refuse["if"]
    assert "steps.review.outputs.invalid-license-changes" in refuse["if"]
    # Untrusted action output reaches the shell through env only, never inline.
    assert "${{" not in refuse["run"]
    assert "unlicensed" in refuse["run"]
    # CI actions have no licence in the graph and are not redistributed: not a defect.
    assert 'select(.ecosystem != "actions")' in refuse["run"]


def test_backend_check_only_runs_when_dependencies_or_the_policy_change() -> None:
    triggers = _triggers(_load("licence-backend.yml"))
    assert set(triggers["pull_request"]["paths"]) == {
        "backend/pyproject.toml",
        "licence-policy.yml",
        "backend/scripts/licence_report.py",
        ".github/workflows/licence-backend.yml",
    }
    assert "workflow_dispatch" in triggers


def test_dockerfile_checks_licences_and_keeps_the_tool_out_of_runtime() -> None:
    text = (REPO_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    builder, _, runtime = text.partition("AS runtime")
    assert "licence_report.py" in builder
    assert "pip-licenses==5.5.5" in builder
    assert "/opt/licence" not in runtime
    assert "pip-licenses" not in runtime
