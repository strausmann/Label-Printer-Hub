"""Manual hardware smoke for First-Print.

Run against a real Brother PT-P750W on the local network:

    PRINTER_HUB_PT750W_HOST=<printer-ip> \\
        python -m scripts.smoke_first_print

Flow:
  1. SNMP preflight against the printer — read status + loaded tape width.
  2. Pick the qr-only-<n>mm seed template that matches the loaded tape.
  3. Render with primary_id=SMOKE-001 and a QR-encodable URL.
  4. Submit through the queue-printer (which re-runs preflight internally).

Exits 0 on success, non-zero with a clear message on failure.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Side-effect imports register the backend + driver.
from app.printer_backends import BackendRegistry
from app.printer_backends.exceptions import (
    PrinterCoverOpenError,
    PrinterError,
    PrinterOfflineError,
    TapeEmptyError,
    TapeMismatchError,
)
from app.printer_backends.ptouch_backend import PTouchBackend
from app.printer_models.pt import PTP750WDriver
from app.printer_models.registry import ModelRegistry
from app.schemas.label_data import LabelData
from app.services.label_renderer import LabelRenderer
from app.services.tape_registry import TapeRegistry
from app.services.template_loader import TemplateLoader
from PIL import Image

_SMOKE_PRIMARY_ID = "SMOKE-001"
_SMOKE_QR_PAYLOAD = "https://example.test/smoke"
# Smallest tape supported as a QR-only template. Adjust if the seed-templates
# directory adds more variants.
_SUPPORTED_TAPE_MM = (12, 18, 24)


def _qr_only_template_for(tape_mm: int) -> str:
    return f"qr-only-{tape_mm}mm"


async def main() -> int:
    host = os.environ.get("PRINTER_HUB_PT750W_HOST", "")
    if not host:
        print(  # noqa: T201 - CLI script
            "error: set PRINTER_HUB_PT750W_HOST to the printer's IP/hostname",
            file=sys.stderr,
        )
        return 2

    BackendRegistry.ensure_discovered()
    ModelRegistry.ensure_discovered()

    backend = PTouchBackend(host=host, model_id="PT-P750W")
    driver = PTP750WDriver(backend=backend)
    printer = driver.make_queue_printer(TapeRegistry())

    seed_dir = Path(__file__).resolve().parent.parent / "app" / "seed" / "templates"
    TemplateLoader.load_dir(seed_dir)

    print(f"[1/4] preflight @ {host} (SNMP) ...")  # noqa: T201
    try:
        preflight = await backend.preflight_check()
    except PrinterOfflineError as exc:
        print(f"FAIL: printer offline — {exc}", file=sys.stderr)  # noqa: T201
        return 3
    except TapeEmptyError:
        print("FAIL: tape is empty — insert tape and retry", file=sys.stderr)  # noqa: T201
        return 3
    except PrinterCoverOpenError:
        print("FAIL: cover is open — close and retry", file=sys.stderr)  # noqa: T201
        return 3
    print(  # noqa: T201
        f"      status={preflight.hr_printer_status}, "
        f"loaded_tape_mm={preflight.loaded_tape_mm}, "
        f"errors={preflight.error_flags}"
    )
    if preflight.loaded_tape_mm is None:
        print("FAIL: no tape detected", file=sys.stderr)  # noqa: T201
        return 3
    if preflight.loaded_tape_mm not in _SUPPORTED_TAPE_MM:
        print(  # noqa: T201
            f"FAIL: loaded tape {preflight.loaded_tape_mm}mm has no "
            f"qr-only template (have: {_SUPPORTED_TAPE_MM})",
            file=sys.stderr,
        )
        return 3

    template_id = _qr_only_template_for(preflight.loaded_tape_mm)
    template = TemplateLoader.get(template_id)
    label_data = LabelData(
        title="Smoke",
        primary_id=_SMOKE_PRIMARY_ID,
        qr_payload=_SMOKE_QR_PAYLOAD,
        secondary=(),
        source_app="manual",
    )
    image: Image.Image = LabelRenderer().render(template, label_data)
    print(f"[2/4] template={template_id}, image={image.size}")  # noqa: T201

    print("[3/4] sending to printer ...")  # noqa: T201
    try:
        await printer.print_image(image, tape_mm=template.tape_mm)
    except TapeMismatchError as exc:
        print(  # noqa: T201
            f"FAIL: tape mismatch (expected {exc.expected_mm}mm, loaded {exc.loaded_mm}mm)",
            file=sys.stderr,
        )
        return 3
    except PrinterError as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)  # noqa: T201
        return 3

    print("[4/4] OK — print sent successfully")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
