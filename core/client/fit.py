# -*- coding: utf-8 -*-
"""Assessing one organization against the eight criteria.

Two criteria get extra scrutiny, because they are the two that a model will otherwise satisfy
with reasoning rather than evidence.

**Purchasing potential.** The default move is "they are large, so they can afford it". Size is
not a buying signal, so ``STRONG`` requires a named :class:`~core.client.models.PurchaseSignal`,
a resolvable reference, and evidence that is not a search snippet. Without all three the level
comes down.

**Accessibility.** The equivalent is "they are a public body, so we can contact them". ``STRONG``
requires a named :class:`~core.client.models.AccessRoute` on the same terms.

A reason longer than ``MAX_FIT_REASON_CHARS`` is **refused, not trimmed.** The output schema
states the limit, so a longer string is a provider that broke the contract; cutting it at 500
characters would store a sentence nobody wrote, possibly reversing its meaning mid-clause, and
would do it silently. The criterion degrades to ``UNKNOWN`` and a rejection code records that it
happened. Nothing retries: a retry engine here would be complexity bought with the one thing
this stage is supposed to protect.

Findings are selected by ``mn_basis`` rather than re-analysed. Phase 3 already read the evidence
through MN02–MN07; running the frameworks again per client would produce volume, not insight.
"""
from __future__ import annotations

from typing import Optional, Sequence

from core.client.models import (
    AccessRoute,
    FitDraft,
    PurchaseSignal,
    VerifiedOrganization,
)
from core.client.output_schemas import FIT_ASSESSMENT
from core.client.policy import DEFAULT_DISCOVERY_POLICY, ClientPromptSet, DiscoveryPolicy
from core.models import (
    MAX_FIT_REASON_CHARS,
    FitAssessment,
    FitCriterion,
    FitLevel,
    ResearchFinding,
    SourceMetadata,
)
from core.research.models import Rejection, RejectionCode, ReviewFlag
from core.transmission import send

#: Which Master Note perspective each criterion draws on. Phase 3 already produced findings
#: tagged with these, so this selects rather than re-analyses.
CRITERION_FRAMEWORKS: dict[FitCriterion, tuple[str, ...]] = {
    FitCriterion.PROBLEM_FIT: ("MN03",),
    FitCriterion.SOLUTION_FIT: ("MN04",),
    FitCriterion.CAPABILITY_FIT: ("MN02",),
    FitCriterion.MARKET_ATTRACTIVENESS: ("MN02", "MN07"),
    FitCriterion.PURCHASING_POTENTIAL: ("MN03", "MN07"),
    FitCriterion.ACCESSIBILITY: ("MN05",),
    FitCriterion.COMPETITIVE_SITUATION: ("MN04",),
    FitCriterion.EVIDENCE_QUALITY: (),
}

class FlagCodes:
    """Review flags this stage raises."""

    SNIPPET_ONLY_DOWNGRADE = "SNIPPET_ONLY_DOWNGRADE"


#: Criteria where a search summary is not enough to claim the strongest level.
_SNIPPET_SENSITIVE = frozenset(
    {
        FitCriterion.PROBLEM_FIT,
        FitCriterion.PURCHASING_POTENTIAL,
        FitCriterion.ACCESSIBILITY,
    }
)


#: Criteria that need a named signal before they may be favourable.
_SIGNAL_REQUIRED = {
    FitCriterion.PURCHASING_POTENTIAL: "signal_type",
    FitCriterion.ACCESSIBILITY: "access_route",
}


def findings_for(
    criterion: FitCriterion,
    findings: Sequence[ResearchFinding],
    *,
    limit: int = 24,
) -> list[ResearchFinding]:
    """Findings whose framework matches this criterion. Unfiltered for EVIDENCE_QUALITY."""
    frameworks = CRITERION_FRAMEWORKS[criterion]
    if not frameworks:
        return list(findings)[:limit]
    return [f for f in findings if any(mn in f.mn_basis for mn in frameworks)][:limit]


