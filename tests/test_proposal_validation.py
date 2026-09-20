# -*- coding: utf-8 -*-
"""What proposal strategy refuses to keep.

The failures here are the ones that survive into a document and get read aloud in a meeting: a
capability we do not have, a percentage nobody measured, an objection attributed to a customer
who never raised it, an objective that assumes a buyer nobody has found.

Every organization in these fixtures is invented.
"""
from __future__ import annotations

import pytest

from core import evidence
from core.models import (
    MAX_CLAIM_STATEMENT_CHARS,
    AnalysisClaim,
    AnalysisDimension,
    ClientAnalysis,
    Confidence,
    EvidenceNeed,
    EvidenceTiming,
    EvidenceType,
    ObjectionBasis,
    ObjectiveSource,
    ProposalObjection,
    ProposalObjective,
    ProposalStatus,
    ProposalStrategy,
    SelectedSolutionElement,
    StoryStep,
    StoryStepType,
    StrategyStatement,
    aggregate_finding_ids,
    aggregate_missing_evidence,
)
from core.proposal import (
    OBJECTIVE_REQUIREMENTS,
    ProposalRejectionCode,
    SolutionElement,
    StatementDraft,
    carry_forward_gaps,
    figures_in,
    next_step_matches,
    resolve_elements,
    resolve_objection,
    resolve_objective,
    resolve_statement,
    resolve_step,
    split_by_basis,
    unmet_requirements,
    unsourced_figures,
)
from core.proposal.models import ObjectionDraft
from core.proposal.pipeline import KEY_MESSAGE_REQUIREMENTS

D = AnalysisDimension
PROJECT = "prj_proposal"
ALPHA = "Fictional Alpha Water Systems"


def _settled(dimension, statement="확인된 내용", finding_id="f1") -> AnalysisClaim:
    return AnalysisClaim(
        dimension=dimension,
        statement=statement,
        finding_ids=[finding_id],
        evidence_type=EvidenceType.FACT,
        confidence=Confidence.MEDIUM,
        framework_basis=["MN03"],
    )


def _analysis(*settled_dimensions, statements=None) -> ClientAnalysis:
    statements = statements or {}
    claims = []
    for dimension in AnalysisDimension:
        if dimension in settled_dimensions:
            claims.append(_settled(dimension, statements.get(dimension, "확인된 내용")))
        else:
            claims.append(
                AnalysisClaim(dimension=dimension, missing_evidence=[f"gap for {dimension.value}"])
            )
    return ClientAnalysis(
        project_id=PROJECT,
        client_id="cli_1",
        client_name=ALPHA,
        country="VN",
        industry="water",
        our_solution="a sensor",
        claims=claims,
        analysis_id="cla_1",
        finding_ids=aggregate_finding_ids(claims),
        missing_evidence=aggregate_missing_evidence(claims),
    )


# -- the objective ------------------------------------------------------------

def test_the_objective_has_no_default() -> None:
    """A quiet fallback is the harness deciding what a proposal is for."""
    strategy = ProposalStrategy(
        project_id=PROJECT, client_id="cli_1", client_name=ALPHA, country="VN"
    )
    assert strategy.objective is None
    assert strategy.objective_source is None


def test_poc_and_pilot_are_different_objectives() -> None:
    """A proof runs at our cost; a pilot runs in their operation and needs an authoriser."""
    assert ProposalObjective.POC is not ProposalObjective.PILOT
    assert OBJECTIVE_REQUIREMENTS[ProposalObjective.PILOT] != OBJECTIVE_REQUIREMENTS[
        ProposalObjective.POC
    ]


def test_an_early_objective_needs_nothing() -> None:
    """A discovery meeting is how you find the buyer.

    Requiring evidence of one first would make the harness useless at the stage where most
    candidates actually sit.
    """
    analysis = _analysis()
    assert unmet_requirements(ProposalObjective.DISCOVERY_MEETING, analysis) == []


