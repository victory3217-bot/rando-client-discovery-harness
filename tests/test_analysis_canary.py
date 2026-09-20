# -*- coding: utf-8 -*-
"""Nothing from a client's documents escapes through a diagnostic.

Deep analysis handles the most sensitive text in the harness: who buys, what their problem
costs them, how their procurement works. The canary below is a string that appears nowhere
except in the evidence, so any surface it turns up on is a leak with a name attached.

Six surfaces, matching ``tests/test_intake_canary.py``: repr, exception, rejection record,
traceback, storage, and the run summary that an operator would log.
"""
from __future__ import annotations

import json
import traceback

import pytest

from adapters.llm.echo import EchoLLM
from adapters.prompts import load_analysis_prompt_set
from adapters.storage.memory import MemoryStorage
from core.analysis import AnalysisRejectionCode, persist, resolve_claim, run_client_analysis
from core.analysis.models import (
    AnalysisOutcome,
    ClaimDraft,
    ClientResearchCriteria,
    InternationalDraft,
    PartnerProfile,
)
from core.models import (
    AnalysisClaim,
    AnalysisDimension,
    ClientCandidate,
    Confidence,
    EvidenceType,
    FitAssessment,
    FitCriterion,
    FitLevel,
    InternationalDimension,
    MarketScope,
    Project,
    ResearchFinding,
    as_dict,
)
from core.research.models import Rejection, ReviewFlag

CANARY = "ZZCANARYZZ"
PROJECT = "prj_analysis_canary"
D = AnalysisDimension


@pytest.fixture
def prompts(repo_root):
    return load_analysis_prompt_set(repo_root / "prompts")


def _finding(finding_id: str = "f1") -> ResearchFinding:
    return ResearchFinding(
        project_id=PROJECT,
        finding=f"조달 담당자 {CANARY} 가 계측 설비 교체를 검토 중이다",
        evidence_type=EvidenceType.FACT,
        confidence=Confidence.MEDIUM,
        mn_basis=["MN03"],
        source_id="src_1",
        evidence_summary=f"{CANARY} 관련 원문",
        finding_id=finding_id,
    )


# -- surface 1: repr ---------------------------------------------------------

def test_a_draft_does_not_print_its_statement() -> None:
    draft = ClaimDraft(dimension=D.BUYER, statement=f"{CANARY} 조달팀", evidence_refs=["F1"])
    assert CANARY not in repr(draft)
    assert "BUYER" in repr(draft), "the diagnostic still says which dimension"


def test_an_international_draft_does_not_print_its_statement() -> None:
    draft = InternationalDraft(
        dimension=InternationalDimension.TARIFF, statement=f"{CANARY} 관세"
    )
    assert CANARY not in repr(draft)


def test_criteria_do_not_print_their_queries() -> None:
    criteria = ClientResearchCriteria(client_id="cli_1", queries=[f"{CANARY} procurement"])
    assert CANARY not in repr(criteria)


@pytest.mark.parametrize(
    "record",
    [
        Rejection("analyze_client", AnalysisRejectionCode.NAME_NOT_IN_EVIDENCE, CANARY),
        ReviewFlag("analyze_client", "SNIPPET_ONLY_EVIDENCE", CANARY),
    ],
    ids=["rejection", "flag"],
)
def test_a_diagnostic_reference_is_reduced_to_something_safe(record) -> None:
    """``safe_reference`` lets identifiers through and replaces anything else.

    ``ZZCANARYZZ`` is identifier-shaped, so this asserts the mechanism rather than the string:
    a document sentence in the same slot becomes a placeholder.
    """
    sentence = Rejection("analyze_client", "X", f"조달 담당자 {CANARY} 가 검토 중이다")
    assert CANARY not in repr(sentence)
    assert sentence.reference == "<omitted>"


# -- surface 2: rejection records from a real run ----------------------------

