# -*- coding: utf-8 -*-
"""Null storage — the default, and the whole point of ephemeral mode.

Every write is discarded; every read comes back empty. The pipeline runs, the analysis is
returned to the person who uploaded the material, and nothing remains on the server.

This is not a degraded or stub adapter. It is the intended behaviour of the public build: see
``docs/privacy.md``. An organisation that wants records chooses a different adapter, and that
choice belongs to the organisation rather than to this core.

Saves still return the entity's own identifier, so a caller can keep working with stable ids
inside one request even though nothing is kept afterwards.
"""
from __future__ import annotations

from typing import Optional

from core.models import (
    ClientAnalysis,
    ClientCandidate,
    KeyIssue,
    PricingResult,
    Project,
    ProposalStrategy,
    ResearchFinding,
    SourceMetadata,
    SWOTIssue,
)


class NullStorage:
    """Discards everything. Implements :class:`core.interfaces.storage.StorageProvider`."""

    name = "null"

    # -- project -----------------------------------------------------------
    def save_project(self, project: Project) -> str:
        return project.project_id

    def get_project(self, project_id: str) -> Optional[Project]:
        return None

    # -- sources -----------------------------------------------------------
    def save_source_metadata(self, source: SourceMetadata) -> str:
        return source.source_id

    def get_source_metadata(self, project_id: str) -> list[SourceMetadata]:
        return []

    # -- engine 1 ----------------------------------------------------------
    def save_finding(self, finding: ResearchFinding) -> str:
        return finding.finding_id

    def get_findings(self, project_id: str) -> list[ResearchFinding]:
        return []

    def save_swot_issue(self, issue: SWOTIssue) -> str:
        return issue.issue_id

    def get_swot_issues(self, project_id: str) -> list[SWOTIssue]:
        return []

    def save_key_issue(self, issue: KeyIssue) -> str:
        return issue.key_issue_id

    def get_key_issues(self, project_id: str) -> list[KeyIssue]:
        return []

    # -- engine 2 ----------------------------------------------------------
    def save_client(self, client: ClientCandidate) -> str:
        return client.client_id

    def get_clients(self, project_id: str) -> list[ClientCandidate]:
        return []

    def save_client_analysis(self, analysis: ClientAnalysis) -> str:
        return analysis.analysis_id

    def get_client_analyses(self, project_id: str) -> list[ClientAnalysis]:
        return []

    def save_proposal_strategy(self, strategy: ProposalStrategy) -> str:
        return strategy.strategy_id

    def get_proposal_strategies(self, project_id: str) -> list[ProposalStrategy]:
        return []

    # -- pricing hand-off --------------------------------------------------
    def save_pricing_result(self, result: PricingResult) -> str:
        return result.pricing_result_id

    def get_pricing_results(self, project_id: str) -> list[PricingResult]:
        return []