def test_a_formal_proposal_needs_somebody_to_send_it_to() -> None:
    analysis = _analysis(D.PROBLEM)
    unmet = unmet_requirements(ProposalObjective.FORMAL_PROPOSAL, analysis)
    assert unmet == ["BUYER or DECISION_MAKER"]


def test_either_member_of_a_requirement_group_satisfies_it() -> None:
    """A proposal can be addressed to a buyer or to a decision maker."""
    assert unmet_requirements(ProposalObjective.FORMAL_PROPOSAL, _analysis(D.PROBLEM, D.BUYER)) == []
    assert unmet_requirements(
        ProposalObjective.FORMAL_PROPOSAL, _analysis(D.PROBLEM, D.DECISION_MAKER)
    ) == []


def test_an_ai_objective_that_outruns_the_evidence_is_withdrawn_not_lowered() -> None:
    """And nothing takes its place."""
    objective, source, unmet = resolve_objective(
        human_objective=None,
        suggested=ProposalObjective.FORMAL_PROPOSAL,
        analysis=_analysis(D.PROBLEM),
    )
    assert objective is None
    assert source is None
    assert unmet
    assert objective is not ProposalObjective.DISCOVERY_MEETING, "no safe-looking substitute"


def test_a_human_objective_stands_even_when_it_outruns_the_evidence() -> None:
    """They may have been in the meeting. The gap is recorded beside the decision."""
    objective, source, unmet = resolve_objective(
        human_objective=ProposalObjective.FORMAL_PROPOSAL,
        suggested=None,
        analysis=_analysis(D.PROBLEM),
    )
    assert objective is ProposalObjective.FORMAL_PROPOSAL
    assert source is ObjectiveSource.HUMAN
    assert unmet, "and the harness says so rather than silently agreeing"


def test_an_ai_suggestion_the_evidence_carries_is_kept() -> None:
    objective, source, unmet = resolve_objective(
        human_objective=None,
        suggested=ProposalObjective.TECHNICAL_REVIEW,
        analysis=_analysis(D.PROBLEM),
    )
    assert objective is ProposalObjective.TECHNICAL_REVIEW
    assert source is ObjectiveSource.AI_SUGGESTED
    assert unmet == []


def test_a_next_step_cannot_ask_for_a_different_objective() -> None:
    assert next_step_matches(ProposalObjective.DISCOVERY_MEETING, "request a discovery meeting")
    assert not next_step_matches(
        ProposalObjective.DISCOVERY_MEETING, "proceed to a formal proposal this quarter"
    )
    assert next_step_matches(None, "anything at all")


# -- what we are offering -------------------------------------------------------

ELEMENTS = [
    SolutionElement(ref="S1", text="a single-module multi-parameter sensor"),
    SolutionElement(ref="S2", text="remote data access"),
]


def test_a_selection_keeps_both_the_ref_and_the_callers_text() -> None:
    """One is what the record points at; the other is what a reader is shown."""
    selected, rejections = resolve_elements(["S1"], ELEMENTS)
    assert not rejections
    assert [(e.ref, e.text) for e in selected] == [
        ("S1", "a single-module multi-parameter sensor")
    ]


def test_an_unknown_element_is_refused() -> None:
    """The guardrail, in one case: a key the caller never issued buys nothing."""
    selected, rejections = resolve_elements(["S1", "S9"], ELEMENTS)
    assert [e.ref for e in selected] == ["S1"]
    assert any(
        r.code == ProposalRejectionCode.UNKNOWN_SOLUTION_ELEMENT for r in rejections
    )


def test_the_wording_comes_from_the_caller_not_the_model() -> None:
    """A model that may rephrase what we sell may also extend it."""
    selected, _ = resolve_elements(["S2"], ELEMENTS)
    assert selected[0].text == "remote data access"


