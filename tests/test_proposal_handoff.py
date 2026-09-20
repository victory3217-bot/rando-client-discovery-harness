# -*- coding: utf-8 -*-
"""What Phase 7 and Phase 9 can build from a finished strategy.

Phase 7 needs a commercial context and no price; Phase 9 needs something renderable and no
rendering. These tests assemble both out of a ``ProposalStrategy`` and its ``ClientAnalysis``,
and fix the boundary from the other side: this phase must not have produced a number, and must
not have produced a document.
"""
from __future__ import annotations

import json

import pytest

from core.models import (
    AnalysisClaim,
    AnalysisDimension,
    ClientAnalysis,
    Confidence,
    EvidenceNeed,
    EvidenceTiming,
    EvidenceType,
    ObjectionBasis,
    ObjectiveSource,
    PricingResult,
    ProposalObjection,
    ProposalObjective,
    ProposalStrategy,
    SelectedSolutionElement,
    StoryStep,
    StoryStepType,
    StrategyStatement,
    aggregate_finding_ids,
    aggregate_missing_evidence,
)
from core.proposal import split_by_basis

D = AnalysisDimension
PROJECT = "prj_proposal_handoff"

#: The four MN06 claims Phase 7 reads. No numbers among them.
PHASE_7_DIMENSIONS = (
    D.VALUE_DRIVER, D.PRICE_SENSITIVITY, D.BUDGET_EVIDENCE, D.PROCUREMENT_CONTEXT,
)

#: What Phase 9 renders. Structures, not formats.
PHASE_9_PARTS = ("key_message", "storyline", "objections", "evidence_needs")


def _settled(dimension) -> AnalysisClaim:
    return AnalysisClaim(
        dimension=dimension,
        statement=f"{dimension.value} 에 대한 확인된 내용",
        finding_ids=["f1"],
        evidence_type=EvidenceType.FACT,
        confidence=Confidence.MEDIUM,
    )


@pytest.fixture
def analysis() -> ClientAnalysis:
    settled = {D.PROBLEM, D.VALUE_PROPOSITION, *PHASE_7_DIMENSIONS}
    claims = [
        _settled(d) if d in settled else AnalysisClaim(dimension=d, missing_evidence=[f"gap {d.value}"])
        for d in AnalysisDimension
    ]
    return ClientAnalysis(
        project_id=PROJECT,
        client_id="cli_1",
        client_name="Fictional Alpha Water Systems",
        country="VN",
        industry="water utilities",
        our_solution="a single-module multi-parameter sensor",
        claims=claims,
        analysis_id="cla_1",
        finding_ids=aggregate_finding_ids(claims),
        missing_evidence=aggregate_missing_evidence(claims),
    )


@pytest.fixture
def strategy() -> ProposalStrategy:
    return ProposalStrategy(
        project_id=PROJECT,
        client_id="cli_1",
        client_name="Fictional Alpha Water Systems",
        country="VN",
        analysis_id="cla_1",
        objective=ProposalObjective.DISCOVERY_MEETING,
        objective_source=ObjectiveSource.HUMAN,
        selected_solution_elements=[
            SelectedSolutionElement(ref="S1", text="a single-module multi-parameter sensor")
        ],
        proposed_solution="a single-module multi-parameter sensor",
        key_message=StrategyStatement(
            text="측정 주기를 인력 증원 없이 확보한다",
            dimensions=[D.PROBLEM, D.VALUE_DRIVER],
            solution_element_refs=["S1"],
        ),
        storyline=[
            StoryStep(step_type=StoryStepType.PROBLEM, message="수동 채수", dimensions=[D.PROBLEM]),
            StoryStep(step_type=StoryStepType.NEXT_STEP, message="미팅 요청", dimensions=[D.PROBLEM]),
        ],
        objections=[
            ProposalObjection(
                objection="예산 상한",
                basis=ObjectionBasis.EVIDENCE_BACKED,
                dimensions=[D.BUDGET_EVIDENCE],
                response="범위를 조정한다",
                response_dimensions=[D.BUDGET_EVIDENCE],
            ),
            ProposalObjection(objection="인증 미확인", basis=ObjectionBasis.ANTICIPATED,
                              missing_evidence=["인증 요건"]),
        ],
        evidence_needs=[
            EvidenceNeed(need="예산 규모", timing=EvidenceTiming.BEFORE_PRICING,
                         dimension=D.BUDGET_EVIDENCE),
            EvidenceNeed(need="접근 경로", timing=EvidenceTiming.BEFORE_PROPOSAL),
        ],
    )


# -- Phase 7 -------------------------------------------------------------------

