"""Phase 1i Sub-Task G stub — full implementation in Task 8."""
from __future__ import annotations

from typing import Any


class BrotherQLBackend:
    backend_id = "brother_ql"
    half_cut_supported: bool = False

    def __init__(self, host: str, *, port: int = 9100, model_id: str = "QL-820NWB") -> None:
        self.host = host
        self._port = port
        self._model_id = model_id

    async def print_image(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("BrotherQLBackend.print_image — implemented in Task 8")

    async def query_status(self) -> Any:
        raise NotImplementedError("BrotherQLBackend.query_status — implemented in Task 8")