def test_two_elements_that_read_alike_stay_two_elements() -> None:
    """Deduplication is by ref, not by wording.

    A sensor sold as a unit and the same sensor sold as a service can carry identical
    descriptions and are still different things to propose. Collapsing them on a coincidence
    of phrasing would lose one.
    """
    twins = [
        SolutionElement(ref="S1", text="continuous monitoring"),
        SolutionElement(ref="S2", text="continuous monitoring"),
    ]
    selected, rejections = resolve_elements(["S1", "S2"], twins)
    assert [e.ref for e in selected] == ["S1", "S2"]
    assert not rejections


def test_the_same_ref_twice_is_one_selection() -> None:
    selected, _ = resolve_elements(["S1", "S1"], ELEMENTS)
    assert [e.ref for e in selected] == ["S1"]


def test_there_is_no_field_for_describing_our_product() -> None:
    """The structural half of the guardrail: nowhere to type an invented capability."""
    from core.proposal.output_schemas import PROPOSAL_STRATEGY

    properties = PROPOSAL_STRATEGY["properties"]
    assert "solution_element_refs" in properties
    for invented in ("proposed_solution", "capability", "our_solution", "features", "support"):
        assert invented not in properties


# -- statements -----------------------------------------------------------------

def test_a_statement_needs_a_dimension() -> None:
    analysis = _analysis(D.PROBLEM)
    statement, rejections, _ = resolve_statement(
        StatementDraft(text="우리는 좋은 제품을 가지고 있다"), analysis, label="key_message"
    )
    assert statement is None
    assert any(
        r.code == ProposalRejectionCode.DIMENSION_NOT_ESTABLISHED for r in rejections
    )


def test_a_statement_citing_an_unsettled_dimension_loses_that_citation() -> None:
    analysis = _analysis(D.PROBLEM)
    statement, rejections, _ = resolve_statement(
        StatementDraft(
            text="문제를 해결한다", dimensions=[D.PROBLEM, D.KBF], solution_element_refs=["S1"]
        ),
        analysis,
        label="key_message",
        elements=ELEMENTS,
    )
    assert statement is not None
    assert statement.dimensions == [D.PROBLEM]
    assert any(
        r.code == ProposalRejectionCode.DIMENSION_NOT_ESTABLISHED for r in rejections
    )


def test_a_statement_that_offers_nothing_is_refused() -> None:
    """Both statements exist to propose something.

    One that names no element of what we sell cannot be traced back to a capability, and
    reads as an observation rather than an offer.
    """
    analysis = _analysis(D.PROBLEM)
    statement, rejections, _ = resolve_statement(
        StatementDraft(text="측정이 어렵다", dimensions=[D.PROBLEM]),
        analysis,
        label="key_message",
        elements=ELEMENTS,
    )
    assert statement is None
    assert any(
        r.code == ProposalRejectionCode.STATEMENT_OFFERS_NOTHING for r in rejections
    )


def test_a_statement_offering_something_outside_the_whitelist_is_refused() -> None:
    analysis = _analysis(D.PROBLEM)
    statement, rejections, _ = resolve_statement(
        StatementDraft(
            text="문제를 해결한다", dimensions=[D.PROBLEM], solution_element_refs=["S_INVENTED"]
        ),
        analysis,
        label="key_message",
        elements=ELEMENTS,
    )
    assert statement is None
    assert any(
        r.code == ProposalRejectionCode.UNKNOWN_SOLUTION_ELEMENT for r in rejections
    )


def test_a_statement_stores_refs_not_wording() -> None:
    """The chain runs statement → selected element → the caller's capability list.

    Prose used as an identifier would collapse elements that read alike, and rewording an
    offer would silently break every statement pointing at it. It does not make the sentence
    accurate either way — it makes what the sentence offers traceable.
    """
    analysis = _analysis(D.PROBLEM)
    statement, _, _ = resolve_statement(
        StatementDraft(
            text="문제를 해결한다", dimensions=[D.PROBLEM], solution_element_refs=["S2"]
        ),
        analysis,
        label="key_message",
        elements=ELEMENTS,
    )
    assert statement.solution_element_refs == ["S2"]
    assert "remote data access" not in statement.solution_element_refs


