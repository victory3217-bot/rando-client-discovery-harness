# -*- coding: utf-8 -*-
"""The proposal pipeline end to end, offline.

No API key and no network. The echo provider suggests nothing usable, which is the right
behaviour for a provider with no evidence — and the assertions check both that the calls
happened and that nothing was decided, because a run that never happened looks identical to
one that decided nothing.
"""
from __future__ import annotations

import json

import pytest

from adapters.llm.echo import EchoLLM
from adapters.prompts import load_proposal_prompt_set
from adapters.storage.memory import MemoryStorage
from core import evidence
from core.models import (
    AnalysisClaim,
    AnalysisDimension,
    ClientAnalysis,
    ClientCandidate,
    Confidence,
    EvidenceTiming,
    EvidenceType,
    FitAssessment,
    FitCriterion,
    FitLevel,
    ObjectionBasis,
    ObjectiveSource,
    PriorityDecision,
    Project,
    ProposalObjective,
    ProposalStatus,
    ProposalStrategy,
    SalesPriority,
    SelectedSolutionElement,
    StoryStepType,
    aggregate_finding_ids,
    aggregate_missing_evidence,
    as_dict,
    from_dict,
)
from core.proposal import SolutionElement, persist, run_proposal_strategy
from scripted_llm import ScriptedLLM

D = AnalysisDimension
PROJECT = "prj_proposal_e2e"
ALPHA = "Fictional Alpha Water Systems"

ELEMENTS = [
    SolutionElement(ref="S1", text="a single-module multi-parameter sensor"),
    SolutionElement(ref="S2", text="remote data access"),
]


@pytest.fixture
def prompts(repo_root):
    return load_proposal_prompt_set(repo_root / "prompts")


def _settled(dimension, statement="확인된 내용") -> AnalysisClaim:
    return AnalysisClaim(
        dimension=dimension,
        statement=statement,
        finding_ids=["f1"],
        evidence_type=EvidenceType.FACT,
        confidence=Confidence.MEDIUM,
        framework_basis=["MN03"],
    )


def _analysis(*settled_dimensions) -> ClientAnalysis:
    claims = [
        _settled(d)
        if d in settled_dimensions
        else AnalysisClaim(dimension=d, missing_evidence=[f"gap for {d.value}"])
        for d in AnalysisDimension
    ]
    return ClientAnalysis(
        project_id=PROJECT,
        client_id="cli_1",
        client_name=ALPHA,
        country="VN",
        industry="water utilities",
        our_solution="a single-module multi-parameter sensor",
        claims=claims,
        analysis_id="cla_1",
        finding_ids=aggregate_finding_ids(claims),
        missing_evidence=aggregate_missing_evidence(claims),
    )


def _project() -> Project:
    return Project(project_id=PROJECT, company_name="Fictional Sensing")


def _run(llm, prompts, *, analysis=None, objective=None):
    return run_proposal_strategy(
        project=_project(),
        analysis=analysis or _analysis(D.PROBLEM, D.VALUE_PROPOSITION, D.VALUE_DRIVER),
        solution_elements=ELEMENTS,
        llm=llm,
        prompts=prompts,
        objective=objective,
    )


def _scripted(strategy=None, objections=None) -> ScriptedLLM:
    return ScriptedLLM(
        {
            "proposal_strategy": [strategy or {"storyline": []}],
            "proposal_objections": [objections or {"objections": []}],
        }
    )


def _full_strategy() -> dict:
    return {
        "suggested_objective": "DISCOVERY_MEETING",
        "objective_detail": "확인할 것을 정리한다",
        "solution_element_refs": ["S1"],
        "value_proposition": {
            "text": "수동 채수를 상시 계측으로 대체한다",
            "dimensions": ["PROBLEM", "VALUE_PROPOSITION"],
            "solution_element_refs": ["S1"],
        },
        "key_message": {
            "text": "측정 주기를 인력 증원 없이 확보한다",
            "dimensions": ["PROBLEM", "VALUE_DRIVER"],
            "solution_element_refs": ["S1"],
        },
        "storyline": [
            {"step_type": "PROBLEM", "message": "수동 채수에 의존한다", "dimensions": ["PROBLEM"]},
            {"step_type": "NEXT_STEP", "message": "미팅을 요청한다", "dimensions": ["PROBLEM"]},
        ],
        "evidence_timing": [{"need": f"gap for {D.BUDGET_EVIDENCE.value}", "timing": "BEFORE_PRICING"}],
    }


# -- shape ---------------------------------------------------------------------

def test_two_calls_one_for_the_case_and_one_for_the_pushback(prompts) -> None:
    """Asking for both at once produces objections that conveniently answer themselves."""
    outcome = _run(EchoLLM(), prompts)
    assert [r.stage for r in outcome.transmissions] == [
        "propose_strategy",
        "anticipate_objections",
    ]


