# -*- coding: utf-8 -*-
"""Which objectives the evidence can carry, and what to do when it cannot.

A proposal's objective is where over-reach enters. "Submit a formal proposal" against a client
whose buyer has never been identified is not a bold plan; it is a plan addressed to nobody, and
it reads in a report exactly like a considered decision.

The gate below is deliberately narrow. It does not predict whether a deal will close, score a
likelihood, or rank objectives — it asks one question per objective: *is the thing this
objective needs to exist actually established in the analysis?* A formal proposal needs
somebody to send it to. A procurement response needs a procurement to respond to.

**Who chose matters more than what was chosen.** A person may know things this harness does
not — they were in the meeting — so a human objective that outruns the evidence is flagged and
kept. A model knows only what it cited, so its suggestion is withdrawn rather than lowered:
there is no fallback objective, because a quiet fallback is the pipeline deciding what the
proposal is for.
"""
from __future__ import annotations

from typing import Optional

from core.models import (
    AnalysisDimension,
    ClientAnalysis,
    ObjectiveSource,
    ProposalObjective,
)

D = AnalysisDimension

#: What each objective needs the analysis to have settled first.
#:
#: Most objectives require nothing: a discovery meeting is how you *find* the buyer, and
#: demanding evidence of one first would make the harness useless at the only stage where most
#: candidates actually sit. The requirements start where the commitment does.
OBJECTIVE_REQUIREMENTS: dict[ProposalObjective, tuple[tuple[AnalysisDimension, ...], ...]] = {
    ProposalObjective.DISCOVERY_MEETING: (),
    ProposalObjective.TECHNICAL_REVIEW: (),
    ProposalObjective.PARTNERSHIP_DISCUSSION: (),
    # Somebody has to host it and something has to be proved.
    ProposalObjective.POC: ((D.PROBLEM,),),
    # A pilot runs in real operation, so the operational problem has to be real and somebody
    # has to be able to authorise disruption.
    ProposalObjective.PILOT: ((D.PROBLEM,), (D.BUYER, D.DECISION_MAKER)),
    # Registration is a procurement act.
    ProposalObjective.SUPPLIER_REGISTRATION: ((D.PROCUREMENT_CONTEXT,),),
    # A proposal is sent to a person who can receive it, about a problem they have.
    ProposalObjective.FORMAL_PROPOSAL: ((D.PROBLEM,), (D.BUYER, D.DECISION_MAKER)),
    # And a procurement response needs the procurement itself on record.
    ProposalObjective.PROCUREMENT_RESPONSE: (
        (D.PROCUREMENT_CONTEXT,),
        (D.BUYER, D.DECISION_MAKER),
    ),
}


def established_dimensions(analysis: ClientAnalysis) -> set[AnalysisDimension]:
    """The dimensions this analysis actually answered.

    A claim counts when it says something *and* cites a finding. Phase 5 uses the same test;
    it is repeated here rather than imported so that ``core.proposal`` does not depend on
    ``core.analysis`` for one predicate.
    """
    return {
        claim.dimension
        for claim in analysis.claims
        if claim.statement and claim.finding_ids
    }


def unmet_requirements(
    objective: ProposalObjective,
    analysis: ClientAnalysis,
) -> list[str]:
    """Which of the objective's requirements the analysis does not meet.

    Each requirement is a group, satisfied by any one of its members: a proposal can be
    addressed to a buyer *or* to a decision maker, and insisting on both would refuse
    objectives that are perfectly well grounded.
    """
    settled = established_dimensions(analysis)
    unmet: list[str] = []
    for group in OBJECTIVE_REQUIREMENTS.get(objective, ()):
        if not any(dimension in settled for dimension in group):
            unmet.append(" or ".join(d.value for d in group))
    return unmet


def resolve_objective(
    *,
    human_objective: Optional[ProposalObjective],
    suggested: Optional[ProposalObjective],
    analysis: ClientAnalysis,
) -> tuple[Optional[ProposalObjective], Optional[ObjectiveSource], list[str]]:
    """Settle on an objective, or on none, and say what was unmet.

    Returns the objective, its source, and the unmet requirements. A human objective always
    comes back unchanged — the caller records the gap rather than the harness overruling the
    person. A suggestion that does not meet its requirements comes back as ``None``, and
    **nothing takes its place**.
    """
    if human_objective is not None:
        return human_objective, ObjectiveSource.HUMAN, unmet_requirements(human_objective, analysis)

    if suggested is None:
        return None, None, []

    unmet = unmet_requirements(suggested, analysis)
    if unmet:
        return None, None, unmet
    return suggested, ObjectiveSource.AI_SUGGESTED, []


#: Which storyline step a given objective's NEXT_STEP is allowed to describe.
#:
#: Not a template for the sentence — a check that the last step of the argument is asking for
#: the thing the strategy says it is asking for. A storyline that ends in "sign here" under a
#: DISCOVERY_MEETING objective is two strategies in one record.
def next_step_matches(objective: Optional[ProposalObjective], message: str) -> bool:
    """Whether a NEXT_STEP message contradicts the objective.

    Conservative and literal: it only catches a step that names a *different* objective from
    the closed list. Judging whether prose means the same thing as an enum is the semantic
    problem this repository has not taken on.
    """
    if objective is None:
        return True
    lowered = message.lower()
    for other in ProposalObjective:
        if other is objective:
            continue
        words = other.value.lower().split("_")
        if all(word in lowered for word in words):
            return False
    return True
