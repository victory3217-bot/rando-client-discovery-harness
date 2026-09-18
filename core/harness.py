# -*- coding: utf-8 -*-
"""The assembly point.

:func:`create_harness` is the one place an embedding system has to touch. Swap a storage,
knowledge, llm or search adapter here and nothing else in this repository changes — that is the
whole of the integration surface, for a reference app and for an organisation's internal system
alike.

All four providers are required rather than defaulted, because a default would mean the core
importing an adapter, and that is the dependency direction this architecture exists to prevent.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.interfaces.knowledge import Framework, KnowledgeProvider
from core.interfaces.llm import LLMProvider
from core.interfaces.search import SearchProvider
from core.interfaces.storage import StorageProvider
from core.models import MarketScope, Project, StorageMode

#: Frameworks used for company-level research and diagnosis (ENGINE 1).
RESEARCH_FRAMEWORKS = ("MN02", "MN03", "MN04", "MN05", "MN06", "MN07")

#: Frameworks used for per-client deep analysis (ENGINE 2).
#:
#: MN02 and MN07 are deliberately absent: they diagnose the company, not the client, and
#: repeating them per client produces volume rather than insight (HARNESS.md section 5).
CLIENT_ANALYSIS_FRAMEWORKS = ("MN03", "MN04", "MN05", "MN06")


@dataclass(frozen=True)
class Harness:
    """A configured harness: four providers and the operations that need all of them."""

    storage: StorageProvider
    knowledge: KnowledgeProvider
    llm: LLMProvider
    search: SearchProvider

    # -- project -----------------------------------------------------------
    def create_project(
        self,
        company_name: str,
        *,
        market_scope: Optional[list[MarketScope]] = None,
        target_countries: Optional[list[str]] = None,
        target_industries: Optional[list[str]] = None,
        ui_lang: str = "ko",
        output_lang: str = "ko",
        storage_mode: StorageMode = StorageMode.EPHEMERAL,
    ) -> Project:
        """Create a project and hand it to the configured storage adapter.

        With the null adapter the save is a no-op and the returned project simply lives for the
        duration of the request — which is the intended behaviour of the public build, not a
        degraded mode.
        """
        project = Project(
            company_name=company_name,
            market_scope=market_scope or [MarketScope.DOMESTIC],
            target_countries=target_countries or [],
            target_industries=target_industries or [],
            ui_lang=ui_lang,
            output_lang=output_lang,
            storage_mode=storage_mode,
        )
        self.storage.save_project(project)
        return project

    # -- frameworks --------------------------------------------------------
    def research_frameworks(self) -> list[Framework]:
        """The frameworks ENGINE 1 works through, in order."""
        return [self.knowledge.get_framework(fid) for fid in RESEARCH_FRAMEWORKS]

    def client_analysis_frameworks(self) -> list[Framework]:
        """The frameworks ENGINE 2 works through for one client, in order."""
        return [self.knowledge.get_framework(fid) for fid in CLIENT_ANALYSIS_FRAMEWORKS]

    # -- diagnostics -------------------------------------------------------
    def describe(self) -> dict:
        """Which adapters are wired in, as data.

        Returns rather than logs, so the caller decides whether this ends up in a log line.
        Adapter names are non-sensitive by contract.
        """
        return {
            "storage": getattr(self.storage, "name", "unknown"),
            "knowledge": getattr(self.knowledge, "name", "unknown"),
            "llm": getattr(self.llm, "name", "unknown"),
            "search": getattr(self.search, "name", "unknown"),
        }


def create_harness(
    *,
    storage: StorageProvider,
    knowledge: KnowledgeProvider,
    llm: LLMProvider,
    search: SearchProvider,
) -> Harness:
    """Assemble a harness from four adapters."""
    return Harness(storage=storage, knowledge=knowledge, llm=llm, search=search)
