# -*- coding: utf-8 -*-
"""Findings to SWOT.

The signature is the first control: this function takes findings. There is no path through the
code that produces a SWOT item without them, which is a stronger guarantee than a rule someone
has to remember. Three more layers back it up — an item citing no resolvable finding is dropped
here, ``swot_issue.schema.json`` sets ``minItems: 1``, and ``core.evidence.check_swot_issue``
rejects an empty list.

"We have good technology" is the failure this prevents. Without a finding to cite there is
nothing to classify, so the statement never becomes a Strength; it becomes nothing at all.
"""
from __future__ import annotations

from typing import Optional, Sequence

from core.models import SWOTCategory, SWOTIssue, ResearchFinding
from core.research.models import Rejection, RejectionCode
from core.research.output_schemas import SWOT_BATCH
from core.research.policy import DEFAULT_RESEARCH_POLICY, PromptSet, ResearchPolicy
from core.research.transmission import send


def classify_swot(
    findings: Sequence[ResearchFinding],
    *,
    llm,
    prompts: PromptSet,
    project_id: str,
    output_lang: str = "ko",
    policy: ResearchPolicy = DEFAULT_RESEARCH_POLICY,
) -> tuple[list[SWOTIssue], list[Rejection], list]:
    """Group findings into SWOT items.

    ``mn_basis`` is the union of the cited findings' own bases rather than anything the model
    says, so a SWOT item inherits the frameworks that actually produced its evidence.
    """
    if not findings:
        return [], [], []

    keyed = {f"F{i}": finding for i, finding in enumerate(findings, start=1)}
    lines = [
        f"[{ref}] ({finding.evidence_type.value}/{finding.confidence.value}) {finding.finding}"
        for ref, finding in keyed.items()
    ]

    result, record = send(
        llm,
        stage="classify_swot",
        prompt=prompts.classify_swot,
        schema=SWOT_BATCH,
        items=lines,
        output_lang=output_lang,
    )

    issues: list[SWOTIssue] = []
    rejections: list[Rejection] = []

    for raw in result.get("items") or []:
        if not isinstance(raw, dict):
            rejections.append(Rejection("classify_swot", RejectionCode.ITEM_NOT_AN_OBJECT))
            continue

        statement = (raw.get("statement") or "").strip()
        if not statement:
            rejections.append(Rejection("classify_swot", RejectionCode.EMPTY_STATEMENT))
            continue

        try:
            category = SWOTCategory(raw.get("category"))
        except (ValueError, TypeError):
            rejections.append(
                Rejection("classify_swot", RejectionCode.UNUSABLE_CATEGORY, raw.get("category"))
            )
            continue

        refs = [r for r in (raw.get("finding_refs") or []) if isinstance(r, str)]
        resolved = [keyed[r] for r in refs if r in keyed]
        if not resolved:
            rejections.append(
                Rejection("classify_swot", RejectionCode.NO_FINDING_RESOLVED, ",".join(refs))
            )
            continue

        mn_basis: list[str] = []
        for finding in resolved:
            for basis in finding.mn_basis:
                if basis not in mn_basis:
                    mn_basis.append(basis)

        issues.append(
            SWOTIssue(
                project_id=project_id,
                category=category,
                statement=statement,
                finding_ids=[f.finding_id for f in resolved],
                mn_basis=mn_basis,
                lang=output_lang,
            )
        )

    return issues, rejections, [record]
