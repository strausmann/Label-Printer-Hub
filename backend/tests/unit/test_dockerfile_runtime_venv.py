# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The runtime venv must not carry pip, setuptools or wheel (#332).

pip bundles a vendored setuptools/pkg_resources 70.3.0 (CVE-2025-47273), which image scanners
report against ``/opt/venv``. The hub imports none of the three at runtime, so the builder stage
uninstalls them. This checks the TEXT of ``backend/Dockerfile``: the uninstall exists, comes after
the last install into the venv and before the licence report (so ``backend.json`` matches the
venv), and the runtime stage takes the venv from the builder without reinstalling anything.
A text check cannot prove the built image; the build was inspected by hand (``pip list`` and
``importlib.metadata`` inside the image) and scanned with Trivy.
"""

from __future__ import annotations

import re
from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[2] / "Dockerfile"
TEXT = DOCKERFILE.read_text(encoding="utf-8")


def test_builder_uninstalls_pip_setuptools_and_wheel() -> None:
    match = re.search(r"^RUN pip uninstall -y (.+)$", TEXT, re.MULTILINE)
    assert match, "the builder stage must uninstall the build tooling from /opt/venv"
    assert {"pip", "setuptools", "wheel"} <= set(match.group(1).split())


def test_uninstall_runs_after_the_last_venv_install_and_before_the_licence_report() -> None:
    uninstall = TEXT.index("RUN pip uninstall -y")
    last_install = TEXT.rindex("pip install --no-deps --force-reinstall .")
    licence_report = TEXT.index("/opt/licence/licence_report.py")
    assert last_install < uninstall < licence_report


def test_runtime_stage_installs_nothing_into_the_venv() -> None:
    runtime = TEXT.split("AS runtime", 1)[1]
    assert "COPY --from=builder --chown=hub:hub /opt/venv /opt/venv" in runtime
    assert not re.search(r"\bpip\s+install\b", runtime)
    assert "setuptools" not in runtime
