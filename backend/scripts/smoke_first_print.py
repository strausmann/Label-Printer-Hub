"""Manual hardware smoke for First-Print.

Run against a real Brother PT-P750W on the local network:

    PRINTER_HUB_PT750W_HOST=<printer-ip> \\
        python -m scripts.smoke_first_print

Prints the qr-only-24mm template once with primary_id=SMOKE-001 and a
QR-encodable URL. Exits 0 on success, non-zero with a clear message on
failure.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# PTouchBackend and PTP750WDriver register themselves as side-effects of being imported.
from app.printer_backends import BackendRegistry
from app.printer_backends.ptouch_backend import PTouchBackend
from app.printer_models.pt import PTP750WDriver
from app.printer_models.registry import ModelRegistry
from app.schemas.label_data import LabelData
from app.services.label_renderer import LabelRenderer
from app.services.tape_registry import TapeRegistry
from app.services.template_loader import TemplateLoader
from PIL import Image

_TEMPLATE_ID = "qr-only-24mm"
_SMOKE_PRIMARY_ID = "SMOKE-001"
_SMOKE_QR_PAYLOAD = "https://example.test/smoke"


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
    template = TemplateLoader.get(_TEMPLATE_ID)
    label_data = LabelData(
        title="Smoke",
        primary_id=_SMOKE_PRIMARY_ID,
        qr_payload=_SMOKE_QR_PAYLOAD,
        secondary=(),
        source_app="manual",
    )
    image: Image.Image = LabelRenderer().render(template, label_data)

    print(f"[1/3] template={_TEMPLATE_ID}, image={image.size}")  # noqa: T201
    print(f"[2/3] querying printer status @ {host}...")  # noqa: T201
    status = await backend.query_status()
    print(  # noqa: T201
        f"      loaded_tape_mm={status.loaded_tape_mm}, media_type={status.media_type}"
    )
    print("[3/3] printing...")  # noqa: T201
    await printer.print_image(image, tape_mm=template.tape_mm)
    print("OK")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
