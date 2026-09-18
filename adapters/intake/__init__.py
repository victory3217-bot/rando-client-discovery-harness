# -*- coding: utf-8 -*-
"""File intake: the impure half.

Opening archives, running PDF and Office libraries, decoding bytes and releasing buffers all
happen here, because none of it is allowed in ``core/``. What the core owns is the policy these
adapters apply: limits, type-identification rules, text decoding and label cleaning all live in
``core.intake.policy``.

All eight supported formats parse from memory, so nothing in this package writes to disk.

Typical use:

    with IntakeSession(project_id, policy=IntakePolicy()) as session:
        result = session.ingest(data, file_type=FileType.PDF,
                                source_category=SourceCategory.COMPANY_DATA)
    storage.save_source_metadata(result.source)     # may be kept
    findings = diagnose(result.candidates)          # never kept
"""
from adapters.intake.guard import parser_guard
from adapters.intake.html import HtmlParser
from adapters.intake.office import OfficeParser, verify_ooxml_package
from adapters.intake.pdf import PdfParser
from adapters.intake.registry import ParserRegistry, default_parsers
from adapters.intake.safe_logging import (
    ALLOWED_LOG_FIELDS,
    safe_error_fields,
    safe_fields,
    safe_result_fields,
)
from adapters.intake.session import IntakeSession, release_buffer
from adapters.intake.text import TextParser

__all__ = [
    "ALLOWED_LOG_FIELDS",
    "HtmlParser",
    "IntakeSession",
    "OfficeParser",
    "ParserRegistry",
    "PdfParser",
    "TextParser",
    "default_parsers",
    "parser_guard",
    "release_buffer",
    "safe_error_fields",
    "safe_fields",
    "safe_result_fields",
    "verify_ooxml_package",
]
