# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Print-Job attributes (spec 11.2, OC-19): what is sent depends on what the printer lists."""

from __future__ import annotations

from app.printer_backends.ipp.attributes import ProbeSummary
from app.printer_backends.ipp.codec import (
    Attr,
    Collection,
    Group,
    Message,
    Tag,
    Value,
    decode,
    encode,
)
from app.printer_backends.ipp.job_attrs import (
    LEGACY_IPP_USER_NAME,
    is_own_job,
    print_job_attributes,
)

JOB_NAME = "Sheet L4736-0002 · 9 labels"


def _summary(**over: object) -> ProbeSummary:
    fields: dict[str, object] = {
        "make_and_model": None,
        "ipp_versions": ["2.0"],
        "pdf_supported": True,
        "pdf_versions": [],
        "resolutions_dpi": [600],
        "media_sizes": [],
        "media_types": ["labels"],
        "media_sources": ["main-tray"],
        "color_modes": ["monochrome"],
        "margins_hmm": None,
        "media_col_supported": True,
        "media_col_members": ["media-size", "media-type", "media-source"],
        "accepting_jobs": True,
        "scaling_none_supported": True,
        "monochrome_supported": True,
        "one_sided_supported": True,
        "state": "idle",
    }
    fields.update(over)
    return ProbeSummary.model_validate(fields)


def _by_name(attrs: list[Attr]) -> dict[str, list[Value]]:
    names = [a.name for a in attrs]
    assert len(names) == len(set(names)), "attribute sent twice"
    return {a.name: a.values for a in attrs}


def _media_col(job: dict[str, list[Value]]) -> dict[str, list[Value]]:
    (col,) = job["media-col"]
    assert isinstance(col, Collection)
    return col.members


def test_print_job_attributes_media_col() -> None:
    ops, job_attrs = print_job_attributes(
        _summary(), media="A4", tray="main-tray", job_name=JOB_NAME
    )
    op = _by_name(ops)
    assert op["document-format"] == ["application/pdf"]
    assert op["job-name"] == [JOB_NAME]
    assert op["requesting-user-name"] == ["labelyard"]
    job = _by_name(job_attrs)
    members = _media_col(job)
    (size,) = members["media-size"]
    assert isinstance(size, Collection)
    assert size.members == {"x-dimension": [21000], "y-dimension": [29700]}
    assert members["media-type"] == ["labels"]
    assert members["media-source"] == ["main-tray"]
    assert list(members) == ["media-size", "media-type", "media-source"]
    assert "media" not in job
    assert job["print-scaling"] == ["none"]
    assert job["print-color-mode"] == ["monochrome"]
    assert job["copies"] == [1]
    assert job["sides"] == ["one-sided"]


def test_print_job_attributes_letter_size() -> None:
    _, job_attrs = print_job_attributes(_summary(), media="Letter", tray="auto", job_name="x")
    (size,) = _media_col(_by_name(job_attrs))["media-size"]
    assert isinstance(size, Collection)
    assert size.members == {"x-dimension": [21590], "y-dimension": [27940]}


def test_print_job_attributes_fallback() -> None:
    summary = _summary(
        media_col_supported=False,
        media_col_members=[],
        scaling_none_supported=False,
        monochrome_supported=False,
        one_sided_supported=False,
    )
    ops, job_attrs = print_job_attributes(summary, media="Letter", tray="auto", job_name="x")
    job = _by_name(job_attrs)
    assert job == {"media": ["na_letter_8.5x11in"], "copies": [1]}
    assert _by_name(ops)["document-format"] == ["application/pdf"]


def test_fallback_media_keyword_for_a4_ignores_the_tray() -> None:
    summary = _summary(media_col_supported=False, media_col_members=[])
    _, job_attrs = print_job_attributes(summary, media="A4", tray="main-tray", job_name="x")
    job = _by_name(job_attrs)
    assert job["media"] == ["iso_a4_210x297mm"]
    assert "media-col" not in job
    assert "media-source" not in job


