"""Manual hardware-smoke: 4-item batch via POST /batch endpoint.

Usage:
    python3 backend/scripts/smoke_first_print_batch.py [hub_url] [api_key]

Defaults to http://localhost:8000 + env $PRINTER_HUB_WEBHOOK_API_KEY.

Expected output: 4 labels on the tape strip, with ~5mm Half-Cut between each
item and a full cut at the end. Compare to Brother iOS App print quality.
"""

from __future__ import annotations

import os
import sys

import httpx

HUB_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
# Copilot-Review C9 (PR #106): kein hardcoded API-Key Default. Wenn weder
# CLI-Arg noch Env-Var gesetzt -> sofortiger Fehler mit klarer Meldung.
API_KEY = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("PRINTER_HUB_WEBHOOK_API_KEY")
if not API_KEY:
    print(  # noqa: T201 - CLI script
        "ERROR: API key required. Set $PRINTER_HUB_WEBHOOK_API_KEY or pass as 2nd CLI arg.",
        file=sys.stderr,
    )
    sys.exit(2)


def main() -> None:
    body = {
        "items": [
            {
                "template_id": "qr-only-12mm",
                "data": {
                    "primary_id": f"BATCH-{i + 1}",
                    "title": "Phase 1k.2 Smoke",
                    "qr_payload": f"https://hangar.example.test/smoke/batch/{i + 1}",
                },
            }
            for i in range(4)
        ],
    }
    resp = httpx.post(
        f"{HUB_URL}/api/print/brother-p750w/batch",
        json=body,
        headers={"X-Label-Hub-Key": API_KEY},
        timeout=30.0,
    )
    print(f"HTTP {resp.status_code}")  # noqa: T201 - CLI script
    print(resp.json())  # noqa: T201 - CLI script


if __name__ == "__main__":
    main()
