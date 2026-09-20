# -*- coding: utf-8 -*-
"""One ClientAnalysis in, one ProposalStrategy out.

Two calls: the strategy, then the objections. The second is separate because anticipating
pushback needs a different stance from making a case, and asking for both in one response
produces objections that conveniently answer themselves.

Nothing here reads a priority band, writes one, or ranks anything. Nothing predicts whether a
deal will close. The strategy is a set of decisions for a person to argue with, and a
likelihood attached to it would be read as a forecast the evidence cannot support.
"""
from __future__ import annotations

from typing import Optional, Sequence

from core.evidence import check_proposal_strategy
from core.models import (
    AnalysisDimension,
    ClientAnalysis,
    EvidenceTiming,
    ProposalObjective,
    ProposalStatus,
    ProposalStrategy,
    Project,
    StoryStepType,
)
from core.proposal.models import (
    ObjectionDraft,
    ProposalOutcome,
    SolutionElement,
    StatementDraft,
)
from core.proposal.objections import flag_if_silent, resolve_objection
from core.proposal.objectives import resolve_objective, unmet_requirements
from core.proposal.output_schemas import PROPOSAL_OBJECTIONS, PROPOSAL_STRATEGY
from core.proposal.policy import DEFAULT_PROPOSAL_POLICY, ProposalPolicy, ProposalPromptSet
from core.proposal.strategy import (
    STAGE,
    ProposalFlagCode,
    ProposalRejectionCode,
    carry_forward_gaps,
    established,
    resolve_elements,
    resolve_statement,
    resolve_step,
)
from core.research.models import Rejection, ReviewFlag
from core.transmission import send

D = AnalysisDimension

#: What a key message has to rest on. Each group is satisfied by any one of its members.
#:
#: A problem to address, something of ours to address it with, and a reason it is worth doing.
#: Without the first it is addressed to nobody; without the third it is a description.
KEY_MESSAGE_REQUIREMENTS: tuple[tuple[AnalysisDimension, ...], ...] = (
    (D.PROBLEM,),
    (D.VALUE_PROPOSITION, D.VALUE_DRIVER),
)

#: A value proposition here is a rewording of one Phase 5 established, so it has to cite it.
VALUE_PROPOSITION_REQUIREMENTS: tuple[tuple[AnalysisDimension, ...], ...] = (
    (D.PROBLEM,),
    (D.VALUE_PROPOSITION,),
)


