# -*- coding: utf-8 -*-
"""Turning the model's suggestions into a strategy, and refusing the parts it has not earned.

Three rules carry the phase.

**Phase 5's gates are not re-litigated here.** A value proposition exists only where the
analysis established one; a differentiation step exists only where it established a competitive
advantage. Phase 6 never re-derives either — it reads whether the claim is settled. Because the
rule is not copied, it cannot drift from the original.

**What we sell is a selection, not a sentence.** The caller supplies the elements; the model
returns their keys. There is no field for a description of our product, so there is nothing to
inflate.

**A number in a customer-facing sentence has to come from the evidence.** "30% reduction" is
the most quotable thing a proposal can contain and the easiest for a model to produce from
nothing. The check is literal numeral matching against the cited claims — not entity
recognition, not a judgement about meaning.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional, Sequence

from core.models import (
    MAX_CLAIM_STATEMENT_CHARS,
    AnalysisDimension,
    ClientAnalysis,
    EvidenceNeed,
    EvidenceTiming,
    ProposalObjective,
    SelectedSolutionElement,
    StoryStep,
    StoryStepType,
    StrategyStatement,
)
from core.proposal.models import SolutionElement, StatementDraft
from core.proposal.objectives import next_step_matches
from core.research.models import Rejection, ReviewFlag

D = AnalysisDimension
STAGE = "propose_strategy"


class ProposalRejectionCode:
    """Why part of a strategy was refused. Codes, never the text that was refused."""

    #: A solution element the caller never offered.
    UNKNOWN_SOLUTION_ELEMENT = "UNKNOWN_SOLUTION_ELEMENT"
    #: A statement or step naming a dimension the analysis did not settle.
    DIMENSION_NOT_ESTABLISHED = "DIMENSION_NOT_ESTABLISHED"
    #: A value proposition where Phase 5 established none.
    VALUE_PROPOSITION_NOT_ESTABLISHED = "VALUE_PROPOSITION_NOT_ESTABLISHED"
    #: A differentiation step where Phase 5 established no competitive advantage.
    COMPETITIVE_POSITION_UNKNOWN = "COMPETITIVE_POSITION_UNKNOWN"
    #: A figure in a customer-facing sentence that no cited claim contains.
    UNSOURCED_FIGURE = "UNSOURCED_FIGURE"
    #: A key message without the minimum it has to rest on.
    KEY_MESSAGE_UNSUPPORTED = "KEY_MESSAGE_UNSUPPORTED"
    #: A statement that proposes none of the caller's solution elements.
    STATEMENT_OFFERS_NOTHING = "STATEMENT_OFFERS_NOTHING"
    #: A next step that names a different objective from the one chosen.
    NEXT_STEP_CONTRADICTS_OBJECTIVE = "NEXT_STEP_CONTRADICTS_OBJECTIVE"
    #: Text longer than the schema allows. Refused, never trimmed.
    STATEMENT_TOO_LONG = "STATEMENT_TOO_LONG"
    #: An objective the evidence does not carry.
    OBJECTIVE_OUTRUNS_EVIDENCE = "OBJECTIVE_OUTRUNS_EVIDENCE"
    #: An analysis id that does not match the analysis supplied.
    UNKNOWN_ANALYSIS = "UNKNOWN_ANALYSIS"
    #: The assembled strategy failed its own invariants.
    STRATEGY_INVALID = "STRATEGY_INVALID"


class ProposalFlagCode:
    """Worth a reader's attention; not grounds for discarding anything."""

    OBJECTIVE_OUTRUNS_EVIDENCE = "OBJECTIVE_OUTRUNS_EVIDENCE"
    COMPETITIVE_POSITION_UNKNOWN = "COMPETITIVE_POSITION_UNKNOWN"
    NO_OBJECTIONS_ANTICIPATED = "NO_OBJECTIONS_ANTICIPATED"
    UNSOURCED_FIGURE = "UNSOURCED_FIGURE"


#: Any run of digits. Deliberately crude: the point is to notice that a figure appeared, not
#: to parse it.
_FIGURE = re.compile(r"\d[\d,.]*")


def bounded(value) -> tuple[Optional[str], bool]:
    """The stripped text and whether it broke the length contract.

    Never returns a shortened string, for the same reason as everywhere else in this harness:
    cutting a sentence stores a claim nobody made.
    """
    if not isinstance(value, str):
        return None, False
    stripped = value.strip()
    if not stripped:
        return None, False
    if len(stripped) > MAX_CLAIM_STATEMENT_CHARS:
        return None, True
    return stripped, False


