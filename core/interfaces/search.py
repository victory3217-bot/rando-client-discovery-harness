# -*- coding: utf-8 -*-
"""Search contract — how market research material reaches the harness.

The default adapter (``adapters/search/manual.py``) performs no search at all: it returns only
material a person has already supplied. That is the honest default for a tool whose findings
must be traceable, and it keeps the MVP usable in environments where outbound web access is
not allowed.

A web adapter arrives in Phase 3 and implements the same two-line interface.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

from core.models import MarketScope


@dataclass
class SearchResult:
    """One retrieved item, carrying enough provenance to become a finding's source."""

    title: str
    snippet: str
    url: Optional[str] = None
    published_date: Optional[str] = None
    country: Optional[str] = None
    market_scope: MarketScope = MarketScope.DOMESTIC
    #: Which adapter produced this, so mixed-provenance research stays auditable.
    provider: Optional[str] = None


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
