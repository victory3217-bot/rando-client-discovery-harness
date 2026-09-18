# -*- coding: utf-8 -*-
"""Intake: parsers, policy, and failure modes.

The leakage tests live in ``test_intake_canary.py``; this module covers everything else.
"""
from __future__ import annotations

import pytest

from adapters.intake import IntakeSession, ParserRegistry, default_parsers
from adapters.intake.office import verify_ooxml_package
from core.errors import INTAKE_ERROR_CODES, IntakeError, IntakeErrorCode
from core.intake import (
    DEFAULT_POLICY,
    IntakePolicy,
    SegmentKind,
    candidates_from,
    decode_text,
    normalize_display_label,
    provenance_of,
    resolve_ooxml,
)
from core.intake.policy import check_declared_type
from core.interfaces.intake import DocumentParser
from core.models import FileType, ProcessingStatus, SourceCategory
from intake_fixtures import (
    BUILDERS,
    CANARY,
    make_csv,
    make_docx,
    make_encrypted_pdf_marker,
    make_html,
    make_non_ooxml_zip,
    make_pdf,
    make_txt,
    make_xlsx,
    make_zip_bomb,
)

PROJECT = "prj_intake_test"


def ingest(data, file_type, **kwargs):
    with IntakeSession(PROJECT, **kwargs.pop("session_kwargs", {})) as session:
        return session.ingest(
            bytearray(data),
            file_type=file_type,
            source_category=SourceCategory.COMPANY_DATA,
            **kwargs,
        )


# -- every format round-trips ---------------------------------------------

@pytest.mark.parametrize("type_name", sorted(BUILDERS))
def test_every_supported_type_produces_located_segments(type_name: str) -> None:
    result = ingest(BUILDERS[type_name](), FileType[type_name])

    assert result.ok, f"{type_name} failed with {result.source.error_code}"
    assert result.source.processing_status is ProcessingStatus.PURGED
    assert result.candidates, f"{type_name} produced no candidates"

    for candidate in result.candidates:
        assert candidate.locator.strip(), "every candidate must be citable"
        assert candidate.text.strip()
        assert candidate.source_id == result.source.source_id
        assert candidate.project_id == PROJECT


@pytest.mark.parametrize("type_name", sorted(BUILDERS))
def test_extraction_is_deterministic(type_name: str) -> None:
    """Same bytes, same segments in the same order — otherwise citations move between runs."""
    data = BUILDERS[type_name]()
    first = ingest(data, FileType[type_name])
    second = ingest(data, FileType[type_name])

    assert [(c.locator, c.text) for c in first.candidates] == [
        (c.locator, c.text) for c in second.candidates
    ]


def test_locator_shapes_match_the_documented_scheme() -> None:
    assert ingest(make_pdf(), FileType.PDF).candidates[0].locator == "p.1"
    assert ingest(make_xlsx(), FileType.XLSX).candidates[0].locator.startswith("utilities-ops!A1:")
    assert ingest(make_csv(), FileType.CSV).candidates[0].locator.startswith("row ")
    assert ingest(make_txt(), FileType.TXT).candidates[0].locator.startswith("line ")
    assert ingest(make_docx(), FileType.DOCX).candidates[0].locator.startswith("¶")

    pptx_locators = [c.locator for c in ingest(BUILDERS["PPTX"](), FileType.PPTX).candidates]
    assert "slide 1" in pptx_locators
    assert "slide 1 notes" in pptx_locators


def test_pptx_notes_are_kept_and_marked() -> None:
    """Speaker notes carry the argument behind a slide and are worth keeping, labelled."""
    result = ingest(BUILDERS["PPTX"](), FileType.PPTX)
    notes = [c for c in result.candidates if c.kind is SegmentKind.SLIDE_NOTE]
    assert len(notes) == 1
    assert CANARY in notes[0].text


def test_xlsx_reports_sheet_count_and_pdf_reports_pages() -> None:
    assert ingest(make_xlsx(), FileType.XLSX).source.page_count == 1
    assert ingest(make_pdf(), FileType.PDF).source.page_count == 1


# -- HTML only keeps what a person would read ------------------------------

def test_html_excludes_script_style_noscript_and_comments() -> None:
    result = ingest(make_html(), FileType.HTML)
    body = "\n".join(c.text for c in result.candidates)

    assert CANARY in body, "the visible paragraph must survive"
    for hidden in ("-IN-SCRIPT", "-IN-STYLE", "-IN-COMMENT", "-IN-NOSCRIPT"):
        assert hidden not in body, f"{hidden} reached an evidence candidate"


