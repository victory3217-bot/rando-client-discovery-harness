# -*- coding: utf-8 -*-
"""Transport objects for intake. Not entities.

Everything defined here carries document text, and document text is never persisted. These
objects live for the duration of one request: a parser produces them, the diagnosis stage
consumes them, and then they go out of scope.

That is why they are **not** in ``core/models.py``, have **no** JSON Schema in ``schemas/``, and
have **no** ``save_*`` method on ``StorageProvider``. ``schemas/`` is the contract for what gets
stored, and publishing a schema for something the harness forbids storing would say the
opposite of what is meant.

Every class here defines its own ``__repr__`` that omits the text. A debugger, an error tracker
or a ``%r`` in a log line will print a shape, not a paragraph of somebody's strategy document.
That is a useful defence but not a complete one — see ``docs/privacy.md`` for what still has to
be switched off in production tooling.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from core.models import FileType, SourceMetadata, new_id


class SegmentKind(str, Enum):
    """What kind of block a segment came from.

    Kept here rather than in ``core/models.py`` on purpose: this is internal vocabulary, and
    values in ``core/models.py`` carry an obligation to have a Korean and English label in
    ``locales/``. If a dashboard ever shows segment kinds to a person, the enum moves there and
    gains its labels then.
    """

    PARAGRAPH = "PARAGRAPH"
    HEADING = "HEADING"
    TABLE = "TABLE"
    LIST = "LIST"
    CELL_RANGE = "CELL_RANGE"
    SLIDE_NOTE = "SLIDE_NOTE"


@dataclass(repr=False)
class DocumentSegment:
    """One addressable block of text from a document.

    ``locator`` is what makes the block citable — ``p.7``, ``Sheet1!A1:D18``, ``slide 4 notes``.
    It travels all the way to ``ResearchFinding.page_or_section``, which is how a conclusion
    stays traceable to the page it came from.
    """

    text: str
    locator: str
    kind: SegmentKind = SegmentKind.PARAGRAPH
    order: int = 0

    def __repr__(self) -> str:
        return (
            f"<DocumentSegment {self.kind.value} locator={self.locator!r} "
            f"chars={len(self.text)}>"
        )


@dataclass(repr=False)
class ExtractedDocument:
    """What a parser produces: segments plus the facts needed to build SourceMetadata.

    ``detected_lang`` stays ``None`` unless a parser has a real basis for a value. This harness
    ships no language detection and does not guess from character ranges — a wrong language tag
    is worse than an absent one, because downstream prompts act on it.
    """

    file_type: FileType
    byte_size: int
    segments: list[DocumentSegment] = field(default_factory=list)
    page_count: Optional[int] = None
    detected_lang: Optional[str] = None
    parser_name: Optional[str] = None

    @property
    def char_count(self) -> int:
        return sum(len(segment.text) for segment in self.segments)

    def __repr__(self) -> str:
        return (
            f"<ExtractedDocument {self.file_type.value} parser={self.parser_name!r} "
            f"segments={len(self.segments)} chars={self.char_count} "
            f"pages={self.page_count} bytes={self.byte_size}>"
        )


@dataclass(repr=False)
class EvidenceCandidate:
    """A passage that may become evidence, with the provenance to prove where it came from.

    Phase 2 stops here. It does **not** decide whether a passage is a fact, an inference or an
    assumption — that judgement needs a Master Note question applied to it, which is Phase 3.
    What Phase 2 guarantees is that the judgement, when it happens, cannot lose the source.
    """

    project_id: str
    source_id: str
    text: str
    locator: str
    kind: SegmentKind = SegmentKind.PARAGRAPH
    order: int = 0
    candidate_id: str = field(default_factory=lambda: new_id("evc"))

    @property
    def char_count(self) -> int:
        return len(self.text)

    def __repr__(self) -> str:
        return (
            f"<EvidenceCandidate {self.candidate_id} source={self.source_id} "
            f"locator={self.locator!r} kind={self.kind.value} chars={self.char_count}>"
        )


@dataclass(repr=False)
class IntakeResult:
    """The outcome of ingesting one document.

    ``source`` is the only part that may be persisted. ``candidates`` are transient.
    """

    source: SourceMetadata
    candidates: list[EvidenceCandidate] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.source.error_code is None

    def __repr__(self) -> str:
        return (
            f"<IntakeResult source={self.source.source_id} "
            f"status={self.source.processing_status.value} "
            f"error={self.source.error_code!r} candidates={len(self.candidates)}>"
        )
