# -*- coding: utf-8 -*-
"""Transient objects for one deep-analysis run.

Nothing here is persisted and nothing gets a schema in ``schemas/``. The one entity this phase
produces is :class:`~core.models.ClientAnalysis`; everything below exists for the duration of
a run and then goes away.

:class:`PartnerProfile` is the piece worth noticing. It describes the *kind* of partner worth
looking for and has no field for a company, which is the same device
``DiscoveryHypothesis`` uses: a model cannot suggest an unverified organization if there is
nowhere to write one down.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.models import (
    AccessRoute,
    AnalysisDimension,
    InternationalDimension,
)


@dataclass
class ClientResearchCriteria:
    """What still needs finding out about one selected client.

    Transient. Turned into search queries by the caller's provider and thrown away; the
    findings it leads to are what persists.
    """

    client_id: str
    #: Free-text queries, one per thing worth looking up.
    queries: list[str] = field(default_factory=list)
    #: Which dimensions the queries are meant to settle, for reporting.
    target_dimensions: list[AnalysisDimension] = field(default_factory=list)
    country: Optional[str] = None
    industry: Optional[str] = None

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"<ClientResearchCriteria client={self.client_id} "
            f"queries={len(self.queries)} dimensions={len(self.target_dimensions)}>"
        )


@dataclass(repr=False)
class ClaimDraft:
    """One dimension's answer as the model returned it, before the rules run.

    Carries only what a model is allowed to decide. Evidence type, confidence and framework
    basis are absent by design: they are derived, and a field here would be an invitation to
    let the model fill it in.
    """

    dimension: AnalysisDimension
    statement: Optional[str] = None
    evidence_refs: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    organization_name: Optional[str] = None
    access_route: Optional[AccessRoute] = None

    def __repr__(self) -> str:
        """Dimension and counts. The statement can hold anything the evidence held."""
        return (
            f"<ClaimDraft {self.dimension.value} refs={len(self.evidence_refs)} "
            f"chars={len(self.statement or '')} named={self.organization_name is not None}>"
        )


@dataclass(repr=False)
class InternationalDraft:
    """The same, for an overseas-specific dimension."""

    dimension: InternationalDimension
    statement: Optional[str] = None
    evidence_refs: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        return (
            f"<InternationalDraft {self.dimension.value} refs={len(self.evidence_refs)} "
            f"chars={len(self.statement or '')}>"
        )


@dataclass
class PartnerProfile:
    """The kind of partner worth looking for, when the evidence names none.

    **There is no name field, and that is the point.** A model that has found no partner in the
    evidence will happily supply a plausible distributor for the region; leaving it nowhere to
    put one is more reliable than asking it not to. A real partner goes through
    ``PARTNER`` with its name verified against the passage that mentions it.
    """

    partner_type: str
    rationale: Optional[str] = None
    required_evidence: list[str] = field(default_factory=list)


@dataclass
class AnalysisOutcome:
    """Everything one deep-analysis run produced, including what it refused."""

    analyses: list = field(default_factory=list)
    partner_profiles: list[PartnerProfile] = field(default_factory=list)
    criteria: list[ClientResearchCriteria] = field(default_factory=list)
    #: Findings created by this run's own client-specific research, if any.
    findings: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    rejections: list = field(default_factory=list)
    review_flags: list = field(default_factory=list)
    #: One record per external call. Counts, never text.
    transmissions: list = field(default_factory=list)

    def summary(self) -> dict:
        """Counts only — safe to log, and names nobody."""
        return {
            "analyses": len(self.analyses),
            "claims": sum(len(a.claims) for a in self.analyses),
            "international_claims": sum(len(a.international_claims) for a in self.analyses),
            "new_findings": len(self.findings),
            "partner_profiles": len(self.partner_profiles),
            "rejections": len(self.rejections),
            "review_flags": len(self.review_flags),
            "transmissions": len(self.transmissions),
        }