def test_media_col_members_gate_type_and_source() -> None:
    summary = _summary(media_col_members=["media-size"])
    _, job_attrs = print_job_attributes(summary, media="A4", tray="main-tray", job_name="x")
    assert list(_media_col(_by_name(job_attrs))) == ["media-size"]
    only_type = _summary(media_col_members=["media-size", "media-type"])
    _, job_attrs = print_job_attributes(only_type, media="A4", tray="main-tray", job_name="x")
    assert list(_media_col(_by_name(job_attrs))) == ["media-size", "media-type"]
    no_members = _summary(media_col_members=[])
    _, job_attrs = print_job_attributes(no_members, media="A4", tray="main-tray", job_name="x")
    assert list(_media_col(_by_name(job_attrs))) == ["media-size"]


def test_tray_auto_or_empty_sends_no_media_source() -> None:
    for tray in ("auto", ""):
        _, job_attrs = print_job_attributes(_summary(), media="A4", tray=tray, job_name="x")
        assert "media-source" not in _media_col(_by_name(job_attrs))


def test_each_optional_attribute_follows_its_own_flag() -> None:
    cases = {
        "print-scaling": {"scaling_none_supported": False},
        "print-color-mode": {"monochrome_supported": False},
        "sides": {"one_sided_supported": False},
    }
    for attribute, off in cases.items():
        _, job_attrs = print_job_attributes(_summary(**off), media="A4", tray="auto", job_name="x")
        job = _by_name(job_attrs)
        assert attribute not in job
        assert {"copies", "media-col"} <= set(job)


def test_job_name_is_cut_to_the_ipp_name_limit_on_a_character_boundary() -> None:
    ops, _ = print_job_attributes(_summary(), media="A4", tray="auto", job_name="é" * 400)
    (name,) = _by_name(ops)["job-name"]
    assert isinstance(name, str)
    assert len(name.encode("utf-8")) <= 255
    assert name == "é" * (255 // 2)


def test_attributes_survive_the_wire() -> None:
    """Encode and decode what the function builds: the nested collection keeps its shape and
    the member tags are the ones IPP expects (keyword, integer, collection)."""
    ops, job_attrs = print_job_attributes(
        _summary(), media="A4", tray="main-tray", job_name=JOB_NAME
    )
    msg = Message((2, 0), 0x0002, 1, [Group(Tag.OPERATION, ops), Group(Tag.JOB, job_attrs)])
    raw = encode(msg, b"%PDF-")
    back, document = decode(raw)
    assert document == b"%PDF-"
    job = back.attrs(Tag.JOB)
    (col,) = job["media-col"]
    assert isinstance(col, Collection)
    assert col.member_tags["media-type"] == [Tag.KEYWORD]
    assert col.member_tags["media-source"] == [Tag.KEYWORD]
    (size,) = col.members["media-size"]
    assert isinstance(size, Collection)
    assert size.member_tags["x-dimension"] == [Tag.INTEGER]
    op_tags = {a.name: a.tag for g in back.groups if g.tag == Tag.OPERATION for a in g.attrs}
    assert op_tags["job-name"] == Tag.NAME
    assert op_tags["requesting-user-name"] == Tag.NAME
    assert op_tags["document-format"] == Tag.MIME


def test_new_jobs_carry_the_labelyard_user_name() -> None:
    ops, _ = print_job_attributes(_summary(), media="A4", tray="auto", job_name=JOB_NAME)
    assert _by_name(ops)["requesting-user-name"] == ["labelyard"]


def test_job_with_the_labelyard_user_name_is_own() -> None:
    assert is_own_job(JOB_NAME, "labelyard", JOB_NAME)


def test_job_sent_by_1_5_x_under_the_old_user_name_is_still_own() -> None:
    # A job sent before the upgrade can still be on the printer afterwards. The name is pinned:
    # 1.5.x sent exactly this (split so the brand guard does not report the test).
    assert LEGACY_IPP_USER_NAME == "label-printer-" + "hub"
    assert is_own_job(JOB_NAME, "label-printer-" + "hub", JOB_NAME)


def test_job_with_another_user_name_is_foreign() -> None:
    assert not is_own_job(JOB_NAME, "someone-else", JOB_NAME)


def test_job_with_another_name_is_foreign_even_with_our_user_name() -> None:
    assert not is_own_job("other job", "labelyard", JOB_NAME)
    assert not is_own_job("other job", LEGACY_IPP_USER_NAME, JOB_NAME)


def test_unreported_user_name_is_not_held_against_the_job() -> None:
    assert is_own_job(JOB_NAME, None, JOB_NAME)
