# -*- coding: utf-8 -*-
"""Which review band a candidate falls in. A rule table, not a model and not a score.

Three properties matter more than the particular thresholds:

**No numbers.** There is no weighted sum anywhere. A total conceals which criterion drove the
answer and invites tuning the weights until the output looks right, which is the opposite of
traceable.

**No model.** The band is computed here, so "why is this P1" has an answer in code that a person
can read and argue with. A model-written justification could disagree with the rule that
actually fired and nobody would know which was true.

**No prose.** The reasons are :class:`~core.models.PriorityReasonCode` values; the sentences a
person reads come from ``locales/*.json``, like every other enum in this harness.

A band is a review order, not an instruction. ``P1`` means the evidence supports looking here
first — the decision to approach anyone stays with a person.
"""
from __future__ import annotations

from typing import Iterable, Optional

from core.models import (
    ClientCandidate,
    FitAssessment,
    FitCriterion,
    FitLevel,
    PriorityDecision,
    PriorityReasonCode,
    SalesPriority,
    aggregate_missing_evidence,
)

#: Problem, solution and capability. Without these there is nothing to sell to anyone.
CORE_CRITERIA: tuple[FitCriterion, ...] = (
    FitCriterion.PROBLEM_FIT,
    FitCriterion.SOLUTION_FIT,
    FitCriterion.CAPABILITY_FIT,
)

#: Whether a sale could actually happen: can they buy, and can we reach them.
COMMERCIAL_CRITERIA: tuple[FitCriterion, ...] = (
    FitCriterion.PURCHASING_POTENTIAL,
    FitCriterion.ACCESSIBILITY,
)

_POSITIVE = (FitLevel.STRONG, FitLevel.MODERATE)
_UNSETTLED = (FitLevel.UNKNOWN, FitLevel.EVIDENCE_NEEDED)


def _level(candidate: ClientCandidate, criterion: FitCriterion) -> FitLevel:
    assessment = candidate.fit_for(criterion)
    return assessment.level if assessment else FitLevel.UNKNOWN


def _assessment(candidate: ClientCandidate, criterion: FitCriterion) -> Optional[FitAssessment]:
    return candidate.fit_for(criterion)


def has_direct_evidence(
    assessment: Optional[FitAssessment],
    direct_source_ids: Iterable[str],
) -> bool:
    """Whether this criterion rests on something other than a search snippet.

    ``direct_source_ids`` are the sources for which the harness holds real document
    provenance — a page, a slide, a cell range. A search snippet is the few lines an engine
    chose to show, and nothing here has opened the page it came from.
    """
    if assessment is None:
        return False
    direct = set(direct_source_ids)
    if any(source_id in direct for source_id in assessment.source_ids):
        return True
    # A finding cited without a source id came from the diagnosis, which was itself grounded.
    return bool(assessment.finding_ids) and not assessment.source_ids


