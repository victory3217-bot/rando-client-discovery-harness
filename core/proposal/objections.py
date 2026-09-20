# -*- coding: utf-8 -*-
"""What the customer may push back on, kept apart from what they actually said.

An anticipated objection is a useful thing to prepare for. Repeated as though the customer had
raised it, it becomes a fact about a conversation that never happened — and a proposal built
around answering it is answering nobody.

So the basis is a value on the record rather than a note in the prose, an evidence-backed
objection has to cite a settled claim, and nothing promotes an anticipation into evidence.

**What this does not check.** A cited dimension proves the claim exists, not that the customer
raised *this* objection on the strength of it. Judging that is the semantic-relevance problem
recorded in ``docs/development-guide.md``; no verifier, embedding or entity recogniser is
introduced here to paper over it.
"""
from __future__ import annotations

from typing import Optional, Sequence

from core.models import (
    AnalysisDimension,
    ClientAnalysis,
    ObjectionBasis,
    ProposalObjection,
)
from core.proposal.models import ObjectionDraft
from core.proposal.strategy import (
    STAGE,
    ProposalFlagCode,
    ProposalRejectionCode,
    bounded,
    established,
)
from core.research.models import Rejection, ReviewFlag


def resolve_objection(
    draft: ObjectionDraft,
    analysis: ClientAnalysis,
) -> tuple[Optional[ProposalObjection], list[Rejection], list[ReviewFlag]]:
    """One objection and its answer, as a single object.

    An evidence-backed objection whose citations do not hold is not discarded — it is
    **demoted** to anticipated. The concern may well be a real one to prepare for; what it has
    lost is the claim that the customer voiced it.
    """
    rejections: list[Rejection] = []
    flags: list[ReviewFlag] = []

    text, too_long = bounded(draft.objection)
    if too_long:
        rejections.append(Rejection(STAGE, ProposalRejectionCode.STATEMENT_TOO_LONG, "objection"))
        return None, rejections, flags
    if not text:
        return None, rejections, flags

    settled = established(analysis)
    dimensions = [d for d in draft.dimensions if d in settled]
    response_dimensions = [d for d in draft.response_dimensions if d in settled]

    if len(dimensions) != len(list(draft.dimensions)) or len(response_dimensions) != len(
        list(draft.response_dimensions)
    ):
        rejections.append(
            Rejection(STAGE, ProposalRejectionCode.DIMENSION_NOT_ESTABLISHED, "objection")
        )

    basis = _basis(draft.basis)
    if basis is ObjectionBasis.EVIDENCE_BACKED and not dimensions:
        basis = ObjectionBasis.ANTICIPATED

    response, response_too_long = bounded(draft.response)
    if response_too_long:
        rejections.append(Rejection(STAGE, ProposalRejectionCode.STATEMENT_TOO_LONG, "response"))
        response = None

    missing = [m.strip() for m in draft.missing_evidence if m and m.strip()]
    if response and not response_dimensions and not missing:
        # An answer resting on nothing, admitting nothing. The gap is recorded rather than the
        # answer deleted: the approach may be right and the evidence simply not gathered.
        missing = ["evidence that this response holds for this customer"]

    return (
        ProposalObjection(
            objection=text,
            basis=basis,
            dimensions=dimensions,
            response=response,
            response_dimensions=response_dimensions,
            missing_evidence=missing,
        ),
        rejections,
        flags,
    )


def _basis(value) -> ObjectionBasis:
    """Anything unrecognised is an anticipation.

    The safe direction: mislabelling a real objection as expected costs some emphasis;
    mislabelling an expectation as evidence puts words in the customer's mouth.
    """
    try:
        return ObjectionBasis(value)
    except (ValueError, TypeError):
        return ObjectionBasis.ANTICIPATED


def split_by_basis(
    objections: Sequence[ProposalObjection],
) -> tuple[list[ProposalObjection], list[ProposalObjection]]:
    """The two kinds, separated. Useful to a renderer, and a reminder that they are two."""
    backed = [o for o in objections if o.basis is ObjectionBasis.EVIDENCE_BACKED]
    anticipated = [o for o in objections if o.basis is ObjectionBasis.ANTICIPATED]
    return backed, anticipated


def flag_if_silent(objections: Sequence[ProposalObjection]) -> list[ReviewFlag]:
    """Note an empty objection list without inventing one to fill it.

    A minimum count would be met by fabrication, which is worse than the silence.
    """
    if objections:
        return []
    return [ReviewFlag(STAGE, ProposalFlagCode.NO_OBJECTIONS_ANTICIPATED)]
