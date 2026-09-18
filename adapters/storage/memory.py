# -*- coding: utf-8 -*-
"""In-process storage — still ephemeral, but able to connect one stage to the next.

Everything lives in Python dictionaries and disappears when the process ends. That makes it the
right adapter for a single analysis session, for ``examples/run_example.py``, and for tests that
need stage two to see what stage one produced.

It is not a persistence adapter. Nothing here survives a restart, and nothing is written to
disk — which is exactly why it is safe to use in the public build. A real database arrives in
Phase 8 as ``adapters/storage/sqlite.py``.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from core.models import (
    ClientAnalysis,
    ClientCandidate,
    PricingResult,
    Project,
    ProposalStrategy,
    ResearchFinding,
    SourceMetadata,
    SWOTIssue,
)


class MemoryStorage:
    """Dictionary-backed storage. Implements ``StorageProvider``."""

    name = "memory"

    def __init__(self) -> None:
        self._projects: dict[str, Project] = {}
        self._sources: dict[str, list[SourceMetadata]] = defaultdict(list)
        self._findings: dict[str, list[ResearchFinding]] = defaultdict(list)
        self._swot: dict[str, list[SWOTIssue]] = defaultdict(list)
        self._clients: dict[str, list[ClientCandidate]] = defaultdict(list)
        self._analyses: dict[str, list[ClientAnalysis]] = defaultdict(list)
        self._strategies: dict[str, list[ProposalStrategy]] = defaultdict(list)
        self._pricing: dict[str, list[PricingResult]] = defaultdict(list)

    # -- project -----------------------------------------------------------
    def save_project(self, project: Project) -> str:
        self._projects[project.project_id] = project
        return project.project_id

    def get_project(self, project_id: str) -> Optional[Project]:
        return self._projects.get(project_id)

    # -- sources -----------------------------------------------------------
    def save_source_metadata(self, source: SourceMetadata) -> str:
        self._sources[source.project_id].append(source)
        return source.source_id

    def get_source_metadata(self, project_id: str) -> list[SourceMetadata]:
        return list(self._sources[project_id])

    # -- engine 1 ----------------------------------------------------------
    def save_finding(self, finding: ResearchFinding) -> str:
        self._findings[finding.project_id].append(finding)
        return finding.finding_id

    def get_findings(self, project_id: str) -> list[ResearchFinding]:
        return list(self._findings[project_id])

    def save_swot_issue(self, issue: SWOTIssue) -> str:
        self._swot[issue.project_id].append(issue)
        return issue.issue_id

    def get_swot_issues(self, project_id: str) -> list[SWOTIssue]:
        return list(self._swot[project_id])

    # -- engine 2 ----------------------------------------------------------
    def save_client(self, client: ClientCandidate) -> str:
        self._clients[client.project_id].append(client)
        return client.client_id

    def get_clients(self, project_id: str) -> list[ClientCandidate]:
        return list(self._clients[project_id])

    def save_client_analysis(self, analysis: ClientAnalysis) -> str:
        self._analyses[analysis.project_id].append(analysis)
        return analysis.analysis_id

    def get_client_analyses(self, project_id: str) -> list[ClientAnalysis]:
        return list(self._analyses[project_id])

    def save_proposal_strategy(self, strategy: ProposalStrategy) -> str:
        self._strategies[strategy.project_id].append(strategy)
        return strategy.strategy_id

    def get_proposal_strategies(self, project_id: str) -> list[ProposalStrategy]:
        return list(self._strategies[project_id])

    # -- pricing hand-off --------------------------------------------------
    def save_pricing_result(self, result: PricingResult) -> str:
        self._pricing[result.project_id].append(result)
        return result.pricing_result_id

    def get_pricing_results(self, project_id: str) -> list[PricingResult]:
        return list(self._pricing[project_id])

    # -- lifecycle ---------------------------------------------------------
    def clear(self) -> None:
        """Drop everything.

        An application in ephemeral mode calls this when a session ends, so that nothing lingers
        in a long-lived process between requests.
        """
        self._projects.clear()
        for bucket in (
            self._sources,
            self._findings,
            self._swot,
            self._clients,
            self._analyses,
            self._strategies,
            self._pricing,
        ):
            bucket.clear()
