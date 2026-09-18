# -*- coding: utf-8 -*-
"""Turning a search result into evidence the pipeline already knows how to handle.

A retrieved page and an uploaded file are different things, and this does not pretend
otherwise: the resulting :class:`~core.models.SourceMetadata` carries ``title``, ``publisher``,
``url`` and ``retrieved_at``, and leaves ``file_type``, ``file_size`` and ``page_count`` null.
Inventing a file type for a web page would put fiction into the record the whole evidence trail
hangs from.

What *is* unified is the downstream shape. Both origins produce a ``SourceMetadata`` plus
:class:`~core.intake.models.EvidenceCandidate` objects, so the research pipeline has one input
type and every finding gets the same provenance treatment regardless of where its evidence came
from.

Retrieval and interpretation stay apart: this module copies what the adapter reported and adds
nothing. The reading of it is a ``ResearchFinding``, produced later by a different stage.
"""
from __future__ import annotations

from typing import Iterable, Optional

from core.intake.models import EvidenceCandidate, SegmentKind
from core.interfaces.search import SearchResult
from core.research.policy import SNIPPET_LOCATOR
from core.models import (
    ProcessingStatus,
    SourceCategory,
    SourceMetadata,
    SourceOrigin,
    new_id,
)

#: Cap on a stored title, matching the schema.
MAX_TITLE_CHARS = 300


def source_from_search_result(
    result: SearchResult,
    *,
    project_id: str,
    source_category: SourceCategory = SourceCategory.EXTERNAL_BUSINESS_DATA,
    retrieved_at: Optional[str] = None,
    source_id: Optional[str] = None,
) -> SourceMetadata:
    """Build the source record for one retrieved item.

    ``retrieved_at`` falls back to the adapter's value and must end up set — a search result
    without a retrieval time cannot be judged for recency, and
    ``core.evidence.check_source_metadata`` rejects it.
    """
    title = (result.title or "").strip()[:MAX_TITLE_CHARS]
    return SourceMetadata(
        project_id=project_id,
        source_origin=SourceOrigin.SEARCH_RESULT,
        source_category=source_category,
        source_id=source_id or new_id("src"),
        display_label=None,
        title=title or None,
        publisher=(result.publisher or None),
        url=(result.url or None),
        retrieved_at=retrieved_at or result.retrieved_at,
        source_date=result.published_date,
        processing_status=ProcessingStatus.EXTRACTED,
    )


def candidate_from_search_result(
    result: SearchResult,
    *,
    project_id: str,
    source_id: str,
    order: int = 0,
) -> EvidenceCandidate:
    """The snippet, as a citable passage.

    The locator is ``snippet`` rather than a page or a cell: that is genuinely all the position
    information a search result has, and saying so is better than manufacturing precision. It
    also caps confidence — nothing here has read the page the snippet was taken from.
    """
    return EvidenceCandidate(
        project_id=project_id,
        source_id=source_id,
        text=result.snippet.strip(),
        locator=SNIPPET_LOCATOR,
        kind=SegmentKind.PARAGRAPH,
        order=order,
    )


def ingest_search_results(
    results: Iterable[SearchResult],
    *,
    project_id: str,
    source_category: SourceCategory = SourceCategory.EXTERNAL_BUSINESS_DATA,
    retrieved_at: Optional[str] = None,
) -> tuple[list[SourceMetadata], list[EvidenceCandidate]]:
    """Convert a batch of results into sources and candidates, in order.

    Results with an empty snippet are dropped: there is nothing to cite, and a source record
    with no passage behind it would be a dangling reference.
    """
    sources: list[SourceMetadata] = []
    candidates: list[EvidenceCandidate] = []

    for order, result in enumerate(results):
        if not (result.snippet or "").strip():
            continue
        source = source_from_search_result(
            result,
            project_id=project_id,
            source_category=source_category,
            retrieved_at=retrieved_at,
        )
        sources.append(source)
        candidates.append(
            candidate_from_search_result(
                result, project_id=project_id, source_id=source.source_id, order=order
            )
        )

    return sources, candidates
