# -*- coding: utf-8 -*-
"""Pure transforms: segments to candidates, and candidates to provenance.

No I/O, no parsing libraries, no knowledge of where the bytes came from. An adapter has already
turned a file into an :class:`~core.intake.models.ExtractedDocument`; from here on it is data.
"""
from __future__ import annotations

import re
from typing import Optional

from core.intake.models import (
    DocumentSegment,
    EvidenceCandidate,
    ExtractedDocument,
    SegmentKind,
)
from core.intake.policy import DEFAULT_POLICY, IntakePolicy, normalize_display_label
from core.models import (
    ProcessingStatus,
    SourceCategory,
    SourceMetadata,
    SourceOrigin,
)

#: Below this a segment is noise — a stray page number, a lone bullet glyph, a table gutter.
#: Carrying them forward inflates the evidence set without adding anything citable.
MIN_SEGMENT_CHARS = 2

_TRAILING_WHITESPACE = re.compile(r"[ \t]+$", re.MULTILINE)
_EXCESS_BLANK_LINES = re.compile(r"\n{3,}")


def clean_segment_text(text: str) -> str:
    """Tidy whitespace without touching content.

    Deliberately conservative: no case folding, no punctuation stripping, no de-hyphenation.
    Evidence has to remain quotable back to the reader of the original document.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = _TRAILING_WHITESPACE.sub("", normalized)
    normalized = _EXCESS_BLANK_LINES.sub("\n\n", normalized)
    return normalized.strip()


def make_segment(
    text: str,
    locator: str,
    *,
    kind: SegmentKind = SegmentKind.PARAGRAPH,
    order: int = 0,
) -> Optional[DocumentSegment]:
    """Build a segment, or ``None`` when there is nothing worth keeping."""
    cleaned = clean_segment_text(text)
    if len(cleaned) < MIN_SEGMENT_CHARS:
        return None
    return DocumentSegment(text=cleaned, locator=locator, kind=kind, order=order)


def candidates_from(
    document: ExtractedDocument,
    *,
    project_id: str,
    source_id: str,
) -> list[EvidenceCandidate]:
    """Turn every segment into a candidate, preserving order and locator."""
    return [
        EvidenceCandidate(
            project_id=project_id,
            source_id=source_id,
            text=segment.text,
            locator=segment.locator,
            kind=segment.kind,
            order=segment.order,
        )
        for segment in document.segments
    ]


def source_metadata_from(
    document: ExtractedDocument,
    *,
    project_id: str,
    source_category: SourceCategory,
    source_id: Optional[str] = None,
    display_label: Optional[str] = None,
    source_date: Optional[str] = None,
    policy: IntakePolicy = DEFAULT_POLICY,
    processing_status: ProcessingStatus = ProcessingStatus.EXTRACTED,
) -> SourceMetadata:
    """Assemble the record that may be kept, from the document that may not.

    Note what is *not* copied across: no text, no filename, no path. ``display_label`` is only
    what a person typed, already normalised; it is never derived from the upload.
    """
    metadata = SourceMetadata(
        project_id=project_id,
        source_origin=SourceOrigin.UPLOADED_FILE,
        source_category=source_category,
        file_type=document.file_type,
        file_size=document.byte_size,
        page_count=document.page_count,
        source_date=source_date,
        detected_lang=document.detected_lang,
        processing_status=processing_status,
        display_label=normalize_display_label(display_label, policy),
    )
    if source_id is not None:
        metadata.source_id = source_id
    return metadata


def provenance_of(candidate: EvidenceCandidate, source: SourceMetadata) -> dict:
    """The provenance fields a ``ResearchFinding`` built from this candidate must carry.

    Phase 3 supplies the interpretation; this supplies the trail. Going through this function
    rather than copying fields by hand is what stops a finding from quietly losing its source —
    and ``core.evidence.check_finding`` rejects a ``FACT`` that has no ``source_id``.
    """
    return {
        "source_id": source.source_id,
        "source_type": source.source_category,
        "page_or_section": candidate.locator,
        "source_date": source.source_date,
    }
