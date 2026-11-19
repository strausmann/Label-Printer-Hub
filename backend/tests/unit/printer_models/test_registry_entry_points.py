# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Every shipped printer-model driver is an entry point (#207)."""

from __future__ import annotations

import subprocess
import sys


def test_registry_finds_the_ql_driver_without_importing_it() -> None:
    """A fresh process that never imports ``app.printer_models.ql`` still finds the QL driver."""
    code = (
        "import sys\n"
        "from app.printer_models.registry import ModelRegistry\n"
        "assert 'app.printer_models.ql' not in sys.modules\n"
        "ModelRegistry.ensure_discovered()\n"
        "driver = ModelRegistry.find_by_model_id('QL-820NWB')\n"
        "assert driver.model_id == 'QL-820NWB'\n"
        "ModelRegistry.find_by_model_id('PT-P750W')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=False
    )
    assert result.returncode == 0, result.stderr