def test_html_locators_carry_the_enclosing_heading() -> None:
    result = ingest(make_html(), FileType.HTML)
    assert any(">" in c.locator for c in result.candidates)


# -- text decoding ---------------------------------------------------------

@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-8", "cp949"])
def test_supported_encodings_decode(encoding: str) -> None:
    result = ingest(make_txt(encoding=encoding), FileType.TXT)
    assert result.ok
    assert CANARY in "\n".join(c.text for c in result.candidates)


def test_bom_is_consumed_not_kept_as_text() -> None:
    result = ingest(make_txt(encoding="utf-8-sig"), FileType.TXT)
    assert not result.candidates[0].text.startswith("﻿")


def test_undecodable_bytes_report_a_code() -> None:
    undecodable = b"\xff\xfe\x00\x81\xff\xff\xfe\xfd" * 4
    with pytest.raises(IntakeError) as excinfo:
        decode_text(undecodable)
    assert excinfo.value.code == IntakeErrorCode.TEXT_DECODE_FAILED

    result = ingest(undecodable, FileType.TXT)
    assert result.source.error_code == IntakeErrorCode.TEXT_DECODE_FAILED
    assert result.source.processing_status is ProcessingStatus.FAILED


# -- OOXML identification --------------------------------------------------

def test_ooxml_types_are_told_apart_by_package_contents() -> None:
    """ZIP magic bytes are identical for all three, so the package has to be opened."""
    assert resolve_ooxml(["[Content_Types].xml", "word/document.xml"]) is FileType.DOCX
    assert resolve_ooxml(["[Content_Types].xml", "ppt/presentation.xml"]) is FileType.PPTX
    assert resolve_ooxml(["[Content_Types].xml", "xl/workbook.xml"]) is FileType.XLSX


def test_embedded_workbook_does_not_turn_a_docx_into_a_xlsx() -> None:
    """Matching on 'contains xl/' would misidentify a Word file with an embedded sheet."""
    names = ["[Content_Types].xml", "word/document.xml", "word/embeddings/sheet1.xlsx", "xl/"]
    assert resolve_ooxml(names) is FileType.DOCX


def test_zip_without_content_types_is_not_ooxml() -> None:
    assert resolve_ooxml(["readme.txt"]) is None


def test_renamed_ooxml_is_rejected() -> None:
    """A .docx declared as .xlsx passes the magic-byte check and must still be caught."""
    result = ingest(make_docx(), FileType.XLSX)
    assert result.source.error_code == IntakeErrorCode.TYPE_MISMATCH


def test_plain_zip_declared_as_docx_is_rejected() -> None:
    result = ingest(make_non_ooxml_zip(), FileType.DOCX)
    assert result.source.error_code == IntakeErrorCode.TYPE_MISMATCH


def test_corrupt_package_reports_malformed() -> None:
    result = ingest(b"PK\x03\x04" + b"\x00" * 64, FileType.DOCX)
    assert result.source.error_code == IntakeErrorCode.MALFORMED_DOCUMENT


# -- declared type vs magic bytes -----------------------------------------

def test_pdf_bytes_declared_as_csv_are_rejected() -> None:
    result = ingest(make_pdf(), FileType.CSV)
    assert result.source.error_code == IntakeErrorCode.TYPE_MISMATCH


def test_text_declared_as_pdf_is_rejected() -> None:
    result = ingest(make_txt(), FileType.PDF)
    assert result.source.error_code == IntakeErrorCode.TYPE_MISMATCH


def test_text_types_accept_text(monkeypatch) -> None:
    check_declared_type(FileType.CSV, b"utility,region")
    check_declared_type(FileType.MD, b"# heading")


# -- limits ----------------------------------------------------------------

def test_oversized_file_is_refused_before_parsing() -> None:
    policy = IntakePolicy(max_file_bytes=128)
    with IntakeSession(PROJECT, policy=policy) as session:
        result = session.ingest(
            bytearray(make_txt()),
            file_type=FileType.TXT,
            source_category=SourceCategory.COMPANY_DATA,
        )
    assert result.source.error_code == IntakeErrorCode.FILE_TOO_LARGE
    assert result.candidates == []


def test_batch_limit_stops_the_batch_not_the_process() -> None:
    data = make_txt()
    # Room for exactly one of these, so the first succeeds and the second is refused.
    policy = IntakePolicy(max_batch_bytes=len(data) + 1)

    with IntakeSession(PROJECT, policy=policy) as session:
        first = session.ingest(
            bytearray(data),
            file_type=FileType.TXT,
            source_category=SourceCategory.COMPANY_DATA,
        )
        second = session.ingest(
            bytearray(data),
            file_type=FileType.TXT,
            source_category=SourceCategory.COMPANY_DATA,
        )

    assert first.ok, first.source.error_code
    assert second.source.error_code == IntakeErrorCode.BATCH_TOO_LARGE


