# -*- coding: utf-8 -*-
"""Intake: the pure half of turning documents into evidence candidates.

The impure half — opening archives, running PDF and Office parsers, managing buffers — lives in
``adapters/intake/``, because the core may not touch a file, a stream or a third-party library.
The split is not bureaucratic: it is what lets ``tests/test_core_standalone.py`` copy ``core/``
into an empty directory and still run it.

What this package owns:

* :mod:`core.intake.policy`  — limits, type-identification rules, text decoding, label cleaning
* :mod:`core.intake.models`  — transport objects that carry document text (never persisted)
* :mod:`core.intake.extract` — segments to candidates, candidates to provenance
"""
from core.intake.extract import (
    candidates_from,
    clean_segment_text,
    make_segment,
    provenance_of,
    source_metadata_from,
)
from core.intake.models import (
    DocumentSegment,
    EvidenceCandidate,
    ExtractedDocument,
    IntakeResult,
    SegmentKind,
)
from core.intake.policy import (
    DEFAULT_POLICY,
    IntakePolicy,
    check_archive_size,
    check_declared_type,
    decode_text,
    normalize_display_label,
    resolve_ooxml,
)

__all__ = [
    "DEFAULT_POLICY",
    "DocumentSegment",
    "EvidenceCandidate",
    "ExtractedDocument",
    "IntakePolicy",
    "IntakeResult",
    "SegmentKind",
    "candidates_from",
    "check_archive_size",
    "check_declared_type",
    "clean_segment_text",
    "decode_text",
    "make_segment",
    "normalize_display_label",
    "provenance_of",
    "resolve_ooxml",
    "source_metadata_from",
]
