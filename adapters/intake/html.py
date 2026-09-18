# -*- coding: utf-8 -*-
"""HTML, using the standard library parser.

``beautifulsoup4`` would be the reflex choice, but its default backend *is* ``html.parser``, so
it buys nothing here that the standard library does not already provide. One fewer direct
dependency for the same result.

What never reaches an evidence candidate: ``<script>``, ``<style>``, ``<noscript>``,
``<template>`` and HTML comments. Script bodies are the largest text in many saved pages and
none of it is anything a person read; comments routinely hold internal notes, tracking ids and
draft copy that nobody intended to publish.
"""
from __future__ import annotations

from html.parser import HTMLParser

from adapters.intake.guard import parser_guard
from core.errors import IntakeError, IntakeErrorCode
from core.intake.extract import make_segment
from core.intake.models import DocumentSegment, ExtractedDocument, SegmentKind
from core.intake.policy import DEFAULT_POLICY, IntakePolicy, decode_text
from core.models import FileType

#: Content inside these is machine-facing, not something a reader saw.
SKIPPED_TAGS = frozenset({"script", "style", "noscript", "template", "svg", "head"})

HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})

#: Tags that end one readable block and start the next.
BLOCK_TAGS = frozenset(
    {
        "p", "div", "section", "article", "main", "aside", "header", "footer",
        "li", "dd", "dt", "td", "th", "caption", "figcaption", "blockquote", "pre",
        "tr", "table", "ul", "ol", "dl", "form", "nav",
    }
    | HEADING_TAGS
)

#: Longest heading fragment kept in a locator.
_LOCATOR_HEADING_CHARS = 40


class _ReadableText(HTMLParser):
    """Collects the text a person would see, block by block."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.segments: list[DocumentSegment] = []
        self._skip_depth = 0
        self._buffer: list[str] = []
        self._tag = "p"
        self._heading: str | None = None
        self._counter = 0
        self._order = 0

    # -- collection ------------------------------------------------------
    def _flush(self) -> None:
        text = "".join(self._buffer).strip()
        self._buffer = []
        if not text:
            return

        self._counter += 1
        locator = f"{self._tag}#{self._counter}"
        if self._heading:
            locator = f"{self._heading} > {locator}"

        kind = SegmentKind.HEADING if self._tag in HEADING_TAGS else SegmentKind.PARAGRAPH
        if self._tag in {"td", "th", "tr", "table", "caption"}:
            kind = SegmentKind.TABLE
        elif self._tag in {"li", "dd", "dt"}:
            kind = SegmentKind.LIST

        segment = make_segment(text, locator, kind=kind, order=self._order)
        if segment is not None:
            self.segments.append(segment)
            self._order += 1

        if self._tag in HEADING_TAGS:
            self._heading = text[:_LOCATOR_HEADING_CHARS].strip()

    # -- HTMLParser hooks ------------------------------------------------
    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in SKIPPED_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in BLOCK_TAGS:
            self._flush()
            self._tag = tag
        elif tag == "br":
            self._buffer.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIPPED_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag in BLOCK_TAGS:
            self._flush()

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag == "br" and not self._skip_depth:
            self._buffer.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self._buffer.append(data)

    def handle_comment(self, data: str) -> None:
        # Dropped without being read. Comments carry internal notes often enough to matter.
        return

    def close(self) -> None:  # type: ignore[override]
        super().close()
        self._flush()


class HtmlParser:
    """HTML. Implements :class:`core.interfaces.intake.DocumentParser`."""

    name = "html"
    supported_types = frozenset({FileType.HTML})

    def __init__(self, policy: IntakePolicy = DEFAULT_POLICY) -> None:
        self.policy = policy

    def parse(self, data: bytes, *, file_type: FileType) -> ExtractedDocument:
        if file_type is not FileType.HTML:
            raise IntakeError(IntakeErrorCode.UNSUPPORTED_FILE_TYPE, parser=self.name)

        text = decode_text(data)

        with parser_guard(self.name):
            extractor = _ReadableText()
            extractor.feed(text)
            extractor.close()
            segments = extractor.segments

        return ExtractedDocument(
            file_type=file_type,
            byte_size=len(data),
            segments=segments,
            page_count=None,
            detected_lang=None,
            parser_name=self.name,
        )
