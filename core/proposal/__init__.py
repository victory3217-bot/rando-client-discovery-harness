# -*- coding: utf-8 -*-
"""Proposal strategy synthesis — the step between an analysis and a document.

``core/analysis`` answers what is true about a client. This package answers what to do about
it: what to aim for next, which of our things to offer, what the central claim is, in what
order to make it, what the customer will push back on, and what nobody has checked yet.

**A strategy, not a proposal.** Nothing here produces a slide, a page, a quotation or a price.
The output is a set of decisions structured so a later phase can render them and a person can
disagree with them.

Four rules shape the code:

* the objective has no default — ``None`` until a person chooses or a model suggests one the
  evidence carries, and a withdrawn suggestion is replaced by nothing;
* what we sell is selected from the caller's list, never written, so a proposal cannot acquire
  a capability we do not have;
* Phase 5's gates are read, not re-derived: no value proposition where the analysis
  established none, no differentiation where it established no advantage;
* an objection and its answer are one object, because two lists paired by position produce
  wrong pairs rather than missing ones.

Pure, like the rest of ``core``. The LLM arrives injected and every call goes through
:mod:`core.transmission`.
"""
from core.proposal.models import (
    ObjectionDraft,
    ProposalOutcome,
    SolutionElement,
    StatementDraft,
)
from core.proposal.objections import (
    flag_if_silent,
    resolve_objection,
    split_by_basis,
)
from core.proposal.objectives import (
    OBJECTIVE_REQUIREMENTS,
    established_dimensions,
    next_step_matches,
    resolve_objective,
    unmet_requirements,
)
from core.proposal.output_schemas import (
    ALL_OUTPUT_SCHEMAS,
    PROPOSAL_OBJECTIONS,
    PROPOSAL_STRATEGY,
)
from core.proposal.pipeline import (
    KEY_MESSAGE_REQUIREMENTS,
    VALUE_PROPOSITION_REQUIREMENTS,
    persist,
    run_proposal_strategy,
)
from core.proposal.policy import (
    DEFAULT_PROPOSAL_POLICY,
    ProposalPolicy,
    ProposalPromptSet,
)
from core.proposal.strategy import (
    ProposalFlagCode,
    ProposalRejectionCode,
    carry_forward_gaps,
    established,
    figures_in,
    resolve_elements,
    resolve_statement,
    resolve_step,
    unsourced_figures,
)

__all__ = [
    "ALL_OUTPUT_SCHEMAS",
    "DEFAULT_PROPOSAL_POLICY",
    "KEY_MESSAGE_REQUIREMENTS",
    "OBJECTIVE_REQUIREMENTS",
    "PROPOSAL_OBJECTIONS",
    "PROPOSAL_STRATEGY",
    "VALUE_PROPOSITION_REQUIREMENTS",
    "ObjectionDraft",
    "ProposalFlagCode",
    "ProposalOutcome",
    "ProposalPolicy",
    "ProposalPromptSet",
    "ProposalRejectionCode",
    "SolutionElement",
    "StatementDraft",
    "carry_forward_gaps",
    "established",
    "established_dimensions",
    "figures_in",
    "flag_if_silent",
    "next_step_matches",
    "persist",
    "resolve_elements",
    "resolve_objection",
    "resolve_objective",
    "resolve_statement",
    "resolve_step",
    "run_proposal_strategy",
    "split_by_basis",
    "unmet_requirements",
    "unsourced_figures",
]