def run_proposal_strategy(
    *,
    project: Project,
    analysis: ClientAnalysis,
    solution_elements: Sequence[SolutionElement],
    llm,
    prompts: ProposalPromptSet,
    objective: Optional[ProposalObjective] = None,
    policy: ProposalPolicy = DEFAULT_PROPOSAL_POLICY,
) -> ProposalOutcome:
    """Draft a strategy for one analysed client.

    ``objective`` is the caller's. Supplying it records ``HUMAN`` and the harness does not
    overrule it, however far ahead of the evidence it is — a person may have been in the
    meeting. Leaving it out lets the model suggest one, and a suggestion the evidence does not
    carry is withdrawn: no objective, and none substituted.
    """
    outcome = ProposalOutcome()

    if not analysis.analysis_id:
        outcome.rejections.append(Rejection(STAGE, ProposalRejectionCode.UNKNOWN_ANALYSIS))
        return outcome

    settled = established(analysis)
    result, record = send(
        llm,
        stage="propose_strategy",
        prompt=prompts.synthesize_strategy,
        schema=PROPOSAL_STRATEGY,
        items=_strategy_items(analysis, solution_elements, objective, settled),
        output_lang=project.output_lang,
    )
    outcome.transmissions.append(record)

    # -- the objective ------------------------------------------------------
    suggested = _enum(result.get("suggested_objective"), ProposalObjective)
    chosen, source, unmet = resolve_objective(
        human_objective=objective, suggested=suggested, analysis=analysis
    )
    if unmet:
        if chosen is not None:
            # A person's decision stands. The gap is recorded beside it, not instead of it.
            outcome.review_flags.append(
                ReviewFlag(STAGE, ProposalFlagCode.OBJECTIVE_OUTRUNS_EVIDENCE, ",".join(unmet))
            )
        else:
            outcome.rejections.append(
                Rejection(
                    STAGE, ProposalRejectionCode.OBJECTIVE_OUTRUNS_EVIDENCE, ",".join(unmet)
                )
            )
            if suggested is not None:
                outcome.withdrawn_objectives.append(suggested)

    # -- what is being offered ---------------------------------------------
    refs = [r for r in (result.get("solution_element_refs") or []) if isinstance(r, str)]
    selected, element_rejections = resolve_elements(refs, solution_elements)
    outcome.rejections.extend(element_rejections)

    # -- the two statements -------------------------------------------------
    value_proposition = None
    if D.VALUE_PROPOSITION in settled:
        value_proposition, rejections, flags = resolve_statement(
            _statement_draft(result.get("value_proposition")),
            analysis,
            label="value_proposition",
            elements=solution_elements,
            required=VALUE_PROPOSITION_REQUIREMENTS,
        )
        outcome.rejections.extend(rejections)
        outcome.review_flags.extend(flags)
    elif result.get("value_proposition"):
        # Phase 5 refused to establish one. Writing it here would undo that a phase later.
        outcome.rejections.append(
            Rejection(STAGE, ProposalRejectionCode.VALUE_PROPOSITION_NOT_ESTABLISHED)
        )

    key_message, rejections, flags = resolve_statement(
        _statement_draft(result.get("key_message")),
        analysis,
        label="key_message",
        elements=solution_elements,
        required=KEY_MESSAGE_REQUIREMENTS,
    )
    outcome.rejections.extend(rejections)
    outcome.review_flags.extend(flags)
    # -- the argument --------------------------------------------------------
    storyline = []
    seen_steps: set[StoryStepType] = set()
    for raw in (result.get("storyline") or [])[: policy.max_storyline_steps]:
        if not isinstance(raw, dict):
            continue
        step_type = _enum(raw.get("step_type"), StoryStepType)
        if step_type is None or step_type in seen_steps:
            continue
        step, step_rejections, step_flags = resolve_step(
            step_type,
            raw.get("message"),
            _dimensions(raw.get("dimensions")),
            [m for m in (raw.get("missing_evidence") or []) if isinstance(m, str)],
            analysis,
            objective=chosen,
        )
        outcome.rejections.extend(step_rejections)
        outcome.review_flags.extend(step_flags)
        if step is not None:
            seen_steps.add(step_type)
            storyline.append(step)

    # -- gaps, timed ----------------------------------------------------------
    classified = {}
    for raw in result.get("evidence_timing") or []:
        if not isinstance(raw, dict):
            continue
        need = (raw.get("need") or "").strip()
        timing = _enum(raw.get("timing"), EvidenceTiming)
        if need and timing is not None:
            classified[need] = timing
    evidence_needs = carry_forward_gaps(analysis, classified)

    if D.VALUE_PROPOSITION not in settled:
        evidence_needs.insert(
            0,
            _need("a value proposition the analysis can support", D.VALUE_PROPOSITION),
        )
    if D.COMPETITIVE_ADVANTAGE not in settled:
        outcome.review_flags.append(
            ReviewFlag(STAGE, ProposalFlagCode.COMPETITIVE_POSITION_UNKNOWN)
        )
        evidence_needs.insert(
            0,
            _need("a comparison that establishes an advantage", D.COMPETITIVE_ADVANTAGE),
        )

    # -- objections ------------------------------------------------------------
    objections = _objections(
        analysis, llm=llm, prompts=prompts, project=project, policy=policy, outcome=outcome
    )
    outcome.review_flags.extend(flag_if_silent(objections))

    strategy = ProposalStrategy(
        project_id=project.project_id,
        client_id=analysis.client_id,
        client_name=analysis.client_name,
        country=analysis.country,
        analysis_id=analysis.analysis_id,
        objective=chosen,
        objective_source=source,
        objective_detail=_text(result.get("objective_detail")),
        selected_solution_elements=selected,
        proposed_solution=_assemble(selected),
        value_proposition=value_proposition,
        key_message=key_message,
        storyline=storyline,
        objections=objections,
        evidence_needs=evidence_needs,
        # A strategy is drafted once somebody has said what it is for. A model's suggestion is
        # not somebody.
        status=(
            ProposalStatus.STRATEGY_DRAFTED
            if chosen is not None
            else ProposalStatus.NOT_STARTED
        ),
        lang=project.output_lang,
    )

    violations = check_proposal_strategy(strategy, analysis)
    if violations:
        outcome.rejections.append(
            Rejection(STAGE, ProposalRejectionCode.STRATEGY_INVALID, analysis.client_id)
        )
        return outcome

    outcome.strategies.append(strategy)
    return outcome


