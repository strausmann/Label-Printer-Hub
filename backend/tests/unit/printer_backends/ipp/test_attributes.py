"""Attribute summary and status mapping (spec 11.1, 11.3, OC-18, OC-20).

The attribute dictionaries are built by hand, never by the codec: printers
answer with whatever they like and the mapping must cope. Two shapes follow the
interop note (``docs/research/2026-11-05-ipp-client-interop.md``) for the two
``ippeveprinter`` set-ups; only the attributes the note names are taken from it,
the rest is plausible filler and is marked as such.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from app.printer_backends.ipp import attributes
from app.printer_backends.ipp.attributes import (
    PRINTER_ATTRS,
    Margins,
    map_status,
    summarise,
)
from app.printer_backends.ipp.codec import Collection, OutOfBand, Range, Resolution, Tag, Value

Attrs = dict[str, list[Value]]


@pytest.fixture(autouse=True)
def _fresh_warning_cache() -> Iterator[None]:
    attributes._warn_once.cache_clear()
    yield
    attributes._warn_once.cache_clear()


def _base(**over: list[Value]) -> Attrs:
    """A well-formed idle printer; keyword arguments replace attributes (underscore → dash)."""
    attrs: Attrs = {
        "printer-make-and-model": ["Acme Page 9000"],
        "ipp-versions-supported": ["1.1", "2.0"],
        "document-format-supported": ["application/pdf", "image/urf"],
        "printer-state": [3],
        "printer-state-reasons": ["none"],
        "printer-is-accepting-jobs": [True],
        "queued-job-count": [0],
    }
    for key, value in over.items():
        attrs[key.replace("_", "-")] = value
    return attrs


def _media_col(source: str, x: int = 21000, y: int = 29700, **extra: list[Value]) -> Collection:
    members: dict[str, list[Value]] = {
        "media-size": [Collection({"x-dimension": [x], "y-dimension": [y]})],
        "media-source": [source],
    }
    members.update({k.replace("_", "-"): v for k, v in extra.items()})
    return Collection(members)


# ---------------------------------------------------------------- requested attributes


def test_printer_attrs_cover_the_brief() -> None:
    assert len(PRINTER_ATTRS) == len(set(PRINTER_ATTRS))
    for name in (
        "printer-make-and-model",
        "job-creation-attributes-supported",
        "media-col-supported",
        "media-col-ready",
        "printer-state-reasons",
        "marker-low-levels",
        "queued-job-count",
        "media-right-margin-supported",
        "media-default",
        "printer-uuid",
    ):
        assert name in PRINTER_ATTRS
    assert len(PRINTER_ATTRS) == 31
    assert "document-format-version-supported" in PRINTER_ATTRS


# ---------------------------------------------------------------- map_status


def test_map_status_real_shape() -> None:
    """The real-device example of the spec, shown as is: stopped, toner low, black 0 %."""
    rec = map_status(
        _base(
            printer_state=[5],
            printer_state_reasons=["toner-low-warning"],
            marker_names=["black"],
            marker_levels=[0],
            marker_types=["toner-cartridge"],
        )
    )
    assert rec.kind == "page"
    assert rec.online is True
    assert rec.printer_state == "stopped"
    assert rec.warnings == ["toner-low"]
    assert rec.blocking_reason is None
    assert [(r.keyword, r.severity, r.blocking) for r in rec.reasons] == [
        ("toner-low", "warning", False)
    ]
    (marker,) = rec.markers
    assert (marker.name, marker.type) == ("black", "toner-cartridge")
    assert marker.level_percent == 0
    assert marker.low is True
    assert marker.empty is True


def test_toner_empty_blocks() -> None:
    rec = map_status(_base(printer_state=[5], printer_state_reasons=["toner-empty-error"]))
    assert rec.blocking_reason == "toner-empty"
    assert rec.reasons[0].blocking is True


@pytest.mark.parametrize(
    ("reason", "keyword", "severity", "blocking"),
    [
        ("media-jam", "media-jam", "error", True),
        ("toner-low", "toner-low", "warning", False),
        ("marker-supply-low", "marker-supply-low", "warning", False),
        ("media-low", "media-low", "warning", False),
        ("developer-low", "developer-low", "warning", False),
        ("some-unknown-thing", "some-unknown-thing", "error", True),
        ("media-empty-warning", "media-empty", "warning", True),
        ("cover-open-report", "cover-open", "report", True),
        ("sleep-mode-report", "sleep-mode", "report", False),
        ("spool-area-full-warning", "spool-area-full", "warning", False),
        ("fuser-over-temp-error", "fuser-over-temp", "error", True),
        ("toner-low-report", "toner-low", "report", False),
    ],
)
def test_reason_without_suffix_is_error(
    reason: str, keyword: str, severity: str, blocking: bool
) -> None:
    rec = map_status(_base(printer_state_reasons=[reason]))
    (r,) = rec.reasons
    assert (r.keyword, r.severity, r.blocking) == (keyword, severity, blocking)
    assert rec.blocking_reason == (keyword if blocking else None)
    assert (keyword in rec.warnings) == (severity == "warning")


@pytest.mark.parametrize(
    "base", ["media-empty", "media-jam", "door-open", "cover-open", "toner-empty", "paused"]
)
def test_every_blocking_base_blocks_with_any_suffix(base: str) -> None:
    for suffix in ("", "-report", "-warning", "-error"):
        rec = map_status(_base(printer_state_reasons=[base + suffix]))
        assert rec.blocking_reason == base, base + suffix


def test_first_blocking_reason_is_reported_and_none_is_ignored() -> None:
    rec = map_status(
        _base(
            printer_state_reasons=[
                "none",
                "toner-low-warning",
                "door-open-error",
                "media-jam-error",
            ]
        )
    )
    assert rec.blocking_reason == "door-open"
    # blockers first in the displayed list, wire order inside each group
    assert [r.keyword for r in rec.reasons] == ["door-open", "media-jam", "toner-low"]


def test_state_mapping() -> None:
    assert map_status(_base(printer_state=[3])).printer_state == "idle"
    assert map_status(_base(printer_state=[4])).printer_state == "printing"
    assert map_status(_base(printer_state=[5])).printer_state == "stopped"


def _no_state(a: Attrs) -> None:
    del a["printer-state"]


def _state(value: Value) -> Callable[[Attrs], None]:
    def mutate(a: Attrs) -> None:
        a["printer-state"] = [value]

    return mutate


def _set(name: str, *values: Value) -> Callable[[Attrs], None]:
    def mutate(a: Attrs) -> None:
        a[name] = list(values)

    return mutate


HOSTILE: list[tuple[str, Callable[[Attrs], None], Callable[[Any], None]]] = []


def _case(
    name: str, mutate: Callable[[Attrs], None]
) -> Callable[[Callable[[Any], None]], Callable[[Any], None]]:
    def register(check: Callable[[Any], None]) -> Callable[[Any], None]:
        HOSTILE.append((name, mutate, check))
        return check

    return register


@_case("no-printer-state", _no_state)
def _(rec: Any) -> None:
    assert rec.printer_state == "stopped"
    assert rec.reasons[0].keyword == "unknown-state"
    assert rec.reasons[0].severity == "error"
    assert rec.blocking_reason == "unknown-state"


@_case("state-7", _state(7))
def _(rec: Any) -> None:
    assert rec.printer_state == "stopped"
    assert rec.reasons[0].keyword == "unknown-state"


@_case("state-text", _state("idle"))
def _(rec: Any) -> None:
    assert rec.printer_state == "stopped"
    assert rec.reasons[0].keyword == "unknown-state"


@_case("state-out-of-band", _state(OutOfBand(Tag.NO_VALUE)))
def _(rec: Any) -> None:
    assert rec.printer_state == "stopped"


@_case(
    "levels-as-text",
    lambda a: a.update({"marker-names": ["black", "cyan"], "marker-levels": ["half", "full"]}),
)
def _(rec: Any) -> None:
    assert [m.name for m in rec.markers] == ["black", "cyan"]
    assert [m.level_percent for m in rec.markers] == [None, None]


@_case(
    "three-names-two-levels",
    lambda a: a.update({"marker-names": ["a", "b", "c"], "marker-levels": [10, 20]}),
)
def _(rec: Any) -> None:
    assert [(m.name, m.level_percent) for m in rec.markers] == [("a", 10), ("b", 20)]


@_case(
    "level-codes",
    lambda a: a.update({"marker-names": ["a", "b", "c", "d"], "marker-levels": [-1, -2, -3, 150]}),
)
def _(rec: Any) -> None:
    assert [m.level_percent for m in rec.markers] == [None, None, None, None]
    assert [m.some_remaining for m in rec.markers] == [False, False, True, False]
    assert not any(m.empty or m.low for m in rec.markers)


@_case("5000-reasons", lambda a: a.update({"printer-state-reasons": ["toner-low-warning"] * 5000}))
def _(rec: Any) -> None:
    assert len(rec.reasons) == 32


@_case(
    "bad-reasons",
    _set(
        "printer-state-reasons",
        "bad reason!",
        "x" * 300,
        "UPPER case",
        "",
        "door-open",
        "x" * 64,
        "x" * 65,
        7,
        b"raw",
    ),
)
def _(rec: Any) -> None:
    assert [r.keyword for r in rec.reasons] == ["door-open", "x" * 64]


@_case("no-media-source", lambda a: a.update({"media-col-ready": [_media_col("tray-1")]}))
def _(rec: Any) -> None:
    assert rec.trays == []


@_case(
    "everything-wrong-type",
    lambda a: a.update(
        {
            "marker-names": [1, 2],
            "marker-colors": [b"x"],
            "marker-levels": [Collection({})],
            "marker-low-levels": [Range(1, 2)],
            "marker-types": [True],
            "queued-job-count": ["many"],
            "media-source-supported": [5],
            "media-col-ready": ["not a collection"],
            "media-ready": [9],
        }
    ),
)
def _(rec: Any) -> None:
    assert rec.jobs_ahead is None
    assert rec.trays == []


@_case(
    "huge-lists",
    lambda a: a.update(
        {
            "marker-names": [f"m{i}" for i in range(5000)],
            "marker-levels": list(range(5000)),
            "media-source-supported": [f"tray-{i}" for i in range(5000)],
        }
    ),
)
def _(rec: Any) -> None:
    assert len(rec.markers) <= 64
    assert len(rec.trays) <= 64
    assert len(rec.summary.media_sources) <= 64


@_case(
    "long-strings",
    lambda a: a.update(
        {
            "marker-names": ["n" * 5000],
            "marker-colors": ["c" * 5000],
            "marker-types": ["t" * 5000],
            "printer-make-and-model": ["m" * 5000],
        }
    ),
)
def _(rec: Any) -> None:
    assert len(rec.markers[0].name) <= 120
    assert rec.markers[0].color is None or len(rec.markers[0].color) <= 120
    assert rec.markers[0].type is None or len(rec.markers[0].type) <= 120
    assert rec.summary.make_and_model is not None and len(rec.summary.make_and_model) <= 120


@_case("empty-attributes", lambda a: a.clear())
def _(rec: Any) -> None:
    assert rec.printer_state == "stopped"
    assert rec.markers == [] and rec.trays == []
    assert rec.summary.pdf_supported is False


@_case("negative-queue", _set("queued-job-count", -4))
def _(rec: Any) -> None:
    assert rec.jobs_ahead is None


@pytest.mark.parametrize(
    ("mutate", "check"), [(m, c) for _, m, c in HOSTILE], ids=[n for n, _, _ in HOSTILE]
)
def test_map_status_hostile_inputs(
    mutate: Callable[[Attrs], None], check: Callable[[Any], None]
) -> None:
    attrs = _base()
    mutate(attrs)
    rec = map_status(attrs)  # never raises
    check(rec)
    assert rec.online is True
    assert rec.kind == "page"


def test_hostile_input_is_logged_once_at_warning_without_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "SECRET-VALUE-FROM-PRINTER"
    attrs = _base(marker_names=["a"], marker_levels=[secret])
    with caplog.at_level(logging.WARNING, logger="app.printer_backends.ipp.attributes"):
        for _ in range(5):
            map_status(attrs)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "marker-levels" in warnings[0].getMessage()
    assert secret not in caplog.text


def test_missing_state_is_logged_once(caplog: pytest.LogCaptureFixture) -> None:
    attrs = _base()
    del attrs["printer-state"]
    with caplog.at_level(logging.WARNING, logger="app.printer_backends.ipp.attributes"):
        map_status(attrs)
        map_status(attrs)
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


def test_well_formed_answer_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger="app.printer_backends.ipp.attributes"):
        map_status(_base(marker_names=["black"], marker_levels=[50], marker_low_levels=[10]))
    assert caplog.records == []


# ---------------------------------------------------------------- markers


def test_marker_low_by_level_and_by_reason() -> None:
    rec = map_status(
        _base(
            marker_names=["black", "cyan", "waste"],
            marker_levels=[8, 50, 100],
            marker_low_levels=[10, 10, 10],
        )
    )
    assert [(m.low, m.empty) for m in rec.markers] == [
        (True, False),
        (False, False),
        (False, False),
    ]
    by_reason = map_status(
        _base(
            marker_names=["black"],
            marker_levels=[50],
            printer_state_reasons=["marker-supply-low-report"],
        )
    )
    assert by_reason.markers[0].low is True


def test_marker_empty_by_reason_and_unknown_level() -> None:
    rec = map_status(
        _base(
            marker_names=["black"],
            marker_levels=[-1],
            printer_state_reasons=["marker-supply-empty-error"],
        )
    )
    (m,) = rec.markers
    assert m.level_percent is None
    assert m.empty is True
    assert rec.blocking_reason == "marker-supply-empty"


def test_marker_fields() -> None:
    rec = map_status(
        _base(
            marker_names=["black", "cyan"],
            marker_colors=["#000000", "#00FFFF"],
            marker_types=["toner", "toner"],
            marker_levels=[75, 20],
            marker_low_levels=[10, 25],
        )
    )
    assert [m.color for m in rec.markers] == ["#000000", "#00FFFF"]
    assert [m.low for m in rec.markers] == [False, True]
    assert [m.level_percent for m in rec.markers] == [75, 20]


def test_markers_zip_over_the_shortest_present_list() -> None:
    rec = map_status(
        _base(marker_names=["a", "b", "c"], marker_colors=["#000000"], marker_levels=[1, 2, 3])
    )
    assert [m.name for m in rec.markers] == ["a"]


def test_no_marker_attributes_means_no_markers() -> None:
    assert map_status(_base()).markers == []


# ---------------------------------------------------------------- trays and queue


def test_trays_from_media_col_ready() -> None:
    rec = map_status(
        _base(
            media_source_supported=["auto", "main-tray", "manual"],
            media_col_ready=[
                _media_col("main-tray", media_type=["labels"]),
                _media_col("manual", media_key=["na_letter_8.5x11in"]),
            ],
        )
    )
    assert [(t.key, t.media, t.ready) for t in rec.trays] == [
        ("auto", None, False),
        ("main-tray", "21000x29700 labels", True),
        ("manual", "na_letter_8.5x11in", True),
    ]


def test_trays_from_media_ready_with_a_single_tray() -> None:
    rec = map_status(_base(media_source_supported=["main"], media_ready=["iso_a4_210x297mm"]))
    assert [(t.key, t.media, t.ready) for t in rec.trays] == [("main", "iso_a4_210x297mm", True)]


def test_media_ready_cannot_be_assigned_to_one_of_several_trays() -> None:
    rec = map_status(_base(media_source_supported=["a", "b"], media_ready=["iso_a4_210x297mm"]))
    assert [(t.key, t.media, t.ready) for t in rec.trays] == [
        ("a", None, False),
        ("b", None, False),
    ]


def test_jobs_ahead() -> None:
    assert map_status(_base(queued_job_count=[3])).jobs_ahead == 3
    assert map_status(_base(queued_job_count=[True])).jobs_ahead is None
    attrs = _base()
    del attrs["queued-job-count"]
    assert map_status(attrs).jobs_ahead is None


# ---------------------------------------------------------------- interop shapes


def test_reference_printer_a_shape() -> None:
    """ippeveprinter ``-f application/pdf`` as the interop note describes it: media-col-ready
    as nested collections, ``labels`` among the media types, no ``print-scaling-supported``."""
    attrs = _base(
        printer_make_and_model=["Example Printer"],
        job_creation_attributes_supported=["copies", "media", "media-col", "sides"],
        media_col_supported=["media-size", "media-type", "media-source"],
        media_type_supported=["labels", "stationery"],
        media_source_supported=["auto", "main"],
        media_col_ready=[_media_col("main", media_type=["stationery"])],
        document_format_supported=["application/pdf"],
    )
    summary = summarise(attrs)
    assert summary.pdf_supported is True
    assert summary.media_col_supported is True
    assert summary.media_col_members == ["media-size", "media-type", "media-source"]
    assert summary.scaling_none_supported is False
    assert "labels" in summary.media_types
    assert map_status(attrs).trays[1].ready is True


def test_reference_printer_b_shape() -> None:
    """The attribute-file printer: ``print-scaling-supported`` with ``none``, colour modes
    with ``monochrome``, a ``media-col`` the printer will not honour (it still lists it)."""
    summary = summarise(
        _base(
            job_creation_attributes_supported=["media-col", "print-scaling"],
            print_scaling_supported=["auto", "fill", "fit", "none"],
            print_color_mode_supported=["monochrome", "color"],
            media_type_supported=["labels", "stationery"],
        )
    )
    assert summary.scaling_none_supported is True
    assert summary.monochrome_supported is True
    assert summary.color_modes == ["monochrome", "color"]
    assert summary.media_col_supported is True


# ---------------------------------------------------------------- summarise


def test_summarise_resolution_and_margins() -> None:
    summary = summarise(
        _base(
            printer_resolution_supported=[
                Resolution(600, 600, 3),
                Resolution(1200, 600, 3),
                Resolution(236, 236, 4),
            ],
            media_top_margin_supported=[423, 500],
            media_bottom_margin_supported=[423],
            media_left_margin_supported=[500, 423],
            media_right_margin_supported=[Range(423, 600)],
        )
    )
    assert summary.resolutions_dpi == [1200, 600, 599]
    assert summary.margins_hmm == Margins(top=423, left=423, bottom=423, right=423)


def test_resolutions_are_deduplicated_and_junk_is_skipped() -> None:
    summary = summarise(
        _base(
            printer_resolution_supported=[
                Resolution(600, 300, 3),
                Resolution(600, 600, 3),
                Resolution(0, 0, 3),
                Resolution(-5, 5, 3),
                Resolution(600, 600, 9),
                "600x600",
            ]
        )
    )
    assert summary.resolutions_dpi == [600]


def test_margins_need_all_four_sides() -> None:
    assert summarise(_base(media_top_margin_supported=[423])).margins_hmm is None
    assert summarise(_base()).margins_hmm is None
    assert summarise(_base(media_top_margin_supported=[-1])).margins_hmm is None


def test_pdf_supported_flag() -> None:
    assert summarise(_base()).pdf_supported is True
    no_pdf = summarise(_base(document_format_supported=["image/urf", "image/jpeg"]))
    assert no_pdf.pdf_supported is False
    assert summarise(_base(document_format_supported=["APPLICATION/PDF"])).pdf_supported is True
    attrs = _base()
    del attrs["document-format-supported"]
    assert summarise(attrs).pdf_supported is False


def test_pdf_versions_come_from_the_version_attribute_when_present() -> None:
    summary = summarise(_base(document_format_version_supported=["1.4", "1.7"]))
    assert summary.pdf_versions == ["1.4", "1.7"]
    assert summarise(_base()).pdf_versions == []


@pytest.mark.parametrize(
    ("overrides", "supported", "members"),
    [
        ({"job_creation_attributes_supported": ["copies", "media-col"]}, True, []),
        (
            {
                "job_creation_attributes_supported": ["media-col"],
                "media_col_supported": ["media-size", "media-type"],
            },
            True,
            ["media-size", "media-type"],
        ),
        (
            {"media_col_supported": ["media-size", "media-type", "media-source"]},
            True,
            ["media-size", "media-type", "media-source"],
        ),
        ({"media_col_supported": ["media-size"]}, True, ["media-size"]),
        (
            {"media_col_supported": ["media-type", "media-source"]},
            False,
            ["media-type", "media-source"],
        ),
        # the printer lists its creation attributes and media-col is not among them
        (
            {
                "job_creation_attributes_supported": ["copies", "sides"],
                "media_col_supported": ["media-size"],
            },
            False,
            ["media-size"],
        ),
        ({}, False, []),
    ],
)
def test_media_col_detection(
    overrides: dict[str, list[Value]], supported: bool, members: list[str]
) -> None:
    summary = summarise(_base(**overrides))
    assert summary.media_col_supported is supported
    assert summary.media_col_members == members


def test_flags_and_lists() -> None:
    summary = summarise(
        _base(
            media_supported=["iso_a4_210x297mm", "na_letter_8.5x11in"],
            media_type_supported=["labels"],
            media_source_supported=["main", "manual"],
            print_color_mode_supported=["color"],
            sides_supported=["one-sided", "two-sided-long-edge"],
            print_scaling_supported=["auto", "fit"],
        )
    )
    assert summary.make_and_model == "Acme Page 9000"
    assert summary.ipp_versions == ["1.1", "2.0"]
    assert summary.media_sizes == ["iso_a4_210x297mm", "na_letter_8.5x11in"]
    assert summary.media_types == ["labels"]
    assert summary.media_sources == ["main", "manual"]
    assert summary.color_modes == ["color"]
    assert summary.one_sided_supported is True
    assert summary.scaling_none_supported is False
    assert summary.monochrome_supported is False
    assert summary.accepting_jobs is True
    assert summary.state == "idle"


def test_summary_state_and_accepting_jobs_when_unknown() -> None:
    summary = summarise({"printer-is-accepting-jobs": ["yes"], "printer-state": [9]})
    assert summary.state == "unknown"
    assert summary.accepting_jobs is None
    assert summarise(_base(printer_is_accepting_jobs=[False])).accepting_jobs is False
    assert summarise(_base(printer_state=[4])).state == "printing"
    assert summarise(_base(printer_state=[5])).state == "stopped"


def test_summary_lists_are_bounded() -> None:
    summary = summarise(
        _base(
            media_supported=[f"m{i}" for i in range(500)] + ["x" * 500, 3, "bad\x00key"],
            media_type_supported=["labels", OutOfBand(Tag.NO_VALUE)],
        )
    )
    assert len(summary.media_sizes) == 64
    assert all(len(s) <= 120 and "\x00" not in s for s in summary.media_sizes)
    assert summary.media_types == ["labels"]


def test_media_col_is_found_beyond_the_list_cut() -> None:
    """A printer with a long creation-attribute list must not hide ``media-col`` behind the cut."""
    listed: list[Value] = [f"attr-{i}" for i in range(200)] + ["media-col"]
    summary = summarise(_base(job_creation_attributes_supported=listed))
    assert summary.media_col_supported is True


# ---------------------------------------------------------------- fix round 1


def test_blocker_beyond_the_display_cut_still_blocks() -> None:
    reasons: list[Value] = (
        ["toner-low-warning"] * 40 + ["media-jam-error"] + ["sleep-mode-report"] * 20
    )
    rec = map_status(_base(printer_state_reasons=reasons))
    assert rec.blocking_reason == "media-jam"
    assert len(rec.reasons) == 32
    assert rec.reasons[0].keyword == "media-jam"  # blockers first in the displayed list
    assert rec.warnings == ["toner-low"]


def test_unknown_state_stays_within_the_display_cut() -> None:
    attrs = _base(printer_state_reasons=["door-open-error"] * 100)
    del attrs["printer-state"]
    rec = map_status(attrs)
    assert len(rec.reasons) == 32
    assert rec.blocking_reason == "unknown-state"


def test_reason_keywords_are_case_insensitive() -> None:
    rec = map_status(_base(printer_state_reasons=["Media-Jam-Error", "TONER-LOW-WARNING"]))
    assert rec.blocking_reason == "media-jam"
    assert rec.warnings == ["toner-low"]


def test_toner_low_error_blocks_by_design() -> None:
    """Spec 11.3: only bare ``toner-low`` and ``-warning`` are non-blocking; a printer that
    states ``-error`` is not reporting a mere low supply. Blocking only keeps the job queued."""
    rec = map_status(_base(printer_state_reasons=["toner-low-error"]))
    assert rec.blocking_reason == "toner-low"


def test_exactly_64_values_is_not_an_anomaly(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="app.printer_backends.ipp.attributes"):
        summarise(_base(media_supported=[f"m{i}" for i in range(64)]))
        assert caplog.records == []
        summarise(_base(media_supported=[f"m{i}" for i in range(65)]))
    assert len(caplog.records) == 1


def _color_printer(**over: list[Value]) -> Attrs:
    return _base(
        marker_names=["black", "cyan", "magenta", "yellow", "waste"],
        marker_types=["toner", "toner", "toner", "toner", "waste-toner"],
        **over,
    )


def test_reason_marks_only_the_toner_with_unknown_level_on_a_colour_printer() -> None:
    rec = map_status(
        _color_printer(
            marker_levels=[80, 5, -1, 60, -1],
            marker_low_levels=[10, 10, 10, 10, 10],
            printer_state_reasons=["toner-low-warning"],
        )
    )
    assert [m.low for m in rec.markers] == [False, True, True, False, False]  # cyan by level
    assert [m.empty for m in rec.markers] == [False] * 5


def test_reason_marks_every_toner_when_no_level_is_known_but_never_the_waste_container() -> None:
    rec = map_status(_color_printer(printer_state_reasons=["toner-empty-error"]))
    assert [m.empty for m in rec.markers] == [True, True, True, True, False]
    low = map_status(
        _color_printer(marker_levels=[-1] * 5, printer_state_reasons=["marker-supply-low-report"])
    )
    assert [m.low for m in low.markers] == [True, True, True, True, False]


def test_known_levels_win_over_the_reason_on_a_colour_printer() -> None:
    rec = map_status(
        _color_printer(
            marker_levels=[80, 70, 60, 50, 10], printer_state_reasons=["toner-empty-error"]
        )
    )
    assert not any(m.empty or m.low for m in rec.markers)


def test_reason_applies_to_the_only_supply_even_beside_a_waste_container() -> None:
    rec = map_status(
        _base(
            marker_names=["black", "waste"],
            marker_types=["toner", "waste-toner"],
            marker_levels=[50, 20],
            printer_state_reasons=["toner-low-warning"],
        )
    )
    assert [m.low for m in rec.markers] == [True, False]


def test_waste_is_recognised_by_name_when_the_type_is_missing() -> None:
    rec = map_status(
        _base(
            marker_names=["black", "Waste Toner Box"], printer_state_reasons=["toner-empty-error"]
        )
    )
    assert [m.empty for m in rec.markers] == [True, False]


def test_pdf_versions_are_summarised() -> None:
    attrs = _base(document_format_version_supported=["1.4", "1.7"])
    assert map_status(attrs).summary.pdf_versions == ["1.4", "1.7"]


def test_warnings_are_bounded_like_the_displayed_reasons() -> None:
    """Thousands of distinct warning keywords must not grow the status record unbounded."""
    reasons: list[Value] = [f"vendor-thing-{i}-warning" for i in range(500)]
    rec = map_status(_base(printer_state_reasons=reasons))
    assert len(rec.warnings) == 32
    assert rec.warnings[0] == "vendor-thing-0"


def test_media_default_is_summarised_and_requested() -> None:
    # The test print falls back to it when a tray reports no media (the HP reports only this).
    assert "media-default" in PRINTER_ATTRS
    assert summarise(_base(media_default=["iso_a4_210x297mm"])).media_default == "iso_a4_210x297mm"
    assert summarise(_base()).media_default is None