def assess_fit(
    organization: VerifiedOrganization,
    findings: Sequence[ResearchFinding],
    *,
    llm,
    prompts: ClientPromptSet,
    sources_by_id: dict[str, SourceMetadata],
    direct_source_ids: Optional[set[str]] = None,
    output_lang: str = "ko",
    policy: DiscoveryPolicy = DEFAULT_DISCOVERY_POLICY,
) -> tuple[list[FitAssessment], Optional[str], list[Rejection], list[ReviewFlag], list]:
    """Assess all eight criteria for one organization.

    Returns the assessments, the discovery rationale, rejections, review flags and the
    transmission record. Every criterion comes back, always: one that nobody could judge says
    ``UNKNOWN`` rather than being absent, because silence and "we looked and could not tell"
    read identically once they are both missing from a report.
    """
    direct = direct_source_ids if direct_source_ids is not None else set()
    keyed = {f"F{i}": f for i, f in enumerate(findings[: policy.max_findings_per_assessment], 1)}
    lines = [
        f"[{ref}] ({f.evidence_type.value}/{f.confidence.value}) {f.finding}"
        for ref, f in keyed.items()
    ]
    lines.insert(0, f"[ORGANIZATION] {organization.name}")

    result, record = send(
        llm,
        stage="assess_fit",
        prompt=prompts.assess_fit,
        schema=FIT_ASSESSMENT,
        items=lines,
        output_lang=output_lang,
    )

    drafts: dict[FitCriterion, FitDraft] = {}
    discarded: set[FitCriterion] = set()
    rejections: list[Rejection] = []
    flags: list[ReviewFlag] = []

    for raw in result.get("assessments") or []:
        if not isinstance(raw, dict):
            rejections.append(Rejection("assess_fit", RejectionCode.ITEM_NOT_AN_OBJECT))
            continue
        try:
            criterion = FitCriterion(raw.get("criterion"))
            level = FitLevel(raw.get("level"))
        except (ValueError, TypeError):
            rejections.append(
                Rejection("assess_fit", RejectionCode.UNUSABLE_CATEGORY, raw.get("criterion"))
            )
            continue
        if criterion in drafts:
            rejections.append(
                Rejection("assess_fit", RejectionCode.DUPLICATE_ASSESSMENT, criterion.value)
            )
            continue

        reason, too_long = _bounded(raw.get("reason"))
        if too_long:
            # The whole assessment is discarded, not just its reason: a level whose stated
            # justification was unusable is not a level worth keeping. The criterion falls
            # through to UNKNOWN below.
            rejections.append(
                Rejection("assess_fit", RejectionCode.REASON_TOO_LONG, criterion.value)
            )
            discarded.add(criterion)
            continue

        drafts[criterion] = FitDraft(
            criterion=criterion,
            level=level,
            reason=reason,
            evidence_refs=[r for r in (raw.get("evidence_refs") or []) if isinstance(r, str)],
            missing_evidence=[
                m.strip() for m in (raw.get("missing_evidence") or [])
                if isinstance(m, str) and m.strip()
            ],
            signal_type=_enum(raw.get("signal_type"), PurchaseSignal),
            access_route=_enum(raw.get("access_route"), AccessRoute),
        )

    assessments: list[FitAssessment] = []
    for criterion in FitCriterion:
        draft = drafts.get(criterion)
        if draft is None:
            # UNKNOWN with no stated gap when the output was discarded: the rejection record
            # says what went wrong, and inventing a research gap out of a provider fault would
            # send the reader after work that does not exist.
            assessments.append(
                FitAssessment(
                    criterion=criterion,
                    level=FitLevel.UNKNOWN,
                    missing_evidence=(
                        [] if criterion in discarded else ["not assessed in this run"]
                    ),
                )
            )
            continue
        assessment, criterion_rejections, criterion_flags = _resolve(
            draft, keyed, direct, organization
        )
        assessments.append(assessment)
        rejections.extend(criterion_rejections)
        flags.extend(criterion_flags)

    # Handed back at full length. The pipeline owns the decision, because an over-long
    # rationale disqualifies the candidate rather than one criterion.
    rationale, rationale_too_long = _bounded(result.get("discovery_rationale"))
    if rationale_too_long:
        rationale = None
        rejections.append(Rejection("assess_fit", RejectionCode.RATIONALE_TOO_LONG))
    return assessments, rationale, rejections, flags, [record]


