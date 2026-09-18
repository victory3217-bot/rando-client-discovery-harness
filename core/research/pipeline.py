# -*- coding: utf-8 -*-
"""Evidence → Finding → SWOT → Key Issue, in that order and no other.

The pipeline is a sequence of pure functions with the providers passed in. It does not read
files, does not log and does not decide anything an operator should be deciding — it produces
material for a person to judge, with every step traceable to the step before it.

Order is enforced by data flow rather than by documentation: ``classify_swot`` cannot run
before there are findings because it takes findings, and ``derive_key_issues`` cannot run
before there are SWOT items for the same reason.
"""
from __future__ import annotations

from typing import Iterable, Optional, Sequence

from core.interfaces.knowledge import KnowledgeProvider
from core.models import MarketScope, Project, SourceMetadata
from core.research.classify import classify_swot
from core.research.extract import extract_findings, infer_findings
from core.research.models import ResearchOutcome
from core.research.policy import (
    DEFAULT_RESEARCH_POLICY,
    PromptSet,
    ResearchPolicy,
    batch_candidates,
    batch_items,
)
from core.research.select import frameworks_for
from core.research.synthesize import derive_key_issues


def run_research(
    *,
    project: Project,
    candidates: Sequence,
    sources: Sequence[SourceMetadata],
    knowledge: KnowledgeProvider,
    llm,
    prompts: PromptSet,
    policy: ResearchPolicy = DEFAULT_RESEARCH_POLICY,
    frameworks: Optional[Iterable[str]] = None,
    market_scope: Optional[MarketScope] = None,
    country: Optional[str] = None,
    today: Optional[str] = None,
    include_inferences: bool = True,
) -> ResearchOutcome:
    """Run the full diagnosis for one project.

    ``frameworks`` overrides the policy for this run — an operator narrowing the analysis
    deliberately, which is different from the pipeline narrowing it quietly.

    ``today`` feeds the recency rule in ``core.research.confidence``. It is a parameter rather
    than a clock read so that the core stays free of ambient state and the rule is testable.
    """
    outcome = ResearchOutcome()
    sources_by_id = {source.source_id: source for source in sources}
    scope = market_scope or (
        project.market_scope[0] if project.market_scope else MarketScope.DOMESTIC
    )
    lang = project.output_lang

    # -- Evidence → Finding -------------------------------------------------
    for batch in batch_candidates(candidates, policy):
        batch_text = "\n".join(candidate.text for candidate in batch)
        selected, skipped = frameworks_for(
            knowledge, policy=policy, requested=frameworks, batch_text=batch_text
        )
        for framework_id, reason in skipped:
            if (framework_id, reason) not in outcome.skipped_frameworks:
                outcome.skipped_frameworks.append((framework_id, reason))

        for framework in selected:
            found, rejected, records = extract_findings(
                batch,
                framework,
                llm=llm,
                prompts=prompts,
                project_id=project.project_id,
                sources_by_id=sources_by_id,
                market_scope=scope,
                country=country,
                output_lang=lang,
                policy=policy,
                today=today,
            )
            outcome.findings.extend(found)
            outcome.rejections.extend(rejected)
            outcome.transmissions.extend(records)

    # -- Finding → Inference ------------------------------------------------
    # A second pass over what pass 1 established, so an inference can name the findings it
    # rests on instead of pointing at transient evidence objects.
    if include_inferences and outcome.findings:
        selected, _ = frameworks_for(knowledge, policy=policy, requested=frameworks)
        for framework in selected:
            scoped = [f for f in outcome.facts if framework.framework_id in f.mn_basis]
            if not scoped:
                continue
            inferred, rejected, records = infer_findings(
                scoped,
                framework,
                llm=llm,
                prompts=prompts,
                project_id=project.project_id,
                market_scope=scope,
                country=country,
                output_lang=lang,
                policy=policy,
            )
            outcome.findings.extend(inferred)
            outcome.rejections.extend(rejected)
            outcome.transmissions.extend(records)

    # -- Finding → SWOT -----------------------------------------------------
    for batch in batch_items(outcome.findings, policy.max_findings_per_batch):
        issues, rejected, records = classify_swot(
            batch,
            llm=llm,
            prompts=prompts,
            project_id=project.project_id,
            output_lang=lang,
            policy=policy,
        )
        outcome.swot_issues.extend(issues)
        outcome.rejections.extend(rejected)
        outcome.transmissions.extend(records)

    # -- SWOT → Key Issue ---------------------------------------------------
    if outcome.swot_issues:
        key_issues, rejected, flagged, records = derive_key_issues(
            outcome.swot_issues,
            outcome.findings,
            llm=llm,
            prompts=prompts,
            project_id=project.project_id,
            output_lang=lang,
            policy=policy,
        )
        outcome.key_issues.extend(key_issues)
        outcome.rejections.extend(rejected)
        outcome.review_flags.extend(flagged)
        outcome.transmissions.extend(records)

    return outcome


def persist(outcome: ResearchOutcome, storage) -> None:
    """Hand the outcome to the configured storage adapter.

    Findings, SWOT items and key issues only. Evidence candidates are never offered to storage —
    there is no method that would take them.
    """
    for finding in outcome.findings:
        storage.save_finding(finding)
    for issue in outcome.swot_issues:
        storage.save_swot_issue(issue)
    for key_issue in outcome.key_issues:
        storage.save_key_issue(key_issue)
