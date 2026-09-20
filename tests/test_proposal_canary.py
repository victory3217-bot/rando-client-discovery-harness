# -*- coding: utf-8 -*-
"""Nothing from a proposal strategy escapes through a diagnostic.

This phase handles the most commercially sensitive text in the harness: what we intend to say
to a customer, what we think they will push back on, and what we would answer. A leak here is
not an embarrassment about a document — it is a negotiating position in somebody's log file.

Six surfaces, matching the intake and analysis canaries: repr, exception, rejection record,
traceback, storage, and the run summary an operator would log.
"""
from __future__ import annotations

import json
import traceback

import pytest

from adapters.llm.echo import EchoLLM
from adapters.prompts import load_proposal_prompt_set
from adapters.storage.memory import MemoryStorage
from core.models import (
    AnalysisClaim,
    AnalysisDimension,
    ClientAnalysis,
    Confidence,
    EvidenceType,
    ProposalObjective,
    ProposalStrategy,
    StrategyStatement,
    as_dict,
    aggregate_finding_ids,
    aggregate_missing_evidence,
)
from core.proposal import (
    ProposalOutcome,
    SolutionElement,
    persist,
    run_proposal_strategy,
)
from core.proposal.models import ObjectionDraft, StatementDraft
from core.research.models import Rejection, ReviewFlag
from core.models import Project

CANARY = "ZZCANARYZZ"
PROJECT = "prj_proposal_canary"
D = AnalysisDimension

ELEMENTS = [SolutionElement(ref="S1", text="계측 모듈")]


@pytest.fixture
def prompts(repo_root):
    return load_proposal_prompt_set(repo_root / "prompts")


def _analysis() -> ClientAnalysis:
    claims = []
    for dimension in AnalysisDimension:
        if dimension is D.PROBLEM:
            claims.append(
                AnalysisClaim(
                    dimension=dimension,
                    statement=f"조달 담당자 {CANARY} 가 계측 설비를 검토 중이다",
                    finding_ids=["f1"],
                    evidence_type=EvidenceType.FACT,
                    confidence=Confidence.MEDIUM,
                )
            )
        else:
            claims.append(
                AnalysisClaim(dimension=dimension, missing_evidence=["확인 필요"])
            )
    return ClientAnalysis(
        project_id=PROJECT,
        client_id="cli_1",
        client_name="Fictional Buyer",
        country="VN",
        industry="water",
        our_solution="센서",
        claims=claims,
        analysis_id="cla_1",
        finding_ids=aggregate_finding_ids(claims),
        missing_evidence=aggregate_missing_evidence(claims),
    )


# -- surface 1: repr ------------------------------------------------------------

def test_a_statement_draft_does_not_print_its_text() -> None:
    draft = StatementDraft(text=f"{CANARY} 를 제안한다", dimensions=[D.PROBLEM])
    assert CANARY not in repr(draft)
    assert "dimensions=1" in repr(draft), "the diagnostic still counts"


def test_an_objection_draft_does_not_print_its_text() -> None:
    draft = ObjectionDraft(
        objection=f"{CANARY} 때문에 곤란하다", basis="ANTICIPATED", response=f"{CANARY} 대응"
    )
    assert CANARY not in repr(draft)
    assert "ANTICIPATED" in repr(draft)


def test_a_diagnostic_reference_is_reduced_to_something_safe() -> None:
    sentence = Rejection("propose_strategy", "X", f"고객이 {CANARY} 라고 말했다")
    assert CANARY not in repr(sentence)
    assert sentence.reference == "<omitted>"


# -- surface 2: rejections from a real run ---------------------------------------

