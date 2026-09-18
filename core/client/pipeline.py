# -*- coding: utf-8 -*-
"""Criteria → organizations → fit → priority.

A sequence of pure functions with the providers injected, like the research pipeline. The order
holds because of what each stage accepts: fit assessment takes a
:class:`~core.client.models.VerifiedOrganization`, and the only way to obtain one is to have had
a name survive verification against the evidence.
"""
from __future__ import annotations

from typing import Iterable, Optional, Sequence

from core.client.discover import build_criteria, find_organizations
from core.client.fit import assess_fit, findings_for
from core.client.models import DiscoveryOutcome, VerifiedOrganization
from core.client.policy import DEFAULT_DISCOVERY_POLICY, ClientPromptSet, DiscoveryPolicy
from core.client.priority import decide_priority
from core.evidence import check_client_candidate
from core.models import (
    ClientCandidate,
    ClientStatus,
    FitCriterion,
    KeyIssue,
    MarketScope,
    Project,
    ResearchFinding,
    SourceMetadata,
    SourceOrigin,
    aggregate_finding_ids,
    aggregate_missing_evidence,
)
from core.research.models import Rejection, RejectionCode


def direct_source_ids(
    sources: Iterable[SourceMetadata],
    *,
    snippet_locator: str = "snippet",
) -> set[str]:
    """Sources for which the harness holds real document provenance.

    Everything except a search result, whose evidence is the few lines an engine chose to show.
    This set is what the P1 gate and the snippet downgrade both consult.
    """
    return {
        source.source_id
        for source in sources
        if source.source_origin is not SourceOrigin.SEARCH_RESULT
    }


def run_discovery(
    *,
    project: Project,
    candidates: Sequence,
    sources: Sequence[SourceMetadata],
    findings: Sequence[ResearchFinding],
    key_issues: Sequence[KeyIssue],
    llm,
    prompts: ClientPromptSet,
    capability: str,
    solution: str,
    policy: DiscoveryPolicy = DEFAULT_DISCOVERY_POLICY,
    market_scope: Optional[MarketScope] = None,
    country: Optional[str] = None,
    industry: Optional[str] = None,
) -> DiscoveryOutcome:
    """Find prospects the evidence supports, and band them by how well it supports them."""
    outcome = DiscoveryOutcome()
    sources_by_id = {source.source_id: source for source in sources}
    direct = direct_source_ids(sources, snippet_locator=policy.snippet_locator)
    scope = market_scope or (
        project.market_scope[0] if project.market_scope else MarketScope.DOMESTIC
    )
    lang = project.output_lang

    # -- what to look for ---------------------------------------------------
    criteria, records = build_criteria(
        findings,
        key_issues,
        llm=llm,
        prompts=prompts,
        project_id=project.project_id,
        capability=capability,
        solution=solution,
        output_lang=lang,
        policy=policy,
    )
    outcome.criteria = criteria
    outcome.transmissions.extend(records)

    # -- organizations the evidence names -----------------------------------
    organizations, hypotheses, rejections, records = find_organizations(
        candidates,
        llm=llm,
        prompts=prompts,
        sources_by_id=sources_by_id,
        criteria=criteria,
        output_lang=lang,
        policy=policy,
    )
    outcome.hypotheses.extend(hypotheses)
    outcome.rejections.extend(rejections)
    outcome.transmissions.extend(records)

    # -- assess and band ----------------------------------------------------
    for organization in organizations[: policy.max_organizations]:
        candidate = _build_candidate(
            organization,
            findings=findings,
            key_issues=key_issues,
            llm=llm,
            prompts=prompts,
            sources_by_id=sources_by_id,
            direct=direct,
            project=project,
            scope=scope,
            country=country,
            industry=industry,
            policy=policy,
            outcome=outcome,
        )
        if candidate is not None:
            outcome.candidates.append(candidate)

    return outcome


def _build_candidate(
    organization: VerifiedOrganization,
    *,
    findings: Sequence[ResearchFinding],
    key_issues: Sequence[KeyIssue],
    llm,
    prompts: ClientPromptSet,
    sources_by_id: dict[str, SourceMetadata],
    direct: set[str],
    project: Project,
    scope: MarketScope,
    country: Optional[str],
    industry: Optional[str],
    policy: DiscoveryPolicy,
    outcome: DiscoveryOutcome,
) -> Optional[ClientCandidate]:
    relevant = findings_for(
        FitCriterion.EVIDENCE_QUALITY, findings, limit=policy.max_findings_per_assessment
    )
    assessments, rationale, rejections, flags, records = assess_fit(
        organization,
        relevant,
        llm=llm,
        prompts=prompts,
        sources_by_id=sources_by_id,
        direct_source_ids=direct,
        output_lang=project.output_lang,
        policy=policy,
    )
    outcome.rejections.extend(rejections)
    outcome.review_flags.extend(flags)
    outcome.transmissions.extend(records)

    if not rationale:
        # Without it the record is a company name with eight ratings attached, which is the
        # industry-list outcome this phase exists to avoid. An over-long rationale arrives here
        # as an absent one, already reported under its own code — saying EMPTY_STATEMENT on top
        # of that would name the wrong fault.
        if not any(r.code == RejectionCode.RATIONALE_TOO_LONG for r in rejections):
            outcome.rejections.append(
                Rejection("assess_fit", RejectionCode.EMPTY_STATEMENT, _first(organization.source_ids))
            )
        return None

    candidate = ClientCandidate(
        project_id=project.project_id,
        client_name=organization.name,
        country=country or "",
        industry=industry or "",
        discovery_rationale=rationale,
        # Discovery and identity provenance only: where this organization was named.
        source_ids=list(organization.source_ids),
        market_scope=scope,
        # Derived, not authored: no prompt asks for these and nothing else writes them.
        finding_ids=aggregate_finding_ids(assessments),
        key_issue_ids=[issue.key_issue_id for issue in key_issues],
        fit=assessments,
        status=ClientStatus.SCREENED,
        lang=project.output_lang,
    )

    identity_verified = not policy.require_identity_for_p1 or candidate.identity is not None
    candidate.priority = decide_priority(
        candidate, direct_source_ids=direct, identity_verified=identity_verified
    )
    candidate.missing_evidence = aggregate_missing_evidence(candidate.fit)
    candidate.status = _status_for(candidate)

    violations = check_client_candidate(candidate)
    if violations:
        # The entity is rejected whole rather than stored with holes in it.
        outcome.rejections.append(
            Rejection(
                "build_candidate",
                RejectionCode.CANDIDATE_INVALID,
                _first(organization.source_ids),
            )
        )
        return None

    return candidate


def _first(source_ids: Sequence[str]) -> Optional[str]:
    """One source id, so a rejection is traceable.

    A list would be stringified into ``<omitted>`` by ``safe_reference`` and the diagnostic
    would say nothing at all.
    """
    return source_ids[0] if source_ids else None


def _status_for(candidate: ClientCandidate) -> ClientStatus:
    from core.models import SalesPriority

    if candidate.priority.band is SalesPriority.DEFERRED:
        return ClientStatus.DEFERRED
    if candidate.priority.band in (SalesPriority.P1, SalesPriority.P2, SalesPriority.P3):
        return ClientStatus.PRIORITIZED
    return ClientStatus.SCREENED


def persist(outcome: DiscoveryOutcome, storage) -> None:
    """Hand the candidates to storage. Criteria, hypotheses and mentions are never offered."""
    for candidate in outcome.candidates:
        storage.save_client(candidate)