def test_a_key_message_needs_a_problem_and_a_reason() -> None:
    analysis = _analysis(D.PROBLEM)
    statement, rejections, _ = resolve_statement(
        StatementDraft(text="문제를 해결한다", dimensions=[D.PROBLEM]),
        analysis,
        label="key_message",
        required=KEY_MESSAGE_REQUIREMENTS,
    )
    assert statement is None, "a problem alone is not a reason to act"
    assert any(r.code == ProposalRejectionCode.KEY_MESSAGE_UNSUPPORTED for r in rejections)


def test_a_key_message_with_its_minimum_is_kept() -> None:
    analysis = _analysis(D.PROBLEM, D.VALUE_DRIVER)
    statement, rejections, _ = resolve_statement(
        StatementDraft(
            text="문제를 해결한다",
            dimensions=[D.PROBLEM, D.VALUE_DRIVER],
            solution_element_refs=["S1"],
        ),
        analysis,
        label="key_message",
        elements=ELEMENTS,
        required=KEY_MESSAGE_REQUIREMENTS,
    )
    assert statement is not None
    assert not rejections


def test_a_long_statement_is_refused_not_truncated() -> None:
    analysis = _analysis(D.PROBLEM)
    statement, rejections, _ = resolve_statement(
        StatementDraft(text="가" * (MAX_CLAIM_STATEMENT_CHARS + 1), dimensions=[D.PROBLEM]),
        analysis,
        label="key_message",
    )
    assert statement is None
    assert any(r.code == ProposalRejectionCode.STATEMENT_TOO_LONG for r in rejections)


# -- figures ----------------------------------------------------------------------

def test_figures_are_found_and_normalised() -> None:
    assert figures_in("1,200 units at 30%") == {"1200", "30"}
    assert figures_in("no numbers here") == set()


def test_an_invented_figure_kills_the_key_message() -> None:
    """"30% reduction" is the most quotable thing a proposal can contain.

    It is also the easiest thing for a model to produce from nothing, and once it is in a
    slide nobody asks which document it came from.
    """
    analysis = _analysis(D.PROBLEM, D.VALUE_DRIVER)
    statement, rejections, _ = resolve_statement(
        StatementDraft(text="측정 비용을 30% 절감한다", dimensions=[D.PROBLEM, D.VALUE_DRIVER]),
        analysis,
        label="key_message",
        required=KEY_MESSAGE_REQUIREMENTS,
    )
    assert statement is None
    assert any(r.code == ProposalRejectionCode.UNSOURCED_FIGURE for r in rejections)


def test_a_figure_the_evidence_contains_is_allowed() -> None:
    analysis = _analysis(
        D.PROBLEM, D.VALUE_DRIVER, statements={D.PROBLEM: "측정 주기를 주 1회에서 늘려야 한다"}
    )
    statement, rejections, _ = resolve_statement(
        StatementDraft(
            text="주 1회 측정을 상시 계측으로 대체한다",
            dimensions=[D.PROBLEM, D.VALUE_DRIVER],
            solution_element_refs=["S1"],
        ),
        analysis,
        label="key_message",
        elements=ELEMENTS,
        required=KEY_MESSAGE_REQUIREMENTS,
    )
    assert statement is not None


def test_unsourced_figures_reports_only_what_is_missing() -> None:
    analysis = _analysis(D.PROBLEM, statements={D.PROBLEM: "주 1회 측정"})
    assert unsourced_figures("주 1회를 30% 개선", [D.PROBLEM], analysis) == {"30"}


# -- storyline ----------------------------------------------------------------------

