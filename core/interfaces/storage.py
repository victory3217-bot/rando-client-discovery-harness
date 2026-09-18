# -*- coding: utf-8 -*-
"""Storage contract.

Deliberately narrow. There is no query language here, no transaction, no pagination and no
filter object — the moment any of those appear in this file the core stops being database
agnostic, because every adapter then has to emulate whichever database the first one was
written against.

An adapter is free to be a no-op. ``adapters/storage/null.py`` discards every write and returns
nothing, which is exactly what the public web application wants in ephemeral mode: the pipeline
runs, the analysis is returned to the person who uploaded the documents, and nothing is kept.

Because this is a :class:`typing.Protocol`, an organisation writing its own adapter does not
import or subclass anything from this repository. Matching the method signatures is enough.
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

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


@runtime_checkable
class StorageProvider(Protocol):
    """Persistence for the eight core entities.

    Every ``save_*`` returns the identifier of the stored record so that a caller can keep
    working against a stable id even when the adapter keeps nothing (a null adapter returns the
    id it was handed). Every ``get_*`` returns an empty result rather than raising when nothing
    is found — absence is a normal state in ephemeral mode, not an error.
    """

    #: Short adapter identifier, safe to log (e.g. ``"null"``, ``"memory"``, ``"sqlite"``).
    name: str

    # -- project -----------------------------------------------------------
    def save_project(self, project: Project) -> str: ...

    def get_project(self, project_id: str) -> Optional[Project]: ...

    # -- sources -----------------------------------------------------------
    def save_source_metadata(self, source: SourceMetadata) -> str: ...

    def get_source_metadata(self, project_id: str) -> list[SourceMetadata]: ...

    # -- engine 1 ----------------------------------------------------------
    def save_finding(self, finding: ResearchFinding) -> str: ...

    def get_findings(self, project_id: str) -> list[ResearchFinding]: ...

    def save_swot_issue(self, issue: SWOTIssue) -> str: ...

    def get_swot_issues(self, project_id: str) -> list[SWOTIssue]: ...

    # -- engine 2 ----------------------------------------------------------
    def save_client(self, client: ClientCandidate) -> str: ...

    def get_clients(self, project_id: str) -> list[ClientCandidate]: ...

    def save_client_analysis(self, analysis: ClientAnalysis) -> str: ...

    def get_client_analyses(self, project_id: str) -> list[ClientAnalysis]: ...

    def save_proposal_strategy(self, strategy: ProposalStrategy) -> str: ...

    def get_proposal_strategies(self, project_id: str) -> list[ProposalStrategy]: ...

    # -- pricing hand-off --------------------------------------------------
    def save_pricing_result(self, result: PricingResult) -> str: ...

    def get_pricing_results(self, project_id: str) -> list[PricingResult]: ...
