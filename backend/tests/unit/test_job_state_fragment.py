"""Verifiziert dass das job_state.html-Fragment data-job-id und data-state trägt."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from jinja2 import Environment, FileSystemLoader


@pytest.fixture
def jinja_env():
    # Hub-Templates liegen unter backend/app/templates/
    template_dir = Path(__file__).parent.parent.parent / "app" / "templates"
    # autoescape=True via select_autoescape default — no functional change
    # for our UUID/string substitutions, satisfies CodeQL py/jinja2-autoescape.
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=True,
    )


def test_job_state_fragment_has_data_job_id_and_state(jinja_env):
    """Das Root-<div> muss data-job-id und data-state tragen.

    Render-Context: Top-Level-Vars wie sie der Hub-Producer in event.data legt
    (job_id, from_state, to_state, queue_depth, error_code, timestamp).
    """
    job_id = str(uuid4())
    tmpl = jinja_env.get_template("fragments/job_state.html")
    rendered = tmpl.render(
        job_id=job_id,
        from_state="queued",
        to_state="printing",
        queue_depth=0,
        error_code=None,
        timestamp="2026-05-30T12:00:00Z",
    )
    assert f'data-job-id="{job_id}"' in rendered, (
        "job_state.html muss data-job-id auf dem Root-Element tragen "
        "damit der Hangar SSE-Proxy filtern kann"
    )
    assert 'data-state="printing"' in rendered, (
        "job_state.html muss data-state auf dem Root-Element tragen "
        "damit Hangar's parseHubEvent den State extrahieren kann (Spec §5.4)"
    )