def _objections(analysis, *, llm, prompts, project, policy, outcome) -> list:
    result, record = send(
        llm,
        stage="anticipate_objections",
        prompt=prompts.anticipate_objections,
        schema=PROPOSAL_OBJECTIONS,
        items=_objection_items(analysis),
        output_lang=project.output_lang,
    )
    outcome.transmissions.append(record)

    objections = []
    for raw in (result.get("objections") or [])[: policy.max_objections]:
        if not isinstance(raw, dict):
            continue
        draft = ObjectionDraft(
            objection=raw.get("objection"),
            basis=raw.get("basis"),
            dimensions=_dimensions(raw.get("dimensions")),
            response=raw.get("response"),
            response_dimensions=_dimensions(raw.get("response_dimensions")),
            missing_evidence=[
                m for m in (raw.get("missing_evidence") or []) if isinstance(m, str)
            ],
        )
        objection, rejections, flags = resolve_objection(draft, analysis)
        outcome.rejections.extend(rejections)
        outcome.review_flags.extend(flags)
        if objection is not None:
            objections.append(objection)
    return objections


def _strategy_items(analysis, elements, objective, settled) -> list[str]:
    """Established claims, what we can offer, and the objective if one was given.

    Only settled claims are sent. An unanswered dimension has nothing to contribute to an
    argument, and including it invites the model to fill it in here instead.
    """
    items = [
        f"[CLIENT] {analysis.client_name}",
        f"[COUNTRY] {analysis.country}",
        f"[INDUSTRY] {analysis.industry}",
    ]
    if objective is not None:
        items.append(f"[OBJECTIVE ALREADY CHOSEN] {objective.value}")
    items += [f"[{element.ref}] {element.text}" for element in elements]
    items += [
        f"[{claim.dimension.value}] ({claim.evidence_type.value}/{claim.confidence.value}) "
        f"{claim.statement}"
        for claim in analysis.claims
        if claim.dimension in settled
    ]
    items += [f"[GAP] {gap}" for gap in analysis.missing_evidence]
    return items


def _objection_items(analysis) -> list[str]:
    items = [f"[CLIENT] {analysis.client_name}"]
    items += [
        f"[{claim.dimension.value}] {claim.statement}"
        for claim in analysis.claims
        if claim.statement and claim.finding_ids
    ]
    items += [f"[GAP] {gap}" for gap in analysis.missing_evidence]
    return items


def _assemble(selected: Sequence) -> Optional[str]:
    """What is being proposed, in the caller's own words.

    Assembled from ``text`` and joined, never rewritten. A model that may rephrase what we sell
    may also extend it, and the join is the whole of the composition this phase performs.
    """
    return " / ".join(element.text for element in selected) if selected else None


def _need(text: str, dimension: AnalysisDimension):
    from core.models import EvidenceNeed

    return EvidenceNeed(
        need=text, timing=EvidenceTiming.BEFORE_PROPOSAL, dimension=dimension
    )


def _statement_draft(raw) -> StatementDraft:
    if not isinstance(raw, dict):
        return StatementDraft()
    return StatementDraft(
        text=raw.get("text"),
        dimensions=_dimensions(raw.get("dimensions")),
        solution_element_refs=[
            r for r in (raw.get("solution_element_refs") or []) if isinstance(r, str)
        ],
        missing_evidence=[m for m in (raw.get("missing_evidence") or []) if isinstance(m, str)],
    )


def _dimensions(values) -> list[AnalysisDimension]:
    out: list[AnalysisDimension] = []
    for value in values or []:
        dimension = _enum(value, AnalysisDimension)
        if dimension is not None and dimension not in out:
            out.append(dimension)
    return out


def _text(value) -> Optional[str]:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _enum(value, enum_cls):
    try:
        return enum_cls(value)
    except (ValueError, TypeError):
        return None


def persist(outcome: ProposalOutcome, storage) -> None:
    """Hand the strategies to storage. Drafts and withdrawn objectives are never offered."""
    for strategy in outcome.strategies:
        storage.save_proposal_strategy(strategy)