def test_there_are_six_step_types() -> None:
    assert len(list(StoryStepType)) == 6
    assert "IMPLEMENTATION" not in {s.value for s in StoryStepType}


def test_a_differentiation_step_needs_an_established_advantage() -> None:
    """Phase 5 refuses an advantage without a comparison.

    Writing one here would be that refusal undone a phase later, where nobody is looking
    for it.
    """
    analysis = _analysis(D.PROBLEM)
    step, rejections, flags = resolve_step(
        StoryStepType.DIFFERENTIATION,
        "우리가 앞선다",
        [D.PROBLEM],
        [],
        analysis,
        objective=None,
    )
    assert step is None
    assert any(
        r.code == ProposalRejectionCode.COMPETITIVE_POSITION_UNKNOWN for r in rejections
    )
    assert flags


def test_a_differentiation_step_is_allowed_where_phase_five_established_one() -> None:
    analysis = _analysis(D.PROBLEM, D.COMPETITIVE_ADVANTAGE)
    step, rejections, _ = resolve_step(
        StoryStepType.DIFFERENTIATION,
        "비교 기준에서 우리가 앞선다",
        [D.COMPETITIVE_ADVANTAGE],
        [],
        analysis,
        objective=None,
    )
    assert step is not None
    assert not rejections


def test_a_next_step_contradicting_the_objective_is_refused() -> None:
    analysis = _analysis(D.PROBLEM)
    step, rejections, _ = resolve_step(
        StoryStepType.NEXT_STEP,
        "이번 분기에 formal proposal 을 제출한다",
        [D.PROBLEM],
        [],
        analysis,
        objective=ProposalObjective.DISCOVERY_MEETING,
    )
    assert step is None
    assert any(
        r.code == ProposalRejectionCode.NEXT_STEP_CONTRADICTS_OBJECTIVE for r in rejections
    )


def test_a_figure_in_a_storyline_step_is_flagged_not_refused() -> None:
    """Internal reasoning rather than a promise to the customer."""
    analysis = _analysis(D.PROBLEM)
    step, rejections, flags = resolve_step(
        StoryStepType.VALUE, "비용이 40% 줄어든다", [D.PROBLEM], [], analysis, objective=None
    )
    assert step is not None
    assert flags and not rejections


# -- objections -----------------------------------------------------------------------

def test_an_objection_and_its_answer_are_one_object() -> None:
    """Two lists paired by position produce wrong pairs, not missing ones."""
    import dataclasses

    names = {f.name for f in dataclasses.fields(ProposalObjection)}
    assert {"objection", "response"} <= names
    strategy_names = {f.name for f in dataclasses.fields(ProposalStrategy)}
    assert "expected_objection" not in strategy_names
    assert "response_logic" not in strategy_names


def test_an_evidence_backed_objection_without_a_citation_is_demoted() -> None:
    """Not discarded: the concern may be real. What it loses is the customer's voice."""
    analysis = _analysis(D.PROBLEM)
    objection, _, _ = resolve_objection(
        ObjectionDraft(objection="너무 비싸다", basis="EVIDENCE_BACKED"), analysis
    )
    assert objection is not None
    assert objection.basis is ObjectionBasis.ANTICIPATED


def test_an_evidence_backed_objection_with_a_citation_keeps_its_basis() -> None:
    analysis = _analysis(D.PRICE_SENSITIVITY)
    objection, _, _ = resolve_objection(
        ObjectionDraft(
            objection="예산 상한이 있다",
            basis="EVIDENCE_BACKED",
            dimensions=[D.PRICE_SENSITIVITY],
        ),
        analysis,
    )
    assert objection.basis is ObjectionBasis.EVIDENCE_BACKED


def test_an_unrecognised_basis_becomes_an_anticipation() -> None:
    """Mislabelling an expectation as evidence puts words in the customer's mouth."""
    analysis = _analysis(D.PROBLEM)
    objection, _, _ = resolve_objection(
        ObjectionDraft(objection="확인 필요", basis="CUSTOMER_SAID_SO"), analysis
    )
    assert objection.basis is ObjectionBasis.ANTICIPATED


