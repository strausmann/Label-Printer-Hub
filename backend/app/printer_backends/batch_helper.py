"""Default batch-print loop for Backends without native batch support.

Phase 1k.2: PTouchBackend overrides print_images() to use ptouch.print_multi()
for true atomic batch printing. BrotherQLBackend, MockBackend etc. delegate
their print_images() implementation to default_print_images_loop() here —
they loop over print_image() with correct half_cut + last_page semantics.

Semantics match the Brother iOS App: half_cut=True between intermediate
items (5mm taktile Trennung), half_cut=False + last_page=True on the final
item (voller Cut zur Trennung vom nächsten Batch).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image

    from app.models.tape import TapeSpec
    from app.printer_backends.base import PrinterBackend


async def default_print_images_loop(
    backend: PrinterBackend,
    images: list[Image.Image],
    tape_spec: TapeSpec,
    *,
    auto_cut: bool = True,
    high_resolution: bool = False,
    half_cut: bool = True,
) -> None:
    """Loop over print_image(); set half_cut + last_page per index.

    Args:
        backend: PrinterBackend instance whose print_image() is called per item.
        images: Rendered PIL Images, one per batch item, in print order.
        tape_spec: Shared TapeSpec — all items in a batch share the loaded tape.
        auto_cut: Forwarded unchanged to each print_image call.
        high_resolution: Forwarded unchanged to each print_image call.
        half_cut: If True, intermediate items get half_cut=True (5mm taktile
            separation). Last item always gets half_cut=False so the cutter
            performs a full cut for batch separation.

    Behaviour:
        For each image at index i:
          - is_last = (i == len(images) - 1)
          - last_page = is_last  (drives ptouch feed= → controls Pre-Roll)
          - half_cut = half_cut and not is_last
    """
    last_index = len(images) - 1
    for i, image in enumerate(images):
        is_last = i == last_index
        await backend.print_image(
            image,
            tape_spec,
            auto_cut=auto_cut,
            high_resolution=high_resolution,
            half_cut=half_cut and not is_last,
            last_page=is_last,
        )
