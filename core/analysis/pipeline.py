# -*- coding: utf-8 -*-
"""Selected clients → claims → one ClientAnalysis each.

The entry point takes ``client_ids`` as a required keyword argument with no default. That is
the whole of the human-selection design, and it is deliberately unglamorous: there is no way
to call this function without having said which clients to analyse, and no code path that
picks them.

Nothing here reads a priority band, sorts by one, or writes one. The band belongs to
:class:`~core.models.ClientCandidate` and to Phase 4; a deep analysis that quietly reordered
the pipeline behind a reader's back would be the least visible way to lose Human Decision
First.
"""
from __future__ import annotations

from typing import Iterable, Optional, Sequence

from core.analysis.claims import (
    STAGE,
    AnalysisRejectionCode,
    apply_cross_dimension_rules,
    bounded,
    resolve_claim,
    resolve_international,
    source_ids_for,
)
from core.analysis.dimensions import (
    FRAMEWORK_GROUPS,
    INTERNATIONAL_FRAMEWORK,
    NAMED_ORGANIZATION_DIMENSIONS,
    ROUTE_DIMENSIONS,
    dimensions_for,
)
from core.analysis.models import (
    AnalysisOutcome,
    ClaimDraft,
    InternationalDraft,
    PartnerProfile,
)
from core.analysis.output_schemas import INTERNATIONAL_CLAIMS, claim_batch_schema
from core.analysis.policy import DEFAULT_ANALYSIS_POLICY, AnalysisPolicy, AnalysisPromptSet
from core.analysis.research import build_client_criteria, research_client
from core.evidence import check_client_analysis
from core.models import (
    AccessRoute,
    AnalysisClaim,
    AnalysisDimension,
    ClientAnalysis,
    ClientCandidate,
    InternationalDimension,
    MarketScope,
    Project,
    ResearchFinding,
    SourceMetadata,
    SourceOrigin,
    aggregate_finding_ids,
    aggregate_missing_evidence,
)
from core.research.models import Rejection
from core.transmission import send


def direct_source_ids(sources: Iterable[SourceMetadata]) -> set[str]:
    """Sources for which the harness holds real document provenance."""
    return {
        source.source_id
        for source in sources
        if source.source_origin is not SourceOrigin.SEARCH_RESULT
    }


def run_client_analysis(
    *,
    project: Project,
    client_ids: Sequence[str],
    candidates: Sequence[ClientCandidate],
    findings: Sequence[ResearchFinding],
    sources: Sequence[SourceMetadata],
    our_solution: str,
    capability: str,
    llm,
    prompts: AnalysisPromptSet,
    knowledge=None,
    research_prompts=None,
    search=None,
    policy: AnalysisPolicy = DEFAULT_ANALYSIS_POLICY,
    market_scope: Optional[MarketScope] = None,
    today: Optional[str] = None,
) -> AnalysisOutcome:
    """Analyse exactly the clients that were asked for.

    ``client_ids`` has no default and is never inferred. An id that is not among ``candidates``
    is refused rather than skipped, and more ids than the policy allows refuses the whole
    request — taking the first few would be this function choosing which clients matter.
    """
    outcome = AnalysisOutcome()

    if len(client_ids) > policy.max_clients_per_run:
        outcome.rejections.append(
            Rejection(STAGE, AnalysisRejectionCode.TOO_MANY_CLIENTS, str(len(client_ids)))
        )
        return outcome

    by_id = {candidate.client_id: candidate for candidate in candidates}
    scope = market_scope or (
        project.market_scope[0] if project.market_scope else MarketScope.DOMESTIC
    )
    lang = project.output_lang

    for client_id in client_ids:
        candidate = by_id.get(client_id)
        if candidate is None:
            outcome.rejections.append(
                Rejection(STAGE, AnalysisRejectionCode.UNKNOWN_CLIENT_ID, client_id)
            )
            continue
        _analyse_one(
            candidate,
            findings=findings,
            sources=sources,
            our_solution=our_solution,
            capability=capability,
            llm=llm,
            prompts=prompts,
            knowledge=knowledge,
            research_prompts=research_prompts,
            search=search,
            project=project,
            scope=scope,
            lang=lang,
            policy=policy,
            today=today,
            outcome=outcome,
        )

    return outcome


