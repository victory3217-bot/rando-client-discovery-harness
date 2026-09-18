# -*- coding: utf-8 -*-
"""PDF text layer, via pypdf.

pypdf rather than PyMuPDF: PyMuPDF extracts text better, but it is AGPL-3.0 and this repository
is MIT. A licence that would change the terms under which anyone can embed this harness
outweighs extraction quality. pypdf is BSD-3 and, on Python 3.11 and later, has no required
runtime dependencies of its own.

**No OCR.** A scanned PDF has no text layer, and this parser says so with
``EXTRACT_NO_TEXT_LAYER`` rather than inventing content. OCR would need a system binary, and
OCR output used as the basis of a ``FACT`` is exactly the kind of confident-looking,
unverifiable claim this harness exists to prevent.
"""
from __future__ import annotations

import re
from io import BytesIO

from adapters.intake.guard import parser_guard
from core.errors import IntakeError, IntakeErrorCode
from core.intake.extract import make_segment
from core.intake.models import DocumentSegment, ExtractedDocument, SegmentKind
from core.intake.policy import DEFAULT_POLICY, IntakePolicy
from core.models import FileType

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


class PdfParser:
    """PDF. Implements :class:`core.interfaces.intake.DocumentParser`."""

    name = "pdf"
    supported_types = frozenset({FileType.PDF})

    def __init__(self, policy: IntakePolicy = DEFAULT_POLICY) -> None:
        self.policy = policy

    def parse(self, data: bytes, *, file_type: FileType) -> ExtractedDocument:
        if file_type is not FileType.PDF:
            raise IntakeError(IntakeErrorCode.UNSUPPORTED_FILE_TYPE, parser=self.name)

        # Imported here, not at module scope: a deployment that only ingests CSV should not
        # need pypdf installed, and a missing library should be a code, not a startup crash.
        try:
            from pypdf import PdfReader
        except ImportError:
            raise IntakeError(IntakeErrorCode.PARSER_UNAVAILABLE, parser=self.name) from None

        with parser_guard(self.name, code=IntakeErrorCode.MALFORMED_DOCUMENT):
            reader = PdfReader(BytesIO(data))

        if reader.is_encrypted:
            # An empty owner password is common and harmless to try; anything else is a
            # document we were not given the means to read.
            try:
                opened = reader.decrypt("")
            except Exception:  # noqa: BLE001
                opened = 0
            if not opened:
                raise IntakeError(IntakeErrorCode.ENCRYPTED_DOCUMENT, parser=self.name)

        segments: list[DocumentSegment] = []
        order = 0

        with parser_guard(self.name):
            page_count = len(reader.pages)
            for page_number, page in enumerate(reader.pages, start=1):
                try:
                    page_text = page.extract_text() or ""
                except Exception:  # noqa: BLE001
                    # One unreadable page does not condemn the document. Its absence shows up
                    # as a gap in the locators, which is honest.
                    continue

                for block in _PARAGRAPH_BREAK.split(page_text):
                    segment = make_segment(
                        block, f"p.{page_number}", kind=SegmentKind.PARAGRAPH, order=order
                    )
                    if segment is not None:
                        segments.append(segment)
                        order += 1

        if not segments:
            # Almost always a scan. Distinguishing it from a genuinely empty PDF is not worth
            # a heuristic; either way there is nothing to analyse and the operator needs to know.
            raise IntakeError(IntakeErrorCode.EXTRACT_NO_TEXT_LAYER, parser=self.name)

        return ExtractedDocument(
            file_type=file_type,
            byte_size=len(data),
            segments=segments,
            page_count=page_count,
            detected_lang=None,
            parser_name=self.name,
        )
