# -*- coding: utf-8 -*-
"""SWOT items to key issues.

A key issue is the question the evidence has raised, not a summary of it. "Which market do we
approach first" is an issue; "we are strong in sensors" is a restatement. The difference is
whether a person has to decide something.

The same no-shortcut rule as everywhere else: an issue that cites no resolvable SWOT item is
dropped, and ``core.evidence.check_key_issue`` rejects an empty ``swot_issue_ids``.

**A key issue is kept whole or not at all.** ``strategic_implication`` is a required field, so a
candidate without a usable one is rejected outright rather than stored with the field blanked
out. Everything in storage satisfies ``key_issue.schema.json`` completely; there is no such
thing as a partially-valid record for a reader to mistake for a finished one.

:func:`looks_like_a_directive` raises a **review flag, not a rejection**. Matching on wording is
language-specific and wrong in both directions — "추가 검증해야 한다" is perfectly good decision
support and would trip a naive blacklist. Human Decision First is guaranteed by what the output
is *made of* (a question, its conditions, its gaps, its next checks — which the prompt requires)
rather than by which verbs it avoids.
"""
from __future__ import annotations

import re
from typing import Optional, Sequence

from core.models import Confidence, KeyIssue, ResearchFinding, SWOTIssue
from core.research.confidence import cap, weakest
from core.research.models import FlagCode, Rejection, RejectionCode, ReviewFlag
from core.research.output_schemas import KEY_ISSUE_BATCH
from core.research.policy import DEFAULT_RESEARCH_POLICY, PromptSet, ResearchPolicy
from core.research.transmission import send

#: Wordings that often signal a decision being asserted rather than supported.
#:
#: A hint, not a rule. It is language-specific and unreliable in both directions: "추가 검증해야
#: 한다" is exactly the decision support we want and matches anyway, while "the obvious move is
#: Vietnam" is a directive and matches nothing here. It exists to draw a reviewer's eye, and
#: nothing is discarded on its say-so.
_DIRECTIVE_PATTERNS = (
    r"진출한다\b",
    r"결정한다\b",
    r"추진한다\b",
    r"\bwe\s+will\b",
    r"\bshould\s+enter\b",
)

_DIRECTIVE_RE = re.compile("|".join(_DIRECTIVE_PATTERNS), re.IGNORECASE)


def looks_like_a_directive(text: Optional[str]) -> bool:
    """Whether an implication *might* read as an instruction rather than as support.

    Advisory only. Callers raise a :class:`~core.research.models.ReviewFlag`; no persisted
    record is rejected because of this. See the module docstring for why.
    """
    return bool(text) and bool(_DIRECTIVE_RE.search(text))


def derive_key_issues(
    swot_issues: Sequence[SWOTIssue],
    findings: Sequence[ResearchFinding],
    *,
    llm,
    prompts: PromptSet,
    project_id: str,
    output_lang: str = "ko",
    policy: ResearchPolicy = DEFAULT_RESEARCH_POLICY,
) -> tuple[list[KeyIssue], list[Rejection], list[ReviewFlag], list]:
    """Bind SWOT items into the decisions they raise.

    Returns the issues, the candidates that were refused, the review flags, and the transmission
    records. A refused candidate produces no entity at all — nothing partially-formed reaches
    storage.
    """
    if not swot_issues:
        return [], [], [], []

    swot_keyed = {f"S{i}": issue for i, issue in enumerate(swot_issues, start=1)}
    finding_keyed = {f"F{i}": f for i, f in enumerate(findings, start=1)}
    by_finding_id = {f.finding_id: f for f in findings}

    lines = [
        f"[{ref}] {issue.category.value}: {issue.statement}"
        for ref, issue in swot_keyed.items()
    ]

    result, record = send(
        llm,
        stage="derive_key_issues",
        prompt=prompts.derive_key_issues,
        schema=KEY_ISSUE_BATCH,
        items=lines,
        output_lang=output_lang,
    )

    key_issues: list[KeyIssue] = []
    rejections: list[Rejection] = []
    flags: list[ReviewFlag] = []

    for raw in result.get("issues") or []:
        if not isinstance(raw, dict):
            rejections.append(Rejection("derive_key_issues", RejectionCode.ITEM_NOT_AN_OBJECT))
            continue

        statement = (raw.get("statement") or "").strip()
        decision_area = (raw.get("decision_area") or "").strip()
        if not statement:
            rejections.append(Rejection("derive_key_issues", RejectionCode.EMPTY_STATEMENT))
            continue
        if not decision_area:
            rejections.append(
                Rejection("derive_key_issues", RejectionCode.MISSING_DECISION_AREA)
            )
            continue

        swot_refs = [r for r in (raw.get("swot_refs") or []) if isinstance(r, str)]
        resolved_swot = [swot_keyed[r] for r in swot_refs if r in swot_keyed]
        if not resolved_swot:
            rejections.append(
                Rejection("derive_key_issues", RejectionCode.NO_SWOT_RESOLVED, ",".join(swot_refs))
            )
            continue

        # Required field. A key issue without one is not a weaker key issue, it is an
        # observation - so the candidate is refused rather than stored with a hole in it.
        implication = (raw.get("strategic_implication") or "").strip()
        if not implication:
            rejections.append(
                Rejection(
                    "derive_key_issues",
                    RejectionCode.MISSING_STRATEGIC_IMPLICATION,
                    ",".join(swot_refs),
                )
            )
            continue

        if looks_like_a_directive(implication):
            # A hint for the reviewer, not grounds for discarding the record.
            flags.append(
                ReviewFlag(
                    "derive_key_issues",
                    FlagCode.IMPLICATION_READS_AS_DIRECTIVE,
                    ",".join(swot_refs),
                )
            )

        finding_refs = [r for r in (raw.get("finding_refs") or []) if isinstance(r, str)]
        resolved_findings = [finding_keyed[r] for r in finding_refs if r in finding_keyed]

        # Whatever the model cited, the findings behind the SWOT items always belong here.
        finding_ids: list[str] = [f.finding_id for f in resolved_findings]
        for issue in resolved_swot:
            for fid in issue.finding_ids:
                if fid not in finding_ids:
                    finding_ids.append(fid)

        supporting = [
            by_finding_id[fid].confidence for fid in finding_ids if fid in by_finding_id
        ]
        ceiling = weakest(supporting) if supporting else Confidence.UNKNOWN
        proposed = _as_confidence(raw.get("confidence"))

        mn_basis: list[str] = []
        for issue in resolved_swot:
            for basis in issue.mn_basis:
                if basis not in mn_basis:
                    mn_basis.append(basis)

        missing = [m for m in (raw.get("missing_evidence") or []) if isinstance(m, str) and m.strip()]

        key_issues.append(
            KeyIssue(
                project_id=project_id,
                statement=statement,
                decision_area=decision_area,
                swot_issue_ids=[issue.issue_id for issue in resolved_swot],
                finding_ids=finding_ids,
                strategic_implication=implication,
                missing_evidence=missing,
                confidence=cap(proposed, ceiling),
                mn_basis=mn_basis,
                lang=output_lang,
            )
        )

    return key_issues, rejections, flags, [record]


def _as_confidence(value) -> Confidence:
    try:
        return Confidence(value)
    except (ValueError, TypeError):
        return Confidence.UNKNOWN
