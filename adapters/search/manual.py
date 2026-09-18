# -*- coding: utf-8 -*-
"""Manual search — returns only material a person already supplied.

No network access, no external index. This is the honest default for a tool whose findings must
be traceable: everything it can return has a known provenance because someone put it there.

It also keeps the MVP usable where outbound web access is not allowed, which is common in the
environments this harness is meant to be embedded in. A real web adapter arrives in Phase 3 and
implements the same two-line interface.
"""
from __future__ import annotations

from typing import Iterable, Optional

from core.interfaces.search import SearchResult
from core.models import MarketScope


class ManualSearch:
    """Filters a supplied collection. Implements ``SearchProvider``."""

    name = "manual"

    def __init__(self, items: Optional[Iterable[SearchResult]] = None) -> None:
        self._items: list[SearchResult] = []
        for item in items or []:
            self.add(item)

    def add(self, item: SearchResult) -> None:
        """Register one piece of material the operator has provided."""
        if item.provider is None:
            item.provider = self.name
        self._items.append(item)

    def search(
        self,
        query: str,
        *,
        scope: MarketScope = MarketScope.DOMESTIC,
        country: Optional[str] = None,
        limit: int = 10,
    ) -> list[SearchResult]:
        """Case-insensitive substring match over title and snippet.

        Deliberately not a ranking algorithm — relevance judgement belongs to the person
        reading the results, and a scored order here would imply a confidence this adapter
        cannot have.
        """
        needle = query.strip().lower()
        matches: list[SearchResult] = []

        for item in self._items:
            if item.market_scope != scope:
                continue
            if country and item.country and item.country != country:
                continue
            if needle and needle not in f"{item.title}\n{item.snippet}".lower():
                continue
            matches.append(item)
            if len(matches) >= limit:
                break

        return matches
