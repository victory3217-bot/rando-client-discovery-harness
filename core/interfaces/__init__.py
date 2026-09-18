# -*- coding: utf-8 -*-
"""The contracts the core owns.

Four providers are assembled into a harness (Storage, Knowledge, LLM, Search).
:class:`DocumentParser` is a fifth contract but deliberately *not* a provider: intake is
request-scoped, so a parser is chosen per file rather than wired into a harness.

``PricingProvider`` (Phase 7) and ``ReportProvider`` (Phase 9) are specified in
ARCHITECTURE.md section 3 and become modules here when they are implemented — an empty protocol
nobody calls is not worth carrying.

Authentication is intentionally absent: it belongs to the application layer, because a core that
knows who is calling it is no longer embeddable.
"""
from core.interfaces.intake import DocumentParser
from core.interfaces.knowledge import Framework, FrameworkDimension, KnowledgeProvider
from core.interfaces.llm import LLMProvider
from core.interfaces.search import SearchProvider, SearchResult
from core.interfaces.storage import StorageProvider

__all__ = [
    "DocumentParser",
    "Framework",
    "FrameworkDimension",
    "KnowledgeProvider",
    "LLMProvider",
    "SearchProvider",
    "SearchResult",
    "StorageProvider",
]
