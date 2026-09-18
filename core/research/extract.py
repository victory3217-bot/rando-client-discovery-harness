# -*- coding: utf-8 -*-
"""Evidence to findings, in two passes.

Pass 1 reads evidence and produces only what a passage states directly — FACT — plus the honest
non-answers, ASSUMPTION and MISSING_EVIDENCE. Pass 2 reasons over pass 1's findings to produce
INFERENCE.

Splitting them is what keeps an inference traceable. An inference derived straight from raw
passages would have to point at :class:`~core.intake.models.EvidenceCandidate` objects, which
are transient and never stored, leaving a persisted finding referencing something that no longer
exists. Pointing at findings instead means the trail survives.

One passage produces at most one FACT. Evidence count is not what distinguishes a fact from an
inference — combining several passages is what pass 2, SWOT and key issues are for.
"""
from __future__ import annotations

from typing import Optional, Sequence

from core.interfaces.knowledge import Framework
from core.models import (
    Confidence,
    EvidenceType,
    MarketScope,
    ResearchFinding,
    SourceMetadata,
)
from core.research.confidence import ConfidenceSignals, cap, ceiling_for
from core.research.models import EvidenceBlock, EvidenceEntry, Rejection, RejectionCode
from core.research.output_schemas import FINDING_BATCH, INFERENCE_BATCH
from core.research.policy import DEFAULT_RESEARCH_POLICY, PromptSet, ResearchPolicy
from core.research.select import dimension_brief
from core.research.transmission import send

#: Types pass 1 may emit. INFERENCE is not among them and is not in the schema either.
_PASS1_TYPES = {
    "FACT": EvidenceType.FACT,
    "ASSUMPTION": EvidenceType.ASSUMPTION,
    "MISSING_EVIDENCE": EvidenceType.MISSING_EVIDENCE,
}


def build_evidence_block(candidates: Sequence, policy: ResearchPolicy) -> EvidenceBlock:
    """Give each passage a short key the model can cite, truncating over-long ones."""
    entries: list[EvidenceEntry] = []
    for index, candidate in enumerate(candidates, start=1):
        text = candidate.text
        truncated = len(text) > policy.max_chars_per_candidate
        if truncated:
            text = text[: policy.max_chars_per_candidate] + " […truncated]"
        entries.append(
            EvidenceEntry(ref=f"E{index}", text=text, candidate=candidate, truncated=truncated)
        )
    return EvidenceBlock(entries=entries)


def _prompt_for_extraction(prompt: str, framework: Framework, lang: str) -> str:
    return f"{prompt}\n\n## Framework\n{dimension_brief(framework, lang)}"


def extract_findings(
    candidates: Sequence,
    framework: Framework,
    *,
    llm,
    prompts: PromptSet,
    project_id: str,
    sources_by_id: dict[str, SourceMetadata],
    market_scope: MarketScope = MarketScope.DOMESTIC,
    country: Optional[str] = None,
    output_lang: str = "ko",
    policy: ResearchPolicy = DEFAULT_RESEARCH_POLICY,
    today: Optional[str] = None,
) -> tuple[list[ResearchFinding], list[Rejection], list]:
    """Pass 1: read this batch of evidence through one framework.

    Every provenance field is set from the resolved candidate, never from the model. A cited
    reference that is not in the block is a fabrication and the finding is dropped.
    """
    if not candidates:
        return [], [], []

    block = build_evidence_block(candidates, policy)
    result, record = send(
        llm,
        stage="extract_findings",
        prompt=_prompt_for_extraction(prompts.extract_findings, framework, output_lang),
        schema=FINDING_BATCH,
        evidence=block,
        output_lang=output_lang,
        framework_id=framework.framework_id,
    )

    findings: list[ResearchFinding] = []
    rejections: list[Rejection] = []

    for raw in result.get("findings") or []:
        if not isinstance(raw, dict):
            rejections.append(Rejection("extract_findings", RejectionCode.ITEM_NOT_AN_OBJECT))
            continue

        statement = (raw.get("finding") or "").strip()
        if not statement:
            rejections.append(Rejection("extract_findings", RejectionCode.EMPTY_STATEMENT))
            continue

        kind = _PASS1_TYPES.get(raw.get("evidence_type"))
        if kind is None:
            rejections.append(
                Rejection(
                    "extract_findings",
                    RejectionCode.UNUSABLE_EVIDENCE_TYPE,
                    raw.get("evidence_type"),
                )
            )
            continue

        ref = raw.get("evidence_ref")
        entry = block.resolve(ref) if ref else None

        if kind is EvidenceType.FACT:
            if entry is None:
                # The characteristic hallucination: a confident statement citing a passage that
                # was never sent. Dropped rather than downgraded — we do not know what it read.
                rejections.append(
                    Rejection("extract_findings", RejectionCode.UNKNOWN_EVIDENCE_REF, ref)
                )
                continue
            source = sources_by_id.get(entry.candidate.source_id)
            if source is None:
                rejections.append(
                    Rejection("extract_findings", RejectionCode.NO_SOURCE_RECORD, ref)
                )
                continue
        else:
            source = None

        proposed = _as_confidence(raw.get("confidence"))
        signals = ConfidenceSignals(
            source=source,
            today=today,
            locator=entry.candidate.locator if entry is not None else None,
        )
        allowed = ceiling_for(kind, signals, policy=policy)
        summary = (raw.get("evidence_summary") or "").strip() or None

        if kind is EvidenceType.MISSING_EVIDENCE and not summary:
            # The rule exists because "we don't know" without "what would tell us" is not a
            # research output, it is a shrug.
            summary = statement

        finding = ResearchFinding(
            project_id=project_id,
            finding=statement,
            evidence_type=kind,
            mn_basis=[framework.framework_id],
            confidence=cap(proposed, allowed),
            market_scope=market_scope,
            evidence_summary=summary,
            country=country,
            lang=output_lang,
        )

        if kind is EvidenceType.FACT and entry is not None and source is not None:
            finding.source_id = source.source_id
            finding.source_type = source.source_category
            finding.page_or_section = entry.candidate.locator
            finding.source_date = source.source_date

        findings.append(finding)

    return findings, rejections, [record]


