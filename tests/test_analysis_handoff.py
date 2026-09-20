# -*- coding: utf-8 -*-
"""What Phase 6 and Phase 7 can build from a finished analysis, without re-reading anything.

The point of a structured record is that the next phase does not have to go back to the
documents. These tests assemble the inputs each later phase needs out of a ``ClientAnalysis``
alone — if one of them starts failing, the record has stopped carrying its own weight and the
next phase will quietly re-analyse the evidence to make up the difference.

They also fix the boundary from the other side: Phase 5 must **not** produce the proposal
fields, and must not produce a price.
"""
from __future__ import annotations

import json

import pytest

from core.analysis import source_ids_for
from core.models import (
    AnalysisClaim,
    AnalysisDimension,
    ClientAnalysis,
    Confidence,
    EvidenceRef,
    EvidenceType,
    MarketScope,
    ProposalStrategy,
    ResearchFinding,
    aggregate_finding_ids,
    aggregate_missing_evidence,
)

D = AnalysisDimension
PROJECT = "prj_handoff"

#: What Phase 6 must be able to fill in from Phase 5 output alone.
PHASE_6_INPUTS = (
    "client", "country", "problem", "buyer", "decision_maker", "proposed_solution",
    "value_proposition", "competitive_advantage", "evidence", "additional_evidence_required",
    "pricing_input",
)

#: What Phase 5 must not have produced: those are Phase 6's to write.
PHASE_6_OUTPUTS = (
    "key_message", "proposal_storyline", "expected_objection", "response_logic",
)

#: The commercial context Phase 7 receives. Four claims, no numbers.
PHASE_7_DIMENSIONS = (
    D.VALUE_DRIVER, D.PRICE_SENSITIVITY, D.BUDGET_EVIDENCE, D.PROCUREMENT_CONTEXT,
)


def _finding(finding_id: str, mn: str = "MN03") -> ResearchFinding:
    return ResearchFinding(
        project_id=PROJECT,
        finding="확인된 내용",
        evidence_type=EvidenceType.FACT,
        confidence=Confidence.MEDIUM,
        mn_basis=[mn],
        source_id=f"src_{finding_id}",
        finding_id=finding_id,
    )


def _settled(dimension, finding_id, framework="MN03") -> AnalysisClaim:
    return AnalysisClaim(
        dimension=dimension,
        statement=f"{dimension.value} 에 대한 확인된 내용",
        finding_ids=[finding_id],
        evidence_type=EvidenceType.FACT,
        confidence=Confidence.MEDIUM,
        framework_basis=[framework],
    )


@pytest.fixture
def analysis() -> ClientAnalysis:
    settled = {
        D.PROBLEM: _settled(D.PROBLEM, "f1"),
        D.BUYER: _settled(D.BUYER, "f2"),
        D.DECISION_MAKER: _settled(D.DECISION_MAKER, "f3"),
        D.VALUE_PROPOSITION: _settled(D.VALUE_PROPOSITION, "f4", "MN04"),
        D.COMPETITIVE_ADVANTAGE: _settled(D.COMPETITIVE_ADVANTAGE, "f5", "MN04"),
        D.VALUE_DRIVER: _settled(D.VALUE_DRIVER, "f6", "MN06"),
        D.BUDGET_EVIDENCE: _settled(D.BUDGET_EVIDENCE, "f7", "MN06"),
    }
    claims = [
        settled.get(
            dimension,
            AnalysisClaim(dimension=dimension, missing_evidence=[f"evidence for {dimension.value}"]),
        )
        for dimension in AnalysisDimension
    ]
    return ClientAnalysis(
        project_id=PROJECT,
        client_id="cli_1",
        client_name="Fictional Alpha Water Systems",
        country="VN",
        industry="water utilities",
        our_solution="a single-module multi-parameter sensor",
        claims=claims,
        market_scope=MarketScope.DOMESTIC,
        finding_ids=aggregate_finding_ids(claims),
        missing_evidence=aggregate_missing_evidence(claims),
    )


@pytest.fixture
def findings() -> dict:
    return {f"f{i}": _finding(f"f{i}") for i in range(1, 8)}


# -- Phase 6 -------------------------------------------------------------------