def _analyse_one(
    candidate: ClientCandidate,
    *,
    findings: Sequence[ResearchFinding],
    sources: Sequence[SourceMetadata],
    our_solution: str,
    capability: str,
    llm,
    prompts: AnalysisPromptSet,
    knowledge,
    research_prompts,
    search,
    project: Project,
    scope: MarketScope,
    lang: str,
    policy: AnalysisPolicy,
    today: Optional[str],
    outcome: AnalysisOutcome,
) -> None:
    all_findings = list(findings)
    all_sources = list(sources)

    # -- optional client-specific research ---------------------------------
    if search is not None and knowledge is not None and research_prompts is not None:
        criteria, records = build_client_criteria(
            candidate,
            all_findings,
            llm=llm,
            prompts=prompts,
            capability=capability,
            our_solution=our_solution,
            output_lang=lang,
            policy=policy,
        )
        outcome.criteria.append(criteria)
        outcome.transmissions.extend(records)

        new_sources, new_findings, rejected, records = research_client(
            criteria,
            search=search,
            knowledge=knowledge,
            llm=llm,
            prompts=research_prompts,
            project_id=project.project_id,
            market_scope=scope,
            country=candidate.country or None,
            output_lang=lang,
            policy=policy,
            today=today,
        )
        all_sources.extend(new_sources)
        all_findings.extend(new_findings)
        outcome.sources.extend(new_sources)
        outcome.findings.extend(new_findings)
        outcome.rejections.extend(rejected)
        outcome.transmissions.extend(records)

    direct = direct_source_ids(all_sources)
    findings_by_id = {f.finding_id: f for f in all_findings}

    # -- one framework group at a time -------------------------------------
    claims: dict[AnalysisDimension, AnalysisClaim] = {}
    for framework_id in FRAMEWORK_GROUPS:
        group_claims = _claims_for_group(
            candidate,
            framework_id,
            all_findings,
            our_solution=our_solution,
            llm=llm,
            prompts=prompts,
            lang=lang,
            policy=policy,
            direct=direct,
            outcome=outcome,
        )
        claims.update(group_claims)

    # A dimension nobody answered says so, rather than being absent: silence and "we looked
    # and could not tell" read identically once they are both missing from a report.
    for dimension in AnalysisDimension:
        claims.setdefault(
            dimension,
            AnalysisClaim(
                dimension=dimension,
                missing_evidence=["not assessed in this run"],
            ),
        )

    # -- claims that depend on other claims --------------------------------
    rejections, flags = apply_cross_dimension_rules(claims, our_solution=our_solution)
    outcome.rejections.extend(rejections)
    outcome.review_flags.extend(flags)

    ordered = [claims[dimension] for dimension in AnalysisDimension]

    # -- overseas dimensions, same pipeline --------------------------------
    international: list = []
    if scope is MarketScope.INTERNATIONAL:
        international = _international_claims(
            candidate, all_findings, llm=llm, prompts=prompts, lang=lang,
            policy=policy, outcome=outcome,
        )

    analysis = ClientAnalysis(
        project_id=project.project_id,
        client_id=candidate.client_id,
        client_name=candidate.client_name,
        country=candidate.country,
        industry=candidate.industry,
        our_solution=our_solution,
        claims=ordered,
        international_claims=international,
        market_scope=scope,
        finding_ids=aggregate_finding_ids(ordered + international),
        missing_evidence=aggregate_missing_evidence(ordered + international),
        lang=lang,
    )

    violations = check_client_analysis(analysis, known_finding_ids=findings_by_id)
    if violations:
        outcome.rejections.append(
            Rejection(STAGE, AnalysisRejectionCode.UNKNOWN_EVIDENCE_REF, candidate.client_id)
        )
        return

    outcome.analyses.append(analysis)


def _claims_for_group(
    candidate: ClientCandidate,
    framework_id: str,
    findings: Sequence[ResearchFinding],
    *,
    our_solution: str,
    llm,
    prompts: AnalysisPromptSet,
    lang: str,
    policy: AnalysisPolicy,
    direct: set[str],
    outcome: AnalysisOutcome,
) -> dict[AnalysisDimension, AnalysisClaim]:
    """Ask one Master Note's worth of questions and resolve the answers."""
    group = dimensions_for(framework_id)
    relevant = [f for f in findings if framework_id in f.mn_basis]
    if not relevant:
        relevant = list(findings)
    keyed = {f"F{i}": f for i, f in enumerate(relevant[: policy.max_findings_per_group], 1)}

    items = [
        f"[ORGANIZATION] {candidate.client_name}",
        f"[FRAMEWORK] {framework_id}",
        f"[OUR SOLUTION] {our_solution}",
        f"[DIMENSIONS] {', '.join(d.value for d in group)}",
    ]
    items += [
        f"[{ref}] ({f.evidence_type.value}/{f.confidence.value}) {f.finding}"
        for ref, f in keyed.items()
    ]

    result, record = send(
        llm,
        stage=f"analyze_client_{framework_id.lower()}",
        prompt=prompts.synthesize_claims,
        schema=claim_batch_schema(framework_id),
        items=items,
        output_lang=lang,
        framework_id=framework_id,
    )
    outcome.transmissions.append(record)

    passages = {f.finding_id: (f.evidence_summary or "") for f in relevant}
    out: dict[AnalysisDimension, AnalysisClaim] = {}

    for raw in result.get("claims") or []:
        if not isinstance(raw, dict):
            continue
        try:
            dimension = AnalysisDimension(raw.get("dimension"))
        except (ValueError, TypeError):
            continue
        if dimension not in group:
            outcome.rejections.append(
                Rejection(STAGE, AnalysisRejectionCode.DIMENSION_OUT_OF_GROUP, str(raw.get("dimension")))
            )
            continue
        if dimension in out:
            outcome.rejections.append(
                Rejection(STAGE, AnalysisRejectionCode.DUPLICATE_DIMENSION, dimension.value)
            )
            continue

        statement, too_long = bounded(raw.get("statement"))
        if too_long:
            # Trimming would store a sentence nobody wrote, and could reverse its meaning.
            outcome.rejections.append(
                Rejection(STAGE, AnalysisRejectionCode.STATEMENT_TOO_LONG, dimension.value)
            )
            continue

        draft = ClaimDraft(
            dimension=dimension,
            statement=statement,
            evidence_refs=[r for r in (raw.get("evidence_refs") or []) if isinstance(r, str)],
            missing_evidence=[
                m.strip() for m in (raw.get("missing_evidence") or [])
                if isinstance(m, str) and m.strip()
            ],
            organization_name=(
                raw.get("organization_name") if dimension in NAMED_ORGANIZATION_DIMENSIONS else None
            ),
            access_route=(
                _enum(raw.get("access_route"), AccessRoute) if dimension in ROUTE_DIMENSIONS else None
            ),
        )
        claim, rejections, flags = resolve_claim(
            draft, keyed, passages=passages, direct_source_ids=direct
        )
        outcome.rejections.extend(rejections)
        outcome.review_flags.extend(flags)
        out[dimension] = claim

        if dimension is AnalysisDimension.PARTNER and claim.organization_name is None:
            profile = _partner_profile(raw, claim)
            if profile is not None:
                outcome.partner_profiles.append(profile)

    return out