def infer_findings(
    findings: Sequence[ResearchFinding],
    framework: Framework,
    *,
    llm,
    prompts: PromptSet,
    project_id: str,
    market_scope: MarketScope = MarketScope.DOMESTIC,
    country: Optional[str] = None,
    output_lang: str = "ko",
    policy: ResearchPolicy = DEFAULT_RESEARCH_POLICY,
) -> tuple[list[ResearchFinding], list[Rejection], list]:
    """Pass 2: reason over findings, producing inferences that name what they rest on.

    The resulting findings carry no source fields at all. That is the point: an inference is
    ours, not the document's, and it should not be able to masquerade as a quotation.
    """
    usable = [f for f in findings if f.evidence_type is EvidenceType.FACT]
    if not usable:
        return [], [], []

    keyed = {f"F{i}": finding for i, finding in enumerate(usable, start=1)}
    lines = [f"[{ref}] {finding.finding}" for ref, finding in keyed.items()]

    result, record = send(
        llm,
        stage="infer_findings",
        prompt=_prompt_for_extraction(prompts.for_stage("infer_findings"), framework, output_lang),
        schema=INFERENCE_BATCH,
        items=lines,
        output_lang=output_lang,
        framework_id=framework.framework_id,
    )

    inferences: list[ResearchFinding] = []
    rejections: list[Rejection] = []

    for raw in result.get("inferences") or []:
        if not isinstance(raw, dict):
            rejections.append(Rejection("infer_findings", RejectionCode.ITEM_NOT_AN_OBJECT))
            continue

        statement = (raw.get("finding") or "").strip()
        if not statement:
            rejections.append(Rejection("infer_findings", RejectionCode.EMPTY_STATEMENT))
            continue

        refs = [r for r in (raw.get("finding_refs") or []) if isinstance(r, str)]
        resolved = [keyed[r] for r in refs if r in keyed]
        if not resolved:
            rejections.append(
                Rejection("infer_findings", RejectionCode.NO_SUPPORTING_FINDING, ",".join(refs))
            )
            continue

        proposed = _as_confidence(raw.get("confidence"))
        allowed = ceiling_for(
            EvidenceType.INFERENCE,
            supporting=[f.confidence for f in resolved],
            policy=policy,
        )

        inferences.append(
            ResearchFinding(
                project_id=project_id,
                finding=statement,
                evidence_type=EvidenceType.INFERENCE,
                mn_basis=[framework.framework_id],
                confidence=cap(proposed, allowed),
                market_scope=market_scope,
                supporting_finding_ids=[f.finding_id for f in resolved],
                evidence_summary=(raw.get("evidence_summary") or "").strip() or None,
                country=country,
                lang=output_lang,
            )
        )

    return inferences, rejections, [record]


def _as_confidence(value) -> Confidence:
    try:
        return Confidence(value)
    except (ValueError, TypeError):
        return Confidence.UNKNOWN