def _resolve(
    draft: FitDraft,
    keyed: dict[str, ResearchFinding],
    direct: set[str],
    organization: VerifiedOrganization,
) -> tuple[FitAssessment, list[Rejection], list[ReviewFlag]]:
    """Turn one draft into an assessment, lowering the level where it is not earned."""
    rejections: list[Rejection] = []
    flags: list[ReviewFlag] = []
    criterion = draft.criterion
    level = draft.level

    resolved = [keyed[ref] for ref in draft.evidence_refs if ref in keyed]
    unresolved = [ref for ref in draft.evidence_refs if ref not in keyed]
    if unresolved:
        rejections.append(
            Rejection("assess_fit", RejectionCode.UNKNOWN_EVIDENCE_REF, ",".join(unresolved))
        )

    finding_ids = [f.finding_id for f in resolved]
    source_ids = [f.source_id for f in resolved if f.source_id]

    # A favourable level with nothing behind it is an opinion.
    if level in (FitLevel.STRONG, FitLevel.MODERATE) and not (finding_ids or source_ids):
        rejections.append(
            Rejection("assess_fit", RejectionCode.NO_FINDING_RESOLVED, criterion.value)
        )
        level = FitLevel.EVIDENCE_NEEDED

    # Purchasing potential and accessibility need a named signal, not an argument.
    signal_field = _SIGNAL_REQUIRED.get(criterion)
    if signal_field and level in (FitLevel.STRONG, FitLevel.MODERATE):
        signal = draft.signal_type if signal_field == "signal_type" else draft.access_route
        if signal is None:
            rejections.append(
                Rejection("assess_fit", RejectionCode.NO_QUALIFYING_SIGNAL, criterion.value)
            )
            level = FitLevel.EVIDENCE_NEEDED

    # A search snippet is an engine's extract; nothing here has opened the page.
    if level is FitLevel.STRONG and criterion in _SNIPPET_SENSITIVE:
        if not _has_direct(source_ids, finding_ids, direct):
            flags.append(
                ReviewFlag("assess_fit", FlagCodes.SNIPPET_ONLY_DOWNGRADE, criterion.value)
            )
            level = FitLevel.MODERATE

    missing = list(draft.missing_evidence)
    if level is FitLevel.EVIDENCE_NEEDED and not missing:
        missing = [f"direct evidence for {criterion.value.lower().replace('_', ' ')}"]

    return (
        FitAssessment(
            criterion=criterion,
            level=level,
            reason=draft.reason,
            finding_ids=finding_ids,
            source_ids=sorted(set(source_ids)),
            missing_evidence=missing,
        ),
        rejections,
        flags,
    )


def _has_direct(source_ids: Sequence[str], finding_ids: Sequence[str], direct: set[str]) -> bool:
    if any(source_id in direct for source_id in source_ids):
        return True
    return bool(finding_ids) and not source_ids


def _bounded(value) -> tuple[Optional[str], bool]:
    """The stripped string and whether it broke the length contract.

    Returns ``(None, False)`` for anything absent or blank and ``(None, True)`` for a string
    over the cap. Deliberately never returns a shortened string: that is the whole point of
    this function existing instead of a slice.
    """
    if not isinstance(value, str):
        return None, False
    stripped = value.strip()
    if not stripped:
        return None, False
    if len(stripped) > MAX_FIT_REASON_CHARS:
        return None, True
    return stripped, False


def _enum(value, enum_cls):
    try:
        return enum_cls(value)
    except (ValueError, TypeError):
        return None
