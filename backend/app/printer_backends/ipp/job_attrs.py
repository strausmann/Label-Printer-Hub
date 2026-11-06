"""Print-Job attributes from the probe summary, the tray and the paper (spec 11.2, OC-19). Pure.

Only what the printer lists is sent: ``media-col`` when it accepts the attribute, with
``media-type`` and ``media-source`` only as far as the collection's members include them;
otherwise the ``media`` keyword. ``print-scaling``, ``print-color-mode`` and ``sides`` follow
their own flags. ``copies=1`` is always sent.
"""

from __future__ import annotations

from typing import Literal

from app.printer_backends.ipp.attributes import ProbeSummary
from app.printer_backends.ipp.codec import Attr, Collection, Tag, Value

USER_NAME = "label-printer-hub"
AUTO_TRAY = "auto"
MAX_JOB_NAME_BYTES = 255
"""``name(MAX)`` of RFC 8011 3.1.5."""

# hundredths of mm (media-size) and the PWG self-describing media keyword (PWG 5101.1)
_SIZES: dict[str, tuple[int, int, str]] = {
    "A4": (21000, 29700, "iso_a4_210x297mm"),
    "Letter": (21590, 27940, "na_letter_8.5x11in"),
}


def _job_name(name: str) -> str:
    """Cut to 255 octets on a character boundary."""
    return name.encode("utf-8")[:MAX_JOB_NAME_BYTES].decode("utf-8", errors="ignore")


def print_job_attributes(
    summary: ProbeSummary,
    *,
    media: Literal["A4", "Letter"],
    tray: str,
    job_name: str,
) -> tuple[list[Attr], list[Attr]]:
    """``(operation attributes, job attributes)`` for a Print-Job of one PDF page."""
    x, y, keyword = _SIZES[media]
    ops = [
        Attr("job-name", Tag.NAME, [_job_name(job_name)]),
        Attr("requesting-user-name", Tag.NAME, [USER_NAME]),
        Attr("document-format", Tag.MIME, ["application/pdf"]),
    ]
    job: list[Attr] = []
    if summary.media_col_supported:
        members: dict[str, list[Value]] = {
            "media-size": [Collection({"x-dimension": [x], "y-dimension": [y]})]
        }
        if "media-type" in summary.media_col_members:
            members["media-type"] = ["labels"]
        if "media-source" in summary.media_col_members and tray not in ("", AUTO_TRAY):
            members["media-source"] = [tray]
        job.append(Attr("media-col", Tag.BEG_COLLECTION, [Collection(members)]))
    else:
        job.append(Attr("media", Tag.KEYWORD, [keyword]))
    if summary.scaling_none_supported:
        job.append(Attr("print-scaling", Tag.KEYWORD, ["none"]))
    if summary.monochrome_supported:
        job.append(Attr("print-color-mode", Tag.KEYWORD, ["monochrome"]))
    job.append(Attr("copies", Tag.INTEGER, [1]))
    if summary.one_sided_supported:
        job.append(Attr("sides", Tag.KEYWORD, ["one-sided"]))
    return ops, job