def figures_in(text: str) -> set[str]:
    """The numerals in a sentence, normalised so 1,200 and 1200 compare equal."""
    return {match.group(0).replace(",", "").rstrip(".") for match in _FIGURE.finditer(text)}


def unsourced_figures(
    text: str,
    dimensions: Sequence[AnalysisDimension],
    analysis: ClientAnalysis,
) -> set[str]:
    """Figures in ``text`` that appear in none of the cited claims.

    Literal matching over digit runs. It will occasionally catch a model number or a year that
    happens not to appear in the evidence, and that false positive costs a sentence rather than
    a customer — the direction this harness errs in everywhere else.
    """
    found = figures_in(text)
    if not found:
        return set()
    sourced: set[str] = set()
    for dimension in dimensions:
        claim = analysis.claim_for(dimension)
        if claim and claim.statement:
            sourced |= figures_in(claim.statement)
    return found - sourced


def established(analysis: ClientAnalysis) -> set[AnalysisDimension]:
    return {c.dimension for c in analysis.claims if c.statement and c.finding_ids}


def resolve_elements(
    refs: Iterable[str],
    elements: Sequence[SolutionElement],
) -> tuple[list[SelectedSolutionElement], list[Rejection]]:
    """Turn the model's element keys into selections carrying the caller's own wording.

    A key the caller never issued is refused: that is the whole of the guardrail, and it works
    because the wording is copied from the caller's list rather than read from the response.

    Deduplication is by ``ref``, not by text. Two elements may legitimately read alike — a
    sensor sold as a unit and the same sensor sold as a service — and collapsing them would
    lose one of them on the strength of a coincidence in wording.
    """
    by_ref = {element.ref: element for element in elements}
    selected: list[SelectedSolutionElement] = []
    seen: set[str] = set()
    rejections: list[Rejection] = []
    for ref in refs:
        element = by_ref.get(ref)
        if element is None:
            rejections.append(
                Rejection(STAGE, ProposalRejectionCode.UNKNOWN_SOLUTION_ELEMENT, str(ref))
            )
            continue
        if element.ref in seen:
            continue
        seen.add(element.ref)
        selected.append(SelectedSolutionElement(ref=element.ref, text=element.text))
    return selected, rejections


def resolve_statement(
    draft: StatementDraft,
    analysis: ClientAnalysis,
    *,
    label: str,
    elements: Sequence[SolutionElement] = (),
    required: Sequence[tuple[AnalysisDimension, ...]] = (),
    check_figures: bool = True,
) -> tuple[Optional[StrategyStatement], list[Rejection], list[ReviewFlag]]:
    """One statement, or nothing plus the reason.

    ``required`` is a list of groups; each group is satisfied by any one of its dimensions.
    ``elements`` is the caller's solution list: a statement has to offer at least one entry
    from it, resolved to the caller's own wording, or it is not proposing anything.
    """
    rejections: list[Rejection] = []
    flags: list[ReviewFlag] = []

    text, too_long = bounded(draft.text)
    if too_long:
        rejections.append(Rejection(STAGE, ProposalRejectionCode.STATEMENT_TOO_LONG, label))
        return None, rejections, flags
    if not text:
        return None, rejections, flags

    settled = established(analysis)
    dimensions = [d for d in draft.dimensions if d in settled]
    dropped = [d for d in draft.dimensions if d not in settled]
    if dropped:
        rejections.append(
            Rejection(STAGE, ProposalRejectionCode.DIMENSION_NOT_ESTABLISHED, label)
        )

    for group in required:
        if not any(dimension in dimensions for dimension in group):
            rejections.append(
                Rejection(STAGE, ProposalRejectionCode.KEY_MESSAGE_UNSUPPORTED, label)
            )
            return None, rejections, flags

    if not dimensions:
        rejections.append(
            Rejection(STAGE, ProposalRejectionCode.DIMENSION_NOT_ESTABLISHED, label)
        )
        return None, rejections, flags

    if check_figures and unsourced_figures(text, dimensions, analysis):
        # The single most quotable sentence in a proposal is not the place to round up.
        rejections.append(Rejection(STAGE, ProposalRejectionCode.UNSOURCED_FIGURE, label))
        return None, rejections, flags

    offered, element_rejections = resolve_elements(draft.solution_element_refs, elements)
    rejections.extend(element_rejections)
    if not offered:
        # Both statements this function builds exist to propose something. One that offers
        # nothing in particular is an observation, and it cannot be traced to a capability.
        rejections.append(
            Rejection(STAGE, ProposalRejectionCode.STATEMENT_OFFERS_NOTHING, label)
        )
        return None, rejections, flags

    return (
        StrategyStatement(
            text=text,
            dimensions=dimensions,
            # Refs, not wording: prose used as an identifier collapses elements that happen
            # to read alike and breaks every pointer when one is reworded.
            solution_element_refs=[element.ref for element in offered],
            missing_evidence=[m for m in draft.missing_evidence if m.strip()],
        ),
        rejections,
        flags,
    )