def test_a_refused_element_records_a_key_not_a_sentence(prompts) -> None:
    """A reference key is a safe identifier; anything sentence-shaped is not.

    ``safe_reference`` lets ``S9`` through, which is the point — a diagnostic naming the key
    that failed is useful. A model returning prose where a key belongs gets a placeholder.
    """
    from core.proposal import resolve_elements

    _, rejections = resolve_elements(["S9"], ELEMENTS)
    assert rejections and rejections[0].reference == "S9"

    _, prose = resolve_elements([f"고객이 {CANARY} 라고 말한 모듈"], ELEMENTS)
    assert prose and CANARY not in repr(prose[0])
    assert prose[0].reference == "<omitted>"


# -- surface 3: tracebacks ---------------------------------------------------------

def test_a_traceback_through_the_pipeline_carries_no_strategy_text(prompts) -> None:
    class Exploding(EchoLLM):
        def generate_structured(self, prompt, *, schema, system=None, output_lang="ko"):
            raise RuntimeError("provider unavailable")

    try:
        run_proposal_strategy(
            project=Project(project_id=PROJECT, company_name="Fictional Sensing"),
            analysis=_analysis(),
            solution_elements=ELEMENTS,
            llm=Exploding(),
            prompts=prompts,
        )
    except RuntimeError:
        assert CANARY not in traceback.format_exc()
    else:
        pytest.fail("the exploding provider should have surfaced")


# -- surface 4: storage --------------------------------------------------------------

def test_the_analysis_statement_is_never_copied_into_storage(prompts) -> None:
    """The strategy references claims by dimension; it does not carry their text.

    The canary sits in the analysis's own claim statement. Recorded gaps and selected solution
    elements are persisted deliberately — those are the hand-off — so the leak this looks for
    is specifically a copied claim.
    """
    storage = MemoryStorage()
    outcome = run_proposal_strategy(
        project=Project(project_id=PROJECT, company_name="Fictional Sensing"),
        analysis=_analysis(),
        solution_elements=ELEMENTS,
        llm=EchoLLM(),
        prompts=prompts,
    )
    persist(outcome, storage)
    stored = json.dumps(
        [as_dict(s) for s in storage.get_proposal_strategies(PROJECT)], ensure_ascii=False
    )
    assert CANARY not in stored


# -- surface 5: the summary an operator logs -------------------------------------------

def test_the_run_summary_is_counts_only() -> None:
    outcome = ProposalOutcome()
    outcome.strategies.append(
        ProposalStrategy(
            project_id=PROJECT,
            client_id="cli_1",
            client_name="Fictional Buyer",
            country="VN",
            analysis_id="cla_1",
            key_message=StrategyStatement(
                text=f"{CANARY} 를 제안한다", dimensions=[D.PROBLEM], solution_element_refs=["S1"]
            ),
        )
    )
    outcome.withdrawn_objectives.append(ProposalObjective.FORMAL_PROPOSAL)
    summary = outcome.summary()

    assert CANARY not in json.dumps(summary, ensure_ascii=False)
    assert all(isinstance(value, int) for value in summary.values())


# -- surface 6: no field exists to hold a contact ----------------------------------------

def test_there_is_no_field_for_a_person() -> None:
    """The structural guarantee, and the only one available.

    ``key_message`` and the objections are free text, so this does **not** promise that a name
    never appears in one — see docs/privacy.md, which keeps what the shape guarantees apart
    from what the prompt merely asks for.
    """
    import dataclasses

    from core.models import ProposalObjection, StoryStep

    for cls in (ProposalStrategy, StrategyStatement, StoryStep, ProposalObjection):
        names = {f.name for f in dataclasses.fields(cls)}
        for banned in ("contact_name", "email", "phone", "person_title", "contact"):
            assert banned not in names, f"{cls.__name__} has a field for {banned}"


def test_review_flags_carry_codes_not_positions() -> None:
    flag = ReviewFlag("propose_strategy", "OBJECTIVE_OUTRUNS_EVIDENCE", "BUYER or DECISION_MAKER")
    assert "OBJECTIVE_OUTRUNS_EVIDENCE" in repr(flag)
    assert flag.reference == "BUYER or DECISION_MAKER", "dimension names are safe to record"