def _international_claims(
    candidate: ClientCandidate,
    findings: Sequence[ResearchFinding],
    *,
    llm,
    prompts: AnalysisPromptSet,
    lang: str,
    policy: AnalysisPolicy,
    outcome: AnalysisOutcome,
) -> list:
    """The overseas dimensions. Same evidence, same rules, one extra call."""
    keyed = {f"F{i}": f for i, f in enumerate(findings[: policy.max_findings_per_group], 1)}
    items = [
        f"[ORGANIZATION] {candidate.client_name}",
        f"[COUNTRY] {candidate.country}",
        f"[DIMENSIONS] {', '.join(d.value for d in InternationalDimension)}",
    ]
    items += [
        f"[{ref}] ({f.evidence_type.value}/{f.confidence.value}) {f.finding}"
        for ref, f in keyed.items()
    ]

    result, record = send(
        llm,
        stage="analyze_client_international",
        prompt=prompts.synthesize_claims,
        schema=INTERNATIONAL_CLAIMS,
        items=items,
        output_lang=lang,
    )
    outcome.transmissions.append(record)

    drafts: dict[InternationalDimension, InternationalDraft] = {}
    for raw in result.get("claims") or []:
        if not isinstance(raw, dict):
            continue
        try:
            dimension = InternationalDimension(raw.get("dimension"))
        except (ValueError, TypeError):
            continue
        if dimension in drafts:
            outcome.rejections.append(
                Rejection(STAGE, AnalysisRejectionCode.DUPLICATE_DIMENSION, dimension.value)
            )
            continue
        statement, too_long = bounded(raw.get("statement"))
        if too_long:
            outcome.rejections.append(
                Rejection(STAGE, AnalysisRejectionCode.STATEMENT_TOO_LONG, dimension.value)
            )
            continue
        drafts[dimension] = InternationalDraft(
            dimension=dimension,
            statement=statement,
            evidence_refs=[r for r in (raw.get("evidence_refs") or []) if isinstance(r, str)],
            missing_evidence=[
                m.strip() for m in (raw.get("missing_evidence") or [])
                if isinstance(m, str) and m.strip()
            ],
        )

    out = []
    for dimension in InternationalDimension:
        draft = drafts.get(dimension)
        if draft is None:
            from core.models import InternationalClaim

            out.append(
                InternationalClaim(
                    dimension=dimension, missing_evidence=["not assessed in this run"]
                )
            )
            continue
        claim, rejections = resolve_international(draft, keyed)
        outcome.rejections.extend(rejections)
        out.append(claim)
    return out


def _partner_profile(raw: dict, claim) -> Optional[PartnerProfile]:
    """A partner type, when the evidence named no partner.

    Built from the claim rather than from a field of its own: there is no name to carry, so
    there is nothing for a model to invent.
    """
    if not claim.statement:
        return None
    return PartnerProfile(
        partner_type=claim.statement,
        rationale=None,
        required_evidence=list(claim.missing_evidence),
    )


def _enum(value, enum_cls):
    try:
        return enum_cls(value)
    except (ValueError, TypeError):
        return None


def persist(outcome: AnalysisOutcome, storage) -> None:
    """Hand the analyses to storage. Criteria, drafts and partner profiles are never offered."""
    for analysis in outcome.analyses:
        storage.save_client_analysis(analysis)