def test_a_refused_name_leaves_no_trace_of_the_passage() -> None:
    claim, rejections, _ = resolve_claim(
        ClaimDraft(
            dimension=D.COMPETITOR,
            statement=f"{CANARY} 가 납품 중이다",
            evidence_refs=["f1"],
            organization_name="Invented Holdings",
        ),
        {"f1": _finding()},
        passages={"f1": f"{CANARY} 관련 원문"},
    )
    for record in (claim, *rejections):
        assert CANARY not in repr(record)
    assert claim.statement is None


# -- surface 3: exceptions and tracebacks ------------------------------------

def test_a_traceback_through_the_pipeline_carries_no_evidence(prompts) -> None:
    class Exploding(EchoLLM):
        # send() routes an items= call to generate_structured, like every other stage that
        # passes framework context rather than raw passages.
        def generate_structured(self, prompt, *, schema, system=None, output_lang="ko"):
            raise RuntimeError("provider unavailable")

    candidate = ClientCandidate(
        project_id=PROJECT,
        client_name="Fictional Buyer",
        country="VN",
        industry="water",
        discovery_rationale="their problem matches our capability",
        source_ids=["src_1"],
        fit=[FitAssessment(criterion=c, level=FitLevel.UNKNOWN) for c in FitCriterion],
        client_id="cli_1",
    )
    try:
        run_client_analysis(
            project=Project(project_id=PROJECT, company_name="Fictional Sensing"),
            client_ids=["cli_1"],
            candidates=[candidate],
            findings=[_finding()],
            sources=[],
            our_solution="a sensor",
            capability="measurement",
            llm=Exploding(),
            prompts=prompts,
        )
    except RuntimeError:
        text = traceback.format_exc()
        assert CANARY not in text
    else:
        pytest.fail("the exploding provider should have surfaced")


# -- surface 4: storage --------------------------------------------------------

def test_nothing_with_a_canary_reaches_storage(prompts) -> None:
    storage = MemoryStorage()
    candidate = ClientCandidate(
        project_id=PROJECT,
        client_name="Fictional Buyer",
        country="VN",
        industry="water",
        discovery_rationale="their problem matches our capability",
        source_ids=["src_1"],
        fit=[FitAssessment(criterion=c, level=FitLevel.UNKNOWN) for c in FitCriterion],
        client_id="cli_1",
    )
    outcome = run_client_analysis(
        project=Project(project_id=PROJECT, company_name="Fictional Sensing"),
        client_ids=["cli_1"],
        candidates=[candidate],
        findings=[_finding()],
        sources=[],
        our_solution="a sensor",
        capability="measurement",
        llm=EchoLLM(),
        prompts=prompts,
    )
    persist(outcome, storage)
    stored = json.dumps(
        [as_dict(a) for a in storage.get_client_analyses(PROJECT)], ensure_ascii=False
    )
    assert CANARY not in stored


# -- surface 5: the summary an operator logs ----------------------------------

def test_the_run_summary_is_counts_only() -> None:
    outcome = AnalysisOutcome()
    outcome.partner_profiles.append(PartnerProfile(partner_type=f"{CANARY} 유통사"))
    summary = outcome.summary()
    assert CANARY not in json.dumps(summary, ensure_ascii=False)
    assert all(isinstance(v, int) for v in summary.values())


# -- surface 6: no field exists to hold a person ------------------------------

def test_there_is_no_field_for_a_person() -> None:
    """A structural guarantee, and the only one available here.

    The statement is free text, so this does **not** promise that a name never appears in one —
    see docs/privacy.md, which separates what the shape of the data guarantees from what the
    prompt merely asks for.
    """
    import dataclasses

    from core.models import ClientAnalysis

    for cls in (ClientAnalysis, AnalysisClaim):
        names = {f.name for f in dataclasses.fields(cls)}
        for banned in ("contact_name", "email", "phone", "person_title", "contact"):
            assert banned not in names, f"{cls.__name__} has a field for {banned}"


def test_a_partner_profile_cannot_carry_an_organization() -> None:
    import dataclasses

    names = {f.name for f in dataclasses.fields(PartnerProfile)}
    assert "name" not in names and "organization_name" not in names