def resolve_step(
    step_type: StoryStepType,
    message: Optional[str],
    dimensions: Sequence[AnalysisDimension],
    missing_evidence: Sequence[str],
    analysis: ClientAnalysis,
    *,
    objective: Optional[ProposalObjective],
) -> tuple[Optional[StoryStep], list[Rejection], list[ReviewFlag]]:
    """One storyline step, with the two gates that apply to particular types."""
    rejections: list[Rejection] = []
    flags: list[ReviewFlag] = []

    text, too_long = bounded(message)
    if too_long:
        rejections.append(
            Rejection(STAGE, ProposalRejectionCode.STATEMENT_TOO_LONG, step_type.value)
        )
        return None, rejections, flags
    if not text:
        return None, rejections, flags

    settled = established(analysis)

    if step_type is StoryStepType.DIFFERENTIATION and D.COMPETITIVE_ADVANTAGE not in settled:
        # Phase 5 refuses a competitive advantage without a comparison. Writing one here would
        # be that refusal undone one phase later, where nobody is looking for it.
        rejections.append(
            Rejection(STAGE, ProposalRejectionCode.COMPETITIVE_POSITION_UNKNOWN, step_type.value)
        )
        flags.append(
            ReviewFlag(STAGE, ProposalFlagCode.COMPETITIVE_POSITION_UNKNOWN, step_type.value)
        )
        return None, rejections, flags

    if step_type is StoryStepType.NEXT_STEP and not next_step_matches(objective, text):
        rejections.append(
            Rejection(
                STAGE, ProposalRejectionCode.NEXT_STEP_CONTRADICTS_OBJECTIVE, step_type.value
            )
        )
        return None, rejections, flags

    kept = [d for d in dimensions if d in settled]
    if len(kept) != len(list(dimensions)):
        rejections.append(
            Rejection(STAGE, ProposalRejectionCode.DIMENSION_NOT_ESTABLISHED, step_type.value)
        )

    if unsourced_figures(text, kept, analysis):
        # Internal reasoning rather than a promise, so it is flagged and kept.
        flags.append(ReviewFlag(STAGE, ProposalFlagCode.UNSOURCED_FIGURE, step_type.value))

    return (
        StoryStep(
            step_type=step_type,
            message=text,
            dimensions=kept,
            missing_evidence=[m for m in missing_evidence if m.strip()],
        ),
        rejections,
        flags,
    )


def carry_forward_gaps(
    analysis: ClientAnalysis,
    classified: dict[str, EvidenceTiming],
) -> list[EvidenceNeed]:
    """Every gap the analysis recorded, timed for the proposal where anyone timed it.

    Two rules, and the second is easy to get wrong. Phase 5's gaps are carried forward whole,
    because losing an open question between phases is how a proposal comes to look better
    founded than it is. And a gap nobody classified is marked ``UNCLASSIFIED`` rather than
    promoted to the earliest slot: promoting it would state an urgency the analysis never
    claimed, and would be indistinguishable from a real judgement once written down.
    """
    needs: list[EvidenceNeed] = []
    seen: set[str] = set()

    for claim in analysis.claims:
        for gap in claim.missing_evidence:
            gap = gap.strip()
            if not gap or gap in seen:
                continue
            seen.add(gap)
            needs.append(
                EvidenceNeed(
                    need=gap,
                    timing=classified.get(gap, EvidenceTiming.UNCLASSIFIED),
                    dimension=claim.dimension,
                )
            )

    for claim in analysis.international_claims:
        for gap in claim.missing_evidence:
            gap = gap.strip()
            if not gap or gap in seen:
                continue
            seen.add(gap)
            needs.append(
                EvidenceNeed(need=gap, timing=classified.get(gap, EvidenceTiming.UNCLASSIFIED))
            )

    return needs