def decide_priority(
    candidate: ClientCandidate,
    *,
    direct_source_ids: Iterable[str] = (),
    identity_verified: bool = True,
) -> PriorityDecision:
    """Apply the rule table.

    The order of the checks is the rule: the first disqualifier wins, then P1's gate, then the
    progressively weaker bands.
    """
    direct = set(direct_source_ids)
    reasons: list[PriorityReasonCode] = []

    core_levels = {criterion: _level(candidate, criterion) for criterion in CORE_CRITERIA}
    commercial_levels = {c: _level(candidate, c) for c in COMMERCIAL_CRITERIA}
    competitive = _level(candidate, FitCriterion.COMPETITIVE_SITUATION)

    # The same canonical set the candidate's own missing_evidence comes from.
    missing = aggregate_missing_evidence(candidate.fit)

    # -- disqualifiers ------------------------------------------------------
    if any(level is FitLevel.WEAK for level in core_levels.values()):
        # Nothing downstream rescues a core mismatch: there is no problem to solve, or no
        # capability to solve it with.
        reasons.append(PriorityReasonCode.CORE_FIT_WEAK)
        return PriorityDecision(
            band=SalesPriority.DEFERRED, reason_codes=reasons, missing_evidence=missing
        )

    if competitive is FitLevel.WEAK:
        reasons.append(PriorityReasonCode.COMPETITIVE_BARRIER)
        return PriorityDecision(
            band=SalesPriority.DEFERRED, reason_codes=reasons, missing_evidence=missing
        )

    # -- P1, and the gate it has to pass ------------------------------------
    core_positive = all(level in _POSITIVE for level in core_levels.values())
    core_settled = not any(level in _UNSETTLED for level in core_levels.values())

    if core_positive and core_settled:
        reasons.append(PriorityReasonCode.CORE_FIT_POSITIVE)

        problem = _assessment(candidate, FitCriterion.PROBLEM_FIT)
        problem_direct = has_direct_evidence(problem, direct)

        commercial_ready = [
            criterion
            for criterion, level in commercial_levels.items()
            if level in _POSITIVE and has_direct_evidence(_assessment(candidate, criterion), direct)
        ]

        if problem_direct and commercial_ready:
            reasons.append(PriorityReasonCode.COMMERCIAL_SIGNAL_CONFIRMED)
            if not identity_verified:
                # Worth putting first, but somebody has to confirm which entity this is before
                # anyone acts on it.
                reasons.append(PriorityReasonCode.IDENTITY_VERIFICATION_NEEDED)
            return PriorityDecision(
                band=SalesPriority.P1, reason_codes=reasons, missing_evidence=missing
            )

        # Core fits hold up, but the case for P1 does not. Say which half is missing, and be
        # precise about why: "the evidence is only a snippet" and "there is no evidence" are
        # different problems needing different work, and one code for both would hide that.
        if _is_snippet_limited(candidate, direct):
            reasons.append(PriorityReasonCode.SNIPPET_ONLY_LIMITATION)
        if commercial_levels[FitCriterion.PURCHASING_POTENTIAL] in _UNSETTLED:
            reasons.append(PriorityReasonCode.PURCHASE_EVIDENCE_NEEDED)
        if commercial_levels[FitCriterion.ACCESSIBILITY] in _UNSETTLED:
            reasons.append(PriorityReasonCode.ACCESS_EVIDENCE_NEEDED)
        if not identity_verified:
            reasons.append(PriorityReasonCode.IDENTITY_VERIFICATION_NEEDED)

        return PriorityDecision(
            band=SalesPriority.P2, reason_codes=reasons, missing_evidence=missing
        )

    # -- weaker bands -------------------------------------------------------
    unsettled_total = sum(
        1 for criterion in FitCriterion if _level(candidate, criterion) in _UNSETTLED
    )
    core_unsettled = sum(1 for level in core_levels.values() if level in _UNSETTLED)

    if core_unsettled >= 2:
        reasons.append(PriorityReasonCode.INSUFFICIENT_EVIDENCE)
        return PriorityDecision(
            band=SalesPriority.UNKNOWN, reason_codes=reasons, missing_evidence=missing
        )

    reasons.append(PriorityReasonCode.INSUFFICIENT_EVIDENCE)
    if commercial_levels[FitCriterion.PURCHASING_POTENTIAL] in _UNSETTLED:
        reasons.append(PriorityReasonCode.PURCHASE_EVIDENCE_NEEDED)
    if commercial_levels[FitCriterion.ACCESSIBILITY] in _UNSETTLED:
        reasons.append(PriorityReasonCode.ACCESS_EVIDENCE_NEEDED)
    if not identity_verified:
        reasons.append(PriorityReasonCode.IDENTITY_VERIFICATION_NEEDED)

    band = SalesPriority.P3 if unsettled_total >= 2 else SalesPriority.UNKNOWN
    return PriorityDecision(band=band, reason_codes=reasons, missing_evidence=missing)


def _is_snippet_limited(candidate: ClientCandidate, direct: set[str]) -> bool:
    """Whether a criterion that matters for P1 rests on evidence, but only on snippets.

    The distinction this draws is the point of the code. A criterion with no evidence needs
    research; a criterion whose evidence is a search summary needs somebody to open the page.
    Reporting both as "snippet only" would send the reader after the wrong task.
    """
    for criterion in (FitCriterion.PROBLEM_FIT, *COMMERCIAL_CRITERIA):
        assessment = _assessment(candidate, criterion)
        if assessment is None:
            continue
        has_refs = bool(assessment.finding_ids or assessment.source_ids)
        if has_refs and not has_direct_evidence(assessment, direct):
            return True
    return False