def test_a_response_resting_on_nothing_must_admit_it() -> None:
    analysis = _analysis(D.PROBLEM)
    objection, _, _ = resolve_objection(
        ObjectionDraft(objection="인증이 없다", response="문제없다"), analysis
    )
    assert objection.missing_evidence, "an answer with neither citation nor admission"


def test_the_two_bases_can_be_separated() -> None:
    backed = ProposalObjection(objection="a", basis=ObjectionBasis.EVIDENCE_BACKED)
    anticipated = ProposalObjection(objection="b", basis=ObjectionBasis.ANTICIPATED)
    a, b = split_by_basis([backed, anticipated])
    assert a == [backed] and b == [anticipated]


# -- evidence needs -------------------------------------------------------------------

def test_the_timings_are_a_sequence_plus_an_honest_blank() -> None:
    import dataclasses

    assert len(list(EvidenceTiming)) == 5
    assert EvidenceTiming.UNCLASSIFIED in EvidenceTiming
    names = {f.name for f in dataclasses.fields(EvidenceNeed)}
    assert not any("score" in n or "weight" in n or "rank" in n for n in names)


def test_an_unplaced_gap_defaults_to_unclassified() -> None:
    assert EvidenceNeed(need="something").timing is EvidenceTiming.UNCLASSIFIED


def test_every_analysis_gap_is_carried_forward() -> None:
    """Losing an open question between phases is how a proposal comes to look well founded."""
    analysis = _analysis(D.PROBLEM)
    needs = carry_forward_gaps(analysis, {})
    gaps = {need.need for need in needs}
    for claim in analysis.claims:
        for gap in claim.missing_evidence:
            assert gap in gaps


def test_an_unclassified_gap_is_not_promoted_to_the_earliest_timing() -> None:
    """Promoting it would state an urgency the analysis never claimed.

    And once written down, a default is indistinguishable from a judgement: a reader cannot
    tell "somebody decided this blocks the proposal" from "nobody looked".
    """
    analysis = _analysis(D.PROBLEM)
    needs = carry_forward_gaps(analysis, {})
    assert needs and all(n.timing is EvidenceTiming.UNCLASSIFIED for n in needs)


def test_an_unclassified_gap_is_still_carried_forward() -> None:
    """Not promoted, and not dropped either."""
    analysis = _analysis(D.PROBLEM)
    needs = {n.need for n in carry_forward_gaps(analysis, {})}
    for claim in analysis.claims:
        for gap in claim.missing_evidence:
            assert gap in needs


def test_a_classified_gap_takes_the_timing_it_was_given() -> None:
    analysis = _analysis(D.PROBLEM)
    target = f"gap for {D.BUDGET_EVIDENCE.value}"
    needs = carry_forward_gaps(analysis, {target: EvidenceTiming.BEFORE_PRICING})
    need = next(n for n in needs if n.need == target)
    assert need.timing is EvidenceTiming.BEFORE_PRICING
    assert need.dimension is D.BUDGET_EVIDENCE


# -- the entity invariants ----------------------------------------------------------

def _strategy(**overrides) -> ProposalStrategy:
    base = dict(
        project_id=PROJECT,
        client_id="cli_1",
        client_name=ALPHA,
        country="VN",
        analysis_id="cla_1",
    )
    base.update(overrides)
    return ProposalStrategy(**base)


def test_a_strategy_without_an_analysis_is_invalid() -> None:
    violations = evidence.check_proposal_strategy(_strategy(analysis_id=""))
    assert any("analysis_id is empty" in v for v in violations)


def test_an_analysis_for_another_client_is_caught() -> None:
    analysis = _analysis(D.PROBLEM)
    violations = evidence.check_proposal_strategy(_strategy(client_id="cli_other"), analysis)
    assert any("another client" in v for v in violations)