def test_phase_six_can_be_assembled_without_re_reading_the_evidence(analysis, findings) -> None:
    """The whole point of the restructure, asserted as one fixture."""
    inputs = {
        "client": analysis.client_name,
        "country": analysis.country,
        "problem": analysis.claim_for(D.PROBLEM).statement,
        "buyer": analysis.claim_for(D.BUYER).statement,
        "decision_maker": analysis.claim_for(D.DECISION_MAKER).statement,
        "proposed_solution": analysis.our_solution,
        "value_proposition": analysis.claim_for(D.VALUE_PROPOSITION).statement,
        "competitive_advantage": analysis.claim_for(D.COMPETITIVE_ADVANTAGE).statement,
        "evidence": [
            EvidenceRef(finding_id=fid, source_id=findings[fid].source_id)
            for fid in analysis.finding_ids
        ],
        "additional_evidence_required": analysis.missing_evidence,
        "pricing_input": {
            dimension.value: analysis.claim_for(dimension).statement
            for dimension in PHASE_7_DIMENSIONS
        },
    }

    assert set(inputs) == set(PHASE_6_INPUTS)
    for name in ("client", "country", "problem", "buyer", "proposed_solution"):
        assert inputs[name], f"{name} could not be filled from the analysis"
    assert inputs["evidence"] and all(ref.source_id for ref in inputs["evidence"])
    assert inputs["additional_evidence_required"]


def test_the_assembled_inputs_fit_the_proposal_entity(analysis) -> None:
    """They have to land somewhere, and that somewhere already exists."""
    strategy = ProposalStrategy(
        project_id=analysis.project_id,
        client_id=analysis.client_id,
        client_name=analysis.client_name,
        country=analysis.country,
        problem=analysis.claim_for(D.PROBLEM).statement,
        buyer=analysis.claim_for(D.BUYER).statement,
        decision_maker=analysis.claim_for(D.DECISION_MAKER).statement,
        proposed_solution=analysis.our_solution,
        value_proposition=analysis.claim_for(D.VALUE_PROPOSITION).statement,
        competitive_advantage=analysis.claim_for(D.COMPETITIVE_ADVANTAGE).statement,
        additional_evidence_required=list(analysis.missing_evidence),
    )
    assert strategy.problem and strategy.proposed_solution


def test_phase_five_does_not_write_the_proposal(analysis) -> None:
    """Message, storyline, objections and answers are Phase 6's work."""
    import dataclasses

    names = {f.name for f in dataclasses.fields(ClientAnalysis)}
    for field_name in PHASE_6_OUTPUTS:
        assert field_name not in names

    payload = json.dumps(
        {c.dimension.value: c.statement for c in analysis.claims}, ensure_ascii=False
    )
    for dimension in AnalysisDimension:
        assert dimension.value not in PHASE_6_OUTPUTS
    assert payload  # the record holds claims, not a narrative


def test_an_unsettled_dimension_hands_over_a_gap_not_a_guess(analysis) -> None:
    """Phase 6 has to see what is unknown, or it will write around it."""
    assert analysis.claim_for(D.KBF).statement is None
    assert analysis.claim_for(D.KBF).missing_evidence
    assert any("KBF" in gap for gap in analysis.missing_evidence)


# -- Phase 7 -------------------------------------------------------------------

def test_the_commercial_context_is_four_claims(analysis) -> None:
    context = {d: analysis.claim_for(d) for d in PHASE_7_DIMENSIONS}
    assert all(claim is not None for claim in context.values())
    assert len(context) == 4


def test_the_commercial_context_carries_no_numbers(analysis) -> None:
    """Phase 5 is not a pricing engine. No price, no quotation, no willingness to pay."""
    import dataclasses

    names = {f.name for f in dataclasses.fields(ClientAnalysis)}
    for banned in ("price", "quote", "quotation", "margin", "budget_amount", "willingness"):
        assert not any(banned in name for name in names), f"a field named for {banned}"

    values = [d.value for d in AnalysisDimension]
    assert "REVENUE_MODEL_IMPLICATION" not in values, "deferred to Phase 7"


def test_the_commercial_context_is_traceable(analysis, findings) -> None:
    driver = analysis.claim_for(D.VALUE_DRIVER)
    assert source_ids_for(driver, findings) == ["src_f6"]


def test_pricing_input_stays_empty_until_phase_seven(analysis) -> None:
    strategy = ProposalStrategy(
        project_id=analysis.project_id,
        client_id=analysis.client_id,
        client_name=analysis.client_name,
        country=analysis.country,
    )
    assert strategy.pricing_input is None