def test_zip_bomb_is_caught_from_the_central_directory() -> None:
    """The declared uncompressed total is checked before anything is expanded."""
    policy = IntakePolicy(max_uncompressed_bytes=1024)
    with pytest.raises(IntakeError) as excinfo:
        verify_ooxml_package(make_zip_bomb(declared_size=50 * 1024 * 1024), FileType.DOCX, policy)
    assert excinfo.value.code == IntakeErrorCode.ARCHIVE_LIMIT_EXCEEDED


def test_policy_is_data_not_configuration_the_core_reads() -> None:
    """The core never reads an environment variable; an application injects its own values."""
    custom = IntakePolicy(max_file_bytes=1, max_batch_bytes=2, max_uncompressed_bytes=3)
    assert (custom.max_file_bytes, custom.max_batch_bytes) == (1, 2)
    assert DEFAULT_POLICY.max_file_bytes == 25 * 1024 * 1024
    assert DEFAULT_POLICY.max_uncompressed_bytes == 200 * 1024 * 1024
    assert DEFAULT_POLICY.max_batch_bytes == 100 * 1024 * 1024


def test_policy_can_narrow_the_supported_types() -> None:
    policy = IntakePolicy(supported_types=frozenset({FileType.TXT}))
    registry = ParserRegistry(policy=policy)
    assert registry.supported_types() == frozenset({FileType.TXT})
    with pytest.raises(IntakeError) as excinfo:
        registry.for_type(FileType.PDF)
    assert excinfo.value.code == IntakeErrorCode.UNSUPPORTED_FILE_TYPE


# -- documents with nothing in them ---------------------------------------

def test_scanned_pdf_reports_no_text_layer() -> None:
    """No OCR in this harness: a scan fails honestly rather than being invented."""
    result = ingest(make_pdf(with_text_layer=False), FileType.PDF)
    assert result.source.error_code == IntakeErrorCode.EXTRACT_NO_TEXT_LAYER


def test_empty_text_document_reports_a_code() -> None:
    result = ingest(b"   \n\n  \n", FileType.TXT)
    assert result.source.error_code == IntakeErrorCode.EMPTY_DOCUMENT


def test_zero_byte_file_reports_a_code() -> None:
    result = ingest(b"", FileType.TXT)
    assert result.source.error_code == IntakeErrorCode.EMPTY_DOCUMENT


def test_encrypted_pdf_reports_a_code() -> None:
    result = ingest(make_encrypted_pdf_marker(), FileType.PDF)
    assert result.source.error_code in {
        IntakeErrorCode.ENCRYPTED_DOCUMENT,
        IntakeErrorCode.MALFORMED_DOCUMENT,
    }


def test_one_bad_file_does_not_end_the_batch() -> None:
    with IntakeSession(PROJECT) as session:
        bad = session.ingest(
            bytearray(b"PK\x03\x04garbage"),
            file_type=FileType.DOCX,
            source_category=SourceCategory.COMPANY_DATA,
        )
        good = session.ingest(
            bytearray(make_txt()),
            file_type=FileType.TXT,
            source_category=SourceCategory.COMPANY_DATA,
        )
    assert not bad.ok
    assert good.ok and good.candidates


def test_every_failure_uses_a_declared_code() -> None:
    """The code set is closed; no failure path may invent a new string."""
    failures = [
        ingest(make_pdf(), FileType.CSV),
        ingest(make_docx(), FileType.XLSX),
        ingest(b"", FileType.TXT),
        ingest(make_pdf(with_text_layer=False), FileType.PDF),
        ingest(b"\xff\xfe\x81\xff" * 8, FileType.TXT),
        ingest(b"PK\x03\x04" + b"\x00" * 32, FileType.PPTX),
    ]
    for result in failures:
        assert result.source.error_code in INTAKE_ERROR_CODES, result.source.error_code


# -- missing optional dependency -------------------------------------------

def test_missing_parser_library_is_a_code_not_a_crash(monkeypatch) -> None:
    """A deployment ingesting only CSV should not need pypdf installed."""
    import builtins

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "pypdf" or name.startswith("pypdf."):
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    result = ingest(make_pdf(), FileType.PDF)
    assert result.source.error_code == IntakeErrorCode.PARSER_UNAVAILABLE


# -- display_label ---------------------------------------------------------