def test_offline_end_to_end_with_echo(prompts) -> None:
    """No API key, no network. The offline provider has nothing to say, and says nothing.

    It does return an objective, because the echo adapter fills an enum from the schema and
    the first value happens to be one the evidence carries. That is the pipeline behaving
    correctly rather than a hole: what matters is that the choice is recorded as the machine's,
    and that nothing the provider could not support survives.
    """
    outcome = _run(EchoLLM(), prompts)

    assert outcome.transmissions, "the pipeline must have made calls"
    strategy = outcome.strategies[0]
    assert strategy.objective_source is not ObjectiveSource.HUMAN
    assert strategy.key_message is None, "no claim survives an echo's citations"
    assert strategy.value_proposition is None
    assert strategy.selected_solution_elements == [], "and nothing is offered"
    assert strategy.storyline == []
    assert strategy.objections == []


def test_a_scripted_run_produces_a_usable_strategy(prompts) -> None:
    outcome = _run(_scripted(_full_strategy()), prompts)
    strategy = outcome.strategies[0]

    assert strategy.objective is ProposalObjective.DISCOVERY_MEETING
    assert strategy.objective_source is ObjectiveSource.AI_SUGGESTED
    assert strategy.status is ProposalStatus.STRATEGY_DRAFTED
    assert [(e.ref, e.text) for e in strategy.selected_solution_elements] == [
        ("S1", "a single-module multi-parameter sensor")
    ]
    assert strategy.proposed_solution == "a single-module multi-parameter sensor"
    assert strategy.key_message is not None
    assert [s.step_type for s in strategy.storyline] == [
        StoryStepType.PROBLEM,
        StoryStepType.NEXT_STEP,
    ]
    assert evidence.check_proposal_strategy(strategy, _analysis(
        D.PROBLEM, D.VALUE_PROPOSITION, D.VALUE_DRIVER
    )) == []


def test_the_strategy_points_at_the_analysis_it_read(prompts) -> None:
    outcome = _run(_scripted(_full_strategy()), prompts)
    assert outcome.strategies[0].analysis_id == "cla_1"


# -- the objective ---------------------------------------------------------------

def test_a_human_objective_is_recorded_as_one(prompts) -> None:
    outcome = _run(
        _scripted(_full_strategy()), prompts, objective=ProposalObjective.TECHNICAL_REVIEW
    )
    strategy = outcome.strategies[0]
    assert strategy.objective is ProposalObjective.TECHNICAL_REVIEW
    assert strategy.objective_source is ObjectiveSource.HUMAN


def test_a_human_objective_survives_a_model_suggesting_another(prompts) -> None:
    """The person's decision is not a suggestion to be weighed against the model's."""
    strategy_payload = _full_strategy()
    strategy_payload["suggested_objective"] = "FORMAL_PROPOSAL"
    outcome = _run(
        _scripted(strategy_payload), prompts, objective=ProposalObjective.DISCOVERY_MEETING
    )
    assert outcome.strategies[0].objective is ProposalObjective.DISCOVERY_MEETING


def test_an_over_reaching_suggestion_leaves_no_objective(prompts) -> None:
    """And no substitute, and the strategy stays undrafted."""
    payload = _full_strategy()
    payload["suggested_objective"] = "FORMAL_PROPOSAL"
    outcome = _run(_scripted(payload), prompts)

    strategy = outcome.strategies[0]
    assert strategy.objective is None
    assert strategy.objective_source is None
    assert strategy.status is ProposalStatus.NOT_STARTED
    assert ProposalObjective.FORMAL_PROPOSAL in outcome.withdrawn_objectives


def test_an_over_reaching_human_objective_is_kept_and_flagged(prompts) -> None:
    outcome = _run(
        _scripted(_full_strategy()), prompts, objective=ProposalObjective.FORMAL_PROPOSAL
    )
    strategy = outcome.strategies[0]
    assert strategy.objective is ProposalObjective.FORMAL_PROPOSAL
    assert any("OUTRUNS" in f.code for f in outcome.review_flags)


# -- Phase 5 gates hold ------------------------------------------------------------

def test_no_value_proposition_where_the_analysis_established_none(prompts) -> None:
    outcome = _run(
        _scripted(_full_strategy()), prompts, analysis=_analysis(D.PROBLEM, D.VALUE_DRIVER)
    )
    strategy = outcome.strategies[0]
    assert strategy.value_proposition is None
    assert any("VALUE_PROPOSITION" in n.need or n.dimension is D.VALUE_PROPOSITION
               for n in strategy.evidence_needs)


