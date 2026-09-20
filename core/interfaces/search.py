# -*- coding: utf-8 -*-
"""Search contract — how market research material reaches the harness.

The default adapter (``adapters/search/manual.py``) performs no search at all: it returns only
material a person has already supplied. That is the honest default for a tool whose findings
must be traceable, and it keeps the MVP usable in environments where outbound web access is
not allowed.

A production adapter that reaches an external index implements this same two-line
interface and lives entirely under ``adapters/search/`` — the core gains no notion of a
vendor, an endpoint or a credential when one is wired in.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

from core.models import Confidence, MarketScope


@dataclass
class SearchResult:
    """One retrieved item, carrying enough provenance to become a finding's source.

    This is *retrieval*, not interpretation. What the item says is the snippet; what it means
    is a :class:`~core.models.ResearchFinding`, produced later and separately. Keeping the two
    apart is what lets a reader check a conclusion against the thing it came from.

    ``evidence_quality`` defaults to ``UNKNOWN`` and stays there unless something establishes
    otherwise. A search adapter knows where it fetched from, not whether the source is any good.
    """

    title: str
    snippet: str
    url: Optional[str] = None
    #: Who published it. Absent for an anonymous page, and its absence limits confidence.
    publisher: Optional[str] = None
    published_date: Optional[str] = None
    #: When this harness read it. Distinct from published_date: a five-year-old page read today
    #: is recent retrieval of stale material, and the two facts answer different questions.
    retrieved_at: Optional[str] = None
    country: Optional[str] = None
    market_scope: MarketScope = MarketScope.DOMESTIC
    #: Which adapter produced this, so mixed-provenance research stays auditable.
    provider: Optional[str] = None
    evidence_quality: Confidence = Confidence.UNKNOWN


@runtime_checkable
class SearchProvider(Protocol):
    """Retrieval of external market material."""

    #: Short adapter identifier, safe to log (e.g. ``"manual"``, ``"web"``).
    name: str

    def search(
        self,
        query: str,
        *,
        scope: MarketScope = MarketScope.DOMESTIC,
        country: Optional[str] = None,
        limit: int = 10,
    ) -> list[SearchResult]: ...
