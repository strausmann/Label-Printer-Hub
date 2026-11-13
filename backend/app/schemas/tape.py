"""Tape vocabulary shared by the schemas and the services.

It lives here, below the services, so that a schema can name it without importing a service.
"""

from __future__ import annotations

from typing import Literal

TapeColourName = Literal["white", "yellow", "green", "blue", "red", "black", "clear"]