def test_a_reference_to_an_unsettled_dimension_is_invalid() -> None:
    analysis = _analysis(D.PROBLEM)
    strategy = _strategy(
        key_message=StrategyStatement(text="주장", dimensions=[D.BUYER]),
    )
    violations = evidence.check_proposal_strategy(strategy, analysis)
    assert any("did not settle" in v for v in violations)


def test_a_proposed_solution_needs_selected_elements() -> None:
    violations = evidence.check_proposal_strategy(_strategy(proposed_solution="something"))
    assert any("selected_solution_elements" in v for v in violations)


def test_an_evidence_backed_objection_must_cite_something() -> None:
    strategy = _strategy(
        objections=[
            ProposalObjection(objection="비싸다", basis=ObjectionBasis.EVIDENCE_BACKED)
        ]
    )
    violations = evidence.check_proposal_strategy(strategy)
    assert any("cites no dimension" in v for v in violations)


def test_a_response_with_neither_evidence_nor_an_admission_is_invalid() -> None:
    strategy = _strategy(
        objections=[
            ProposalObjection(objection="비싸다", response="괜찮다")
        ]
    )
    violations = evidence.check_proposal_strategy(strategy)
    assert any("assertion dressed as a position" in v for v in violations)


def test_a_duplicate_storyline_step_is_invalid() -> None:
    strategy = _strategy(
        storyline=[
            StoryStep(step_type=StoryStepType.PROBLEM, message="a"),
            StoryStep(step_type=StoryStepType.PROBLEM, message="b"),
        ]
    )
    violations = evidence.check_proposal_strategy(strategy)
    assert any("duplicate storyline steps" in v for v in violations)


def test_a_statement_with_no_dimension_is_invalid() -> None:
    strategy = _strategy(key_message=StrategyStatement(text="주장"))
    violations = evidence.check_proposal_strategy(strategy)
    assert any("names no analysis dimension" in v for v in violations)


def test_a_statement_offering_nothing_is_invalid() -> None:
    strategy = _strategy(
        selected_solution_elements=[SelectedSolutionElement(ref="S1", text="a sensor")],
        key_message=StrategyStatement(text="주장", dimensions=[D.PROBLEM]),
    )
    violations = evidence.check_proposal_strategy(strategy)
    assert any("offers none of the selected" in v for v in violations)


def test_a_statement_offering_an_unselected_ref_is_invalid() -> None:
    """Checked against the selected refs, so the record validates on its own."""
    strategy = _strategy(
        selected_solution_elements=[SelectedSolutionElement(ref="S1", text="a sensor")],
        key_message=StrategyStatement(
            text="주장", dimensions=[D.PROBLEM], solution_element_refs=["S9"]
        ),
    )
    violations = evidence.check_proposal_strategy(strategy)
    assert any("never selected" in v for v in violations)


def test_a_selected_element_missing_half_of_itself_is_invalid() -> None:
    strategy = _strategy(
        selected_solution_elements=[SelectedSolutionElement(ref="S1", text="  ")]
    )
    violations = evidence.check_proposal_strategy(strategy)
    assert any("missing its ref or its text" in v for v in violations)


def test_the_same_element_selected_twice_is_invalid() -> None:
    strategy = _strategy(
        selected_solution_elements=[
            SelectedSolutionElement(ref="S1", text="a sensor"),
            SelectedSolutionElement(ref="S1", text="a sensor"),
        ]
    )
    violations = evidence.check_proposal_strategy(strategy)
    assert any("selected twice" in v for v in violations)


def test_no_priority_ranking_or_forecast_anywhere() -> None:
    import dataclasses

    names = {f.name for f in dataclasses.fields(ProposalStrategy)}
    for banned in ("priority", "rank", "score", "probability", "likelihood", "forecast", "win"):
        assert not any(banned in name for name in names), f"a field named for {banned}"