def test_the_commercial_context_assembles_without_re_reading_anything(
    strategy, analysis
) -> None:
    """Four claims plus what the strategy decided. No document is opened again."""
    context = {
        "client_id": strategy.client_id,
        "country": strategy.country,
        "objective": strategy.objective.value,
        "offered": [
            {"ref": e.ref, "text": e.text} for e in strategy.selected_solution_elements
        ],
        **{
            dimension.value: analysis.claim_for(dimension).statement
            for dimension in PHASE_7_DIMENSIONS
        },
        "before_pricing": [
            need.need
            for need in strategy.evidence_needs
            if need.timing is EvidenceTiming.BEFORE_PRICING
        ],
    }

    assert all(context[d.value] for d in PHASE_7_DIMENSIONS)
    assert context["before_pricing"] == ["예산 규모"]

    # Phase 7 gets both halves and is not forced to use prose as an identifier.
    assert context["offered"] == [
        {"ref": "S1", "text": "a single-module multi-parameter sensor"}
    ]


def test_the_context_fits_the_pricing_entity_that_already_exists(strategy, analysis) -> None:
    """``PricingResult`` owns the hand-off, which is why the strategy holds no pricing dict."""
    result = PricingResult(
        project_id=strategy.project_id,
        client_id=strategy.client_id,
        commercial_context={
            "objective": strategy.objective.value,
            "offered": [e.ref for e in strategy.selected_solution_elements],
        },
    )
    assert result.pricing_payload == {}, "Phase 7 fills this, not Phase 6"
    assert result.commercial_context["objective"] == "DISCOVERY_MEETING"


def test_phase_six_produced_no_price(strategy) -> None:
    import dataclasses

    names = {f.name for f in dataclasses.fields(ProposalStrategy)}
    for banned in ("price", "discount", "margin", "quote", "quotation", "revenue", "wtp"):
        assert not any(banned in name for name in names), f"a field named for {banned}"

    payload = json.dumps(
        {
            "key_message": strategy.key_message.text,
            "steps": [s.message for s in strategy.storyline],
        },
        ensure_ascii=False,
    )
    assert "pricing_input" not in payload


def test_a_before_pricing_gap_is_visible_to_phase_seven(strategy) -> None:
    """Otherwise pricing runs on a budget nobody has checked."""
    timings = {need.timing for need in strategy.evidence_needs}
    assert EvidenceTiming.BEFORE_PRICING in timings


# -- Phase 9 -------------------------------------------------------------------

def test_a_renderer_can_resolve_a_statements_offer_to_display_text(strategy) -> None:
    """ref is the relationship; text is what goes on the slide. Phase 9 needs both."""
    by_ref = {e.ref: e.text for e in strategy.selected_solution_elements}
    for ref in strategy.key_message.solution_element_refs:
        assert by_ref[ref], "every ref resolves to something showable"


def test_every_renderable_part_is_structured(strategy) -> None:
    """A renderer needs parts it can place, not a paragraph it has to parse."""
    for part in PHASE_9_PARTS:
        assert hasattr(strategy, part)

    assert isinstance(strategy.key_message, StrategyStatement)
    assert all(isinstance(step, StoryStep) for step in strategy.storyline)
    assert all(isinstance(o, ProposalObjection) for o in strategy.objections)
    assert all(isinstance(n, EvidenceNeed) for n in strategy.evidence_needs)


def test_a_brief_can_be_assembled_in_order(strategy) -> None:
    """The storyline is a logic flow, so its order is the document's order."""
    sections = [(step.step_type.value, step.message) for step in strategy.storyline]
    assert sections == [("PROBLEM", "수동 채수"), ("NEXT_STEP", "미팅 요청")]


def test_the_two_objection_kinds_stay_separable_for_a_renderer(strategy) -> None:
    """A reader walking into a meeting needs to know which is which before they speak."""
    backed, anticipated = split_by_basis(strategy.objections)
    assert len(backed) == 1 and len(anticipated) == 1
    assert backed[0].dimensions, "and the evidence-backed one says what it rests on"


def test_gaps_can_be_grouped_by_when_they_matter(strategy) -> None:
    grouped: dict[EvidenceTiming, list[str]] = {}
    for need in strategy.evidence_needs:
        grouped.setdefault(need.timing, []).append(need.need)
    assert set(grouped) == {EvidenceTiming.BEFORE_PRICING, EvidenceTiming.BEFORE_PROPOSAL}


def test_phase_six_renders_nothing(strategy) -> None:
    """Structure only. No HTML, DOCX, PPTX or PDF is produced by this phase."""
    import ast
    from pathlib import Path

    package = Path(__file__).resolve().parent.parent / "core" / "proposal"
    banned = {"html", "docx", "pptx", "reportlab", "jinja2", "markdown", "weasyprint"}
    for path in sorted(package.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0].lower() not in banned, path.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0].lower() not in banned, path.name


def test_the_strategy_carries_no_rendered_output(strategy) -> None:
    import dataclasses

    names = {f.name for f in dataclasses.fields(ProposalStrategy)}
    for banned in ("html", "document", "slide", "pdf", "docx", "rendered"):
        assert not any(banned in name for name in names)