def test_display_label_is_kept_when_a_person_supplies_one() -> None:
    result = ingest(make_txt(), FileType.TXT, display_label="회사소개서 2026")
    assert result.source.display_label == "회사소개서 2026"


def test_display_label_defaults_to_none() -> None:
    assert ingest(make_txt(), FileType.TXT).source.display_label is None


def test_display_label_strips_control_characters_without_joining_words() -> None:
    assert normalize_display_label("3분기\t전망\n보고") == "3분기 전망 보고"
    assert normalize_display_label("clean\x00\x1b[31mtext") == "clean [31mtext"
    assert normalize_display_label("   ") is None
    assert normalize_display_label(None) is None


def test_display_label_is_truncated_not_rejected() -> None:
    label = normalize_display_label("가" * 500)
    assert label is not None and len(label) == DEFAULT_POLICY.max_display_label_chars


def test_display_label_limit_is_policy_driven() -> None:
    policy = IntakePolicy(max_display_label_chars=5)
    assert normalize_display_label("abcdefghij", policy) == "abcde"


def test_display_label_is_never_derived_from_anything() -> None:
    """There is no filename parameter anywhere, so nothing can auto-fill this field."""
    import inspect

    for parser in default_parsers().values():
        params = set(inspect.signature(parser.parse).parameters)
        assert "filename" not in params and "path" not in params

    session_params = set(inspect.signature(IntakeSession.ingest).parameters)
    assert "filename" not in session_params and "path" not in session_params


# -- provenance ------------------------------------------------------------

def test_provenance_carries_everything_a_finding_needs() -> None:
    result = ingest(make_pdf(), FileType.PDF, source_date="2026-03-11")
    candidate = result.candidates[0]

    provenance = provenance_of(candidate, result.source)
    assert provenance["source_id"] == result.source.source_id
    assert provenance["page_or_section"] == "p.1"
    assert provenance["source_type"] is SourceCategory.COMPANY_DATA
    assert provenance["source_date"] == "2026-03-11"


def test_a_fact_built_from_provenance_satisfies_the_evidence_rules() -> None:
    """The Phase 2 to Phase 3 handover: provenance is what lets a finding claim FACT."""
    from core import evidence
    from core.models import Confidence, EvidenceType, ResearchFinding

    result = ingest(make_pdf(), FileType.PDF, source_date="2026-03-11")
    provenance = provenance_of(result.candidates[0], result.source)

    finding = ResearchFinding(
        project_id=PROJECT,
        finding="the utility publishes a quarterly schedule",
        evidence_type=EvidenceType.FACT,
        confidence=Confidence.MEDIUM,
        mn_basis=["MN03"],
        **provenance,
    )
    assert evidence.check_finding(finding) == []


# -- contracts -------------------------------------------------------------

def test_parsers_satisfy_the_protocol() -> None:
    for parser in default_parsers().values():
        assert isinstance(parser, DocumentParser)
        assert isinstance(parser.name, str) and parser.name


def test_every_supported_type_has_a_parser() -> None:
    assert set(default_parsers()) == set(FileType)


def test_candidates_preserve_segment_order() -> None:
    from core.intake.models import DocumentSegment, ExtractedDocument

    document = ExtractedDocument(
        file_type=FileType.TXT,
        byte_size=10,
        segments=[
            DocumentSegment(text="one", locator="line 1", order=0),
            DocumentSegment(text="two", locator="line 2", order=1),
        ],
    )
    candidates = candidates_from(document, project_id=PROJECT, source_id="src_1")
    assert [c.text for c in candidates] == ["one", "two"]
    assert [c.order for c in candidates] == [0, 1]


def test_detected_lang_is_never_guessed() -> None:
    """No language detection ships in this harness; an absent tag beats a wrong one."""
    for type_name in BUILDERS:
        result = ingest(BUILDERS[type_name](), FileType[type_name])
        assert result.source.detected_lang is None


def test_session_rejects_use_after_close() -> None:
    session = IntakeSession(PROJECT)
    session.close()
    with pytest.raises(RuntimeError):
        session.ingest(
            bytearray(make_txt()),
            file_type=FileType.TXT,
            source_category=SourceCategory.COMPANY_DATA,
        )


def test_session_clears_the_buffers_it_was_given() -> None:
    """Best-effort: a bytearray can be overwritten in place, and it is."""
    buffer = bytearray(make_txt())
    with IntakeSession(PROJECT) as session:
        session.ingest(
            buffer, file_type=FileType.TXT, source_category=SourceCategory.COMPANY_DATA
        )
    assert set(buffer) == {0}
