# -*- coding: utf-8 -*-
"""Transient objects for client discovery.

Nothing here is persisted and nothing gets a schema in ``schemas/``. The one entity this phase
produces is :class:`~core.models.ClientCandidate`; everything below is scaffolding that exists
for the duration of one discovery run.

``OrganizationMention`` matters most. It carries a verbatim span cut out of a document, which
is why it is transient, why it defines a redacting ``__repr__``, and why nothing copies its span
into the candidate it becomes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# AccessRoute moved to core.models when core/analysis/ began using it too. Re-exported
# here so that `from core.client.models import AccessRoute` keeps working.
from core.models import AccessRoute, FitCriterion, FitLevel, PurchaseSignal

__all__ = [
    "AccessRoute", "PurchaseSignal", "ClientDiscoveryCriteria", "OrganizationMention",
    "VerifiedOrganization", "DiscoveryHypothesis", "FitDraft", "DiscoveryOutcome",
]


@dataclass
class ClientDiscoveryCriteria:
    """What kind of organization to look for, before looking for any.

    Searching for companies first and justifying them afterwards is how an industry list gets
    mistaken for a discovery result. This is the specification that comes first.

    Transient: it is derived entirely from findings and key issues, nothing reads it back, and a
    persisted record with no reader is a guess about a future requirement. If a dashboard ever
    needs to show what was searched for, it becomes an entity then.
    """

    project_id: str

    target_country: Optional[str] = None
    target_region: Optional[str] = None
    target_industry: Optional[str] = None

    relevant_problem: Optional[str] = None
    problem_severity_signal: Optional[str] = None

    required_buyer_type: Optional[str] = None
    possible_decision_maker: Optional[str] = None

    our_capability: Optional[str] = None
    our_solution: Optional[str] = None
    required_solution_fit: Optional[str] = None

    purchase_signal: list[PurchaseSignal] = field(default_factory=list)
    budget_signal: Optional[str] = None
    procurement_signal: Optional[str] = None

    access_signal: list[AccessRoute] = field(default_factory=list)
    channel_signal: Optional[str] = None
    partner_signal: Optional[str] = None

    competitive_condition: Optional[str] = None
    exclusion_condition: list[str] = field(default_factory=list)
    required_evidence: list[str] = field(default_factory=list)

    finding_ids: list[str] = field(default_factory=list)
    key_issue_ids: list[str] = field(default_factory=list)
    mn_basis: list[str] = field(default_factory=list)


@dataclass(repr=False)
class OrganizationMention:
    """An organization name the model reported, before anyone has checked it.

    A mention is a claim, not a fact. It becomes a :class:`VerifiedOrganization` only once the
    pipeline has found the name in the passage that was cited.
    """

    name: str
    evidence_ref: str
    source_id: Optional[str] = None
    locator: Optional[str] = None
    #: The span the name was found in. Never persisted, never logged.
    verbatim: Optional[str] = None

    def __repr__(self) -> str:
        return (
            f"<OrganizationMention ref={self.evidence_ref} source={self.source_id} "
            f"chars={len(self.name)}>"
        )


@dataclass(repr=False)
class VerifiedOrganization:
    """A name that was found, literally, in the evidence that was cited for it.

    ``source_ids`` here becomes ``ClientCandidate.source_ids`` — discovery and identity
    provenance, not the evidence for any particular judgement.
    """

    name: str
    source_ids: list[str] = field(default_factory=list)
    locators: list[str] = field(default_factory=list)
    finding_ids: list[str] = field(default_factory=list)
    #: True when every source naming this organization is a search snippet.
    snippet_only: bool = True

    def __repr__(self) -> str:
        return (
            f"<VerifiedOrganization sources={len(self.source_ids)} "
            f"snippet_only={self.snippet_only}>"
        )


@dataclass
class DiscoveryHypothesis:
    """A *type* of organization worth looking for, never a particular one.

    There is no name field, and that is the design. A hypothesis says "regional public water
    utilities with a stated replacement programme"; naming a company that no evidence mentions
    is precisely the failure this phase exists to prevent, so there is nowhere to put one.

    Transient, and it cannot be promoted: a named client only ever arrives through
    OrganizationMention → VerifiedOrganization.
    """

    organization_profile: str
    rationale: Optional[str] = None
    required_evidence: list[str] = field(default_factory=list)
    key_issue_ids: list[str] = field(default_factory=list)


@dataclass
class FitDraft:
    """What the model returned for one criterion, before the pipeline resolves references."""

    criterion: FitCriterion
    level: FitLevel
    reason: Optional[str] = None
    evidence_refs: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    signal_type: Optional[PurchaseSignal] = None
    access_route: Optional[AccessRoute] = None


@dataclass
class DiscoveryOutcome:
    """Everything one discovery run produced, including what it refused."""

    criteria: Optional[ClientDiscoveryCriteria] = None
    candidates: list = field(default_factory=list)
    hypotheses: list[DiscoveryHypothesis] = field(default_factory=list)
    rejections: list = field(default_factory=list)
    review_flags: list = field(default_factory=list)
    transmissions: list = field(default_factory=list)

    def summary(self) -> dict:
        """Counts only — safe to log. No client names."""
        from core.models import SalesPriority

        bands = {band.value: 0 for band in SalesPriority}
        for candidate in self.candidates:
            bands[candidate.priority.band.value] += 1
        return {
            "candidates": len(self.candidates),
            "by_band": bands,
            "hypotheses": len(self.hypotheses),
            "rejections": len(self.rejections),
            "review_flags": len(self.review_flags),
            "transmissions": len(self.transmissions),
        }