def test_no_differentiation_step_without_an_established_advantage(prompts) -> None:
    payload = _full_strategy()
    payload["storyline"].append(
        {"step_type": "DIFFERENTIATION", "message": "우리가 앞선다", "dimensions": ["PROBLEM"]}
    )
    outcome = _run(_scripted(payload), prompts)
    strategy = outcome.strategies[0]
    assert strategy.step_of(StoryStepType.DIFFERENTIATION) is None
    assert any("COMPETITIVE_POSITION_UNKNOWN" in f.code for f in outcome.review_flags)


def test_an_unknown_solution_element_does_not_reach_the_strategy(prompts) -> None:
    payload = _full_strategy()
    payload["solution_element_refs"] = ["S1", "S_INVENTED"]
    outcome = _run(_scripted(payload), prompts)
    assert [e.ref for e in outcome.strategies[0].selected_solution_elements] == ["S1"]
    assert any("UNKNOWN_SOLUTION_ELEMENT" in r.code for r in outcome.rejections)


def test_a_key_message_with_no_offer_behind_it_is_dropped(prompts) -> None:
    payload = _full_strategy()
    payload["key_message"]["solution_element_refs"] = []
    outcome = _run(_scripted(payload), prompts)
    assert outcome.strategies[0].key_message is None


def test_a_statement_offer_traces_to_the_callers_list(prompts) -> None:
    """statement.refs → selected_solution_elements[*].ref → the caller's capability list."""
    outcome = _run(_scripted(_full_strategy()), prompts)
    strategy = outcome.strategies[0]

    assert strategy.key_message.solution_element_refs == ["S1"]
    selected = {e.ref: e.text for e in strategy.selected_solution_elements}
    assert set(strategy.key_message.solution_element_refs) <= set(selected)
    assert selected["S1"] == "a single-module multi-parameter sensor", "the caller's wording"


def test_the_proposed_solution_is_assembled_from_selected_text_only(prompts) -> None:
    payload = _full_strategy()
    payload["solution_element_refs"] = ["S1", "S2"]
    outcome = _run(_scripted(payload), prompts)
    strategy = outcome.strategies[0]

    parts = [e.text for e in strategy.selected_solution_elements]
    assert parts == ["a single-module multi-parameter sensor", "remote data access"]
    for part in parts:
        assert part in strategy.proposed_solution


# -- gaps -----------------------------------------------------------------------------

def test_every_analysis_gap_survives_into_the_strategy(prompts) -> None:
    analysis = _analysis(D.PROBLEM, D.VALUE_PROPOSITION, D.VALUE_DRIVER)
    outcome = _run(_scripted(_full_strategy()), prompts, analysis=analysis)
    needs = {n.need for n in outcome.strategies[0].evidence_needs}
    for gap in analysis.missing_evidence:
        assert gap in needs


def test_a_classified_gap_takes_its_timing(prompts) -> None:
    outcome = _run(_scripted(_full_strategy()), prompts)
    need = next(
        n for n in outcome.strategies[0].evidence_needs
        if n.need == f"gap for {D.BUDGET_EVIDENCE.value}"
    )
    assert need.timing is EvidenceTiming.BEFORE_PRICING


def test_the_gaps_nobody_placed_say_so(prompts) -> None:
    """One gap was classified in the payload; the rest keep an honest blank."""
    outcome = _run(_scripted(_full_strategy()), prompts)
    needs = outcome.strategies[0].evidence_needs
    unplaced = [n for n in needs if n.timing is EvidenceTiming.UNCLASSIFIED]
    assert unplaced, "and they are not quietly marked urgent"
    assert all(n.timing is not EvidenceTiming.BEFORE_PROPOSAL for n in unplaced)


# -- objections --------------------------------------------------------------------------

def test_objections_arrive_as_linked_objects(prompts) -> None:
    objections = {
        "objections": [
            {
                "objection": "예산 상한이 있다",
                "basis": "EVIDENCE_BACKED",
                "dimensions": ["PROBLEM"],
                "response": "확인 후 범위를 조정한다",
                "response_dimensions": ["PROBLEM"],
            },
            {"objection": "인증이 없을 수 있다", "basis": "ANTICIPATED"},
        ]
    }
    outcome = _run(_scripted(_full_strategy(), objections), prompts)
    strategy = outcome.strategies[0]

    assert len(strategy.objections) == 2
    backed = strategy.objections[0]
    assert backed.basis is ObjectionBasis.EVIDENCE_BACKED
    assert backed.response and backed.response_dimensions


def test_an_empty_objection_list_is_flagged_not_filled(prompts) -> None:
    """A minimum count would be met by fabrication, which is worse than the silence."""
    outcome = _run(_scripted(_full_strategy()), prompts)
    assert outcome.strategies[0].objections == []
    assert any("NO_OBJECTIONS" in f.code for f in outcome.review_flags)


