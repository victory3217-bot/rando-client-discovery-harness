# -*- coding: utf-8 -*-
"""Plain-text formats: TXT, MD, CSV. Standard library only.

Three formats, no third-party dependency, and a decoding step shared with nothing else in the
harness: Korean business documents exported from older tooling are still frequently CP949, so
the encoding ladder in ``core.intake.policy`` is not decoration.
"""
from __future__ import annotations

import csv
import re
from io import StringIO

from adapters.intake.guard import parser_guard
from core.errors import IntakeError, IntakeErrorCode
from core.intake.extract import make_segment
from core.intake.models import DocumentSegment, ExtractedDocument, SegmentKind
from core.intake.policy import DEFAULT_POLICY, IntakePolicy, decode_text
from core.models import FileType

#: Rows per CSV segment. Small enough to stay quotable, large enough that a table does not
#: shatter into hundreds of fragments.
CSV_ROWS_PER_SEGMENT = 50

#: Markdown ATX heading, e.g. ``## 시장 개요``.
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")

_BLANK_LINE_BLOCK = re.compile(r"\n\s*\n")


def _txt_segments(text: str) -> list[DocumentSegment]:
    """Blank-line separated blocks, located by the line range they occupy."""
    segments: list[DocumentSegment] = []
    line_no = 1
    order = 0

    for block in _BLANK_LINE_BLOCK.split(text):
        block_lines = block.count("\n") + 1
        start, end = line_no, line_no + block_lines - 1
        locator = f"line {start}" if start == end else f"line {start}-{end}"
        segment = make_segment(block, locator, kind=SegmentKind.PARAGRAPH, order=order)
        if segment is not None:
            segments.append(segment)
            order += 1
        # +1 for the blank line that separated this block from the next
        line_no = end + 2

    return segments


def _md_segments(text: str) -> list[DocumentSegment]:
    """Sections delimited by ATX headings, located by the heading they sit under."""
    segments: list[DocumentSegment] = []
    order = 0
    current_heading: str | None = None
    buffer: list[str] = []
    start_line = 1

    def flush(end_line: int) -> None:
        nonlocal order, buffer
        if not buffer:
            return
        locator = current_heading or f"line {start_line}-{end_line}"
        kind = SegmentKind.HEADING if current_heading and len(buffer) == 1 else SegmentKind.PARAGRAPH
        segment = make_segment("\n".join(buffer), locator, kind=kind, order=order)
        if segment is not None:
            segments.append(segment)
            order += 1
        buffer = []

    lines = text.splitlines()
    for index, line in enumerate(lines, start=1):
        match = _MD_HEADING.match(line)
        if match:
            flush(index - 1)
            current_heading = f"{match.group(1)} {match.group(2).strip()}".strip()
            start_line = index
            buffer = [line]
        else:
            if not buffer:
                start_line = index
            buffer.append(line)

    flush(len(lines))
    return segments


def _csv_segments(text: str) -> list[DocumentSegment]:
    """Row blocks, each carrying the header so the block reads on its own."""
    reader = csv.reader(StringIO(text))
    rows = [row for row in reader]
    if not rows:
        return []

    header = rows[0]
    header_line = " | ".join(cell.strip() for cell in header)
    body = rows[1:]

    if not body:
        segment = make_segment(header_line, "row 1", kind=SegmentKind.TABLE, order=0)
        return [segment] if segment else []

    segments: list[DocumentSegment] = []
    order = 0
    for offset in range(0, len(body), CSV_ROWS_PER_SEGMENT):
        chunk = body[offset : offset + CSV_ROWS_PER_SEGMENT]
        # Row numbers are 1-based and include the header row, so the first body row is row 2.
        start = offset + 2
        end = start + len(chunk) - 1
        lines = [header_line] + [" | ".join(cell.strip() for cell in row) for row in chunk]
        locator = f"row {start}-{end}" if end > start else f"row {start}"
        segment = make_segment("\n".join(lines), locator, kind=SegmentKind.TABLE, order=order)
        if segment is not None:
            segments.append(segment)
            order += 1

    return segments


class TextParser:
    """TXT, MD and CSV. Implements :class:`core.interfaces.intake.DocumentParser`."""

    name = "text"
    supported_types = frozenset({FileType.TXT, FileType.MD, FileType.CSV})

    def __init__(self, policy: IntakePolicy = DEFAULT_POLICY) -> None:
        self.policy = policy

    def parse(self, data: bytes, *, file_type: FileType) -> ExtractedDocument:
        if file_type not in self.supported_types:
            raise IntakeError(IntakeErrorCode.UNSUPPORTED_FILE_TYPE, parser=self.name)

        # decode_text raises TEXT_DECODE_FAILED, which the guard passes through untouched.
        text = decode_text(data)

        with parser_guard(self.name):
            if file_type is FileType.CSV:
                segments = _csv_segments(text)
            elif file_type is FileType.MD:
                segments = _md_segments(text)
            else:
                segments = _txt_segments(text)

        return ExtractedDocument(
            file_type=file_type,
            byte_size=len(data),
            segments=segments,
            page_count=None,
            # No language detection in this harness: an absent tag beats a guessed one.
            detected_lang=None,
            parser_name=self.name,
        )
