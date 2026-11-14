# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tape vocabulary shared by the schemas and the services.

It lives here, below the services, so that a schema can name it without importing a service.
"""

from __future__ import annotations

from typing import Literal

TapeColourName = Literal["white", "yellow", "green", "blue", "red", "black", "clear"]