# -- priority is untouched -------------------------------------------------------------------

def test_the_candidate_priority_is_untouched(prompts) -> None:
    import copy

    candidate = ClientCandidate(
        project_id=PROJECT,
        client_name=ALPHA,
        country="VN",
        industry="water",
        discovery_rationale="their problem matches our capability",
        source_ids=["src_1"],
        fit=[FitAssessment(criterion=c, level=FitLevel.UNKNOWN) for c in FitCriterion],
        priority=PriorityDecision(band=SalesPriority.P2),
        client_id="cli_1",
    )
    before = copy.deepcopy(candidate.priority)
    _run(_scripted(_full_strategy()), prompts)
    assert candidate.priority == before


# -- persistence and serialization -------------------------------------------------------

def test_only_strategies_reach_storage(prompts) -> None:
    storage = MemoryStorage()
    outcome = _run(_scripted(_full_strategy()), prompts)
    persist(outcome, storage)
    assert len(storage.get_proposal_strategies(PROJECT)) == 1
    assert not hasattr(storage, "save_story_step")
    assert not hasattr(storage, "save_objection")


def test_the_strategy_round_trips_through_json(prompts) -> None:
    """Five enums and three nested value objects, which is where a serializer breaks."""
    objections = {
        "objections": [
            {
                "objection": "예산 상한",
                "basis": "EVIDENCE_BACKED",
                "dimensions": ["PROBLEM"],
                "response": "조정한다",
                "response_dimensions": ["PROBLEM"],
            }
        ]
    }
    outcome = _run(_scripted(_full_strategy(), objections), prompts)
    original = outcome.strategies[0]

    restored = from_dict(ProposalStrategy, json.loads(json.dumps(as_dict(original), ensure_ascii=False)))

    assert restored == original
    assert isinstance(restored.objective, ProposalObjective)
    assert isinstance(restored.objective_source, ObjectiveSource)
    assert isinstance(restored.storyline[0].step_type, StoryStepType)
    assert isinstance(restored.objections[0].basis, ObjectionBasis)
    assert isinstance(restored.objections[0].dimensions[0], AnalysisDimension)
    assert isinstance(restored.evidence_needs[0].timing, EvidenceTiming)
    assert isinstance(restored.key_message.dimensions[0], AnalysisDimension)

    # The ref -> text mapping has to survive the round trip, or a later phase resolving a
    # statement's offer gets the wrong wording or none at all.
    assert isinstance(restored.selected_solution_elements[0], SelectedSolutionElement)
    mapping = {e.ref: e.text for e in restored.selected_solution_elements}
    assert mapping == {"S1": "a single-module multi-parameter sensor"}
    assert restored.key_message.solution_element_refs == ["S1"]


def test_the_sample_strategy_loads_and_validates(repo_root) -> None:
    path = repo_root / "examples" / "sample_project" / "proposal_strategy.json"
    analysis_path = repo_root / "examples" / "sample_project" / "client_analysis.json"
    analysis = from_dict(
        ClientAnalysis, json.loads(analysis_path.read_text(encoding="utf-8"))[0]
    )
    for record in json.loads(path.read_text(encoding="utf-8")):
        strategy = from_dict(ProposalStrategy, record)
        assert evidence.check_proposal_strategy(strategy, analysis) == []
        assert strategy.step_of(StoryStepType.DIFFERENTIATION) is None, (
            "the sample analysis established no advantage, so the sample must not claim one"
        )


# -- language -------------------------------------------------------------------------------

def test_every_new_enum_has_labels_in_both_languages(repo_root) -> None:
    names = (
        "ProposalObjective", "ObjectiveSource", "StoryStepType", "ObjectionBasis",
        "EvidenceTiming",
    )
    members = {
        "ProposalObjective": ProposalObjective,
        "ObjectiveSource": ObjectiveSource,
        "StoryStepType": StoryStepType,
        "ObjectionBasis": ObjectionBasis,
        "EvidenceTiming": EvidenceTiming,
    }
    for lang in ("ko", "en"):
        with (repo_root / "locales" / f"{lang}.json").open(encoding="utf-8") as fh:
            enums = json.load(fh)["enums"]
        for name in names:
            assert name in enums, f"{lang}.json has no {name}"
            for member in members[name]:
                assert member.value in enums[name], f"{lang}.json: {name}.{member.value}"


def test_the_core_writes_no_user_facing_prose(prompts) -> None:
    outcome = _run(EchoLLM(), prompts)
    for need in outcome.strategies[0].evidence_needs:
        assert need.need.isascii() or "gap for" in need.need
