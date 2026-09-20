# -*- coding: utf-8 -*-
"""Client-specific research: what else do we need to know about this one organization.

Almost nothing new happens here. The criteria stage asks a model what is worth looking up,
and everything after that is the Phase 3 pipeline unchanged — ``ingest_search_results`` builds
the sources and candidates, ``extract_findings`` reads them through the Master Notes, and the
provenance and confidence rules that governed company-level research govern these findings too.

Building a second research engine for "client research" would mean two places where a search
snippet becomes a fact, and they would not stay in agreement.

The stage is optional. With no search provider the analysis runs on the findings the project
already has, which is what the offline tests and a classroom without network access do.
"""
from __future__ import annotations

from typing import Optional, Sequence

from core.analysis.models import ClientResearchCriteria
from core.analysis.output_schemas import CLIENT_RESEARCH_CRITERIA
from core.analysis.policy import DEFAULT_ANALYSIS_POLICY, AnalysisPolicy, AnalysisPromptSet
from core.interfaces.knowledge import KnowledgeProvider
from core.models import (
    AnalysisDimension,
    ClientCandidate,
    MarketScope,
    ResearchFinding,
    SourceMetadata,
)
from core.research.extract import extract_findings
from core.research.models import Rejection
from core.research.sources import ingest_search_results
from core.transmission import send


def build_client_criteria(
    candidate: ClientCandidate,
    findings: Sequence[ResearchFinding],
    *,
    llm,
    prompts: AnalysisPromptSet,
    capability: str,
    our_solution: str,
    output_lang: str = "ko",
    policy: AnalysisPolicy = DEFAULT_ANALYSIS_POLICY,
) -> tuple[ClientResearchCriteria, list]:
    """What still needs looking up about this client.

    The organization is named in the prompt because it is already verified — it got into the
    candidate pool by appearing in evidence. That is different from asking a model to name one.
    """
    items = [
        f"[ORGANIZATION] {candidate.client_name}",
        f"[COUNTRY] {candidate.country}",
        f"[INDUSTRY] {candidate.industry}",
        f"[OUR CAPABILITY] {capability}",
        f"[OUR SOLUTION] {our_solution}",
        f"[WHY THIS CANDIDATE] {candidate.discovery_rationale}",
    ]
    items += [f"[KNOWN GAP] {gap}" for gap in candidate.missing_evidence]
    items += [
        f"[F{i}] {f.finding}" for i, f in enumerate(findings[: policy.max_findings_per_group], 1)
    ]

    result, record = send(
        llm,
        stage="client_research_criteria",
        prompt=prompts.research_criteria,
        schema=CLIENT_RESEARCH_CRITERIA,
        items=items,
        output_lang=output_lang,
    )

    queries: list[str] = []
    targets: list[AnalysisDimension] = []
    for raw in (result.get("queries") or [])[: policy.max_queries_per_client]:
        if not isinstance(raw, dict):
            continue
        query = (raw.get("query") or "").strip()
        if not query or query in queries:
            continue
        queries.append(query)
        try:
            dimension = AnalysisDimension(raw.get("target_dimension"))
        except (ValueError, TypeError):
            continue
        if dimension not in targets:
            targets.append(dimension)

    criteria = ClientResearchCriteria(
        client_id=candidate.client_id,
        queries=queries,
        target_dimensions=targets,
        country=candidate.country or None,
        industry=candidate.industry or None,
    )
    return criteria, [record]


def research_client(
    criteria: ClientResearchCriteria,
    *,
    search,
    knowledge: KnowledgeProvider,
    llm,
    prompts,
    project_id: str,
    market_scope: MarketScope,
    country: Optional[str] = None,
    frameworks: Sequence[str] = ("MN03", "MN04", "MN05", "MN06"),
    output_lang: str = "ko",
    policy: AnalysisPolicy = DEFAULT_ANALYSIS_POLICY,
    today: Optional[str] = None,
) -> tuple[list[SourceMetadata], list[ResearchFinding], list[Rejection], list]:
    """Search, ingest and read — all of it with the Phase 3 machinery.

    ``prompts`` is the *research* prompt set, not the analysis one: this calls
    ``extract_findings``, which is the same function company-level research calls.
    """
    sources: list[SourceMetadata] = []
    findings: list[ResearchFinding] = []
    rejections: list[Rejection] = []
    records: list = []

    if search is None or not criteria.queries:
        return sources, findings, rejections, records

    for query in criteria.queries:
        hits = search.search(
            query,
            scope=market_scope,
            country=country,
            limit=policy.max_results_per_query,
        )
        if not hits:
            continue
        batch_sources, candidates = ingest_search_results(hits, project_id=project_id)
        sources.extend(batch_sources)
        sources_by_id = {s.source_id: s for s in batch_sources}

        for framework_id in frameworks:
            framework = knowledge.get_framework(framework_id)
            if framework is None:
                continue
            found, rejected, batch_records = extract_findings(
                candidates,
                framework,
                llm=llm,
                prompts=prompts,
                project_id=project_id,
                sources_by_id=sources_by_id,
                market_scope=market_scope,
                country=country,
                output_lang=output_lang,
                policy=policy.research_policy,
                today=today,
            )
            findings.extend(found)
            rejections.extend(rejected)
            records.extend(batch_records)

    return sources, findings, rejections, records
