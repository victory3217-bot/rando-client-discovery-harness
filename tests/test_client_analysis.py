# -*- coding: utf-8 -*-
"""The deep-analysis pipeline end to end, offline.

No API key and no network in any of these. The echo provider answers nothing useful, which is
the correct behaviour for a provider with no evidence — and the assertions check both that the
calls happened and that the result is empty, because a pipeline that never ran looks identical
to one that found nothing.
"""
from __future__ import annotations

import json

import pytest

from adapters.llm.echo import EchoLLM
from adapters.knowledge.static import StaticKnowledge
from adapters.prompts import load_analysis_prompt_set, load_prompt_set
from adapters.search.manual import ManualSearch
from adapters.storage.memory import MemoryStorage
from core import evidence
from core.analysis import (
    DIMENSION_FRAMEWORK,
    FRAMEWORK_GROUPS,
    AnalysisPolicy,
    dimensions_for,
    persist,
    run_client_analysis,
)
from core.interfaces.search import SearchResult
from core.models import (
    AnalysisDimension,
    ClientCandidate,
    Confidence,
    EvidenceType,
    FitAssessment,
    FitCriterion,
    FitLevel,
    InternationalDimension,
    MarketScope,
    PriorityDecision,
    Project,
    ResearchFinding,
    SalesPriority,
    as_dict,
    from_dict,
)
from scripted_llm import ScriptedLLM

PROJECT = "prj_deep"
ALPHA = "Fictional Alpha Water Systems"
OUR_SOLUTION = "a single-module multi-parameter sensor"


@pytest.fixture
def prompts(repo_root):
    return load_analysis_prompt_set(repo_root / "prompts")


@pytest.fixture
def research_prompts(repo_root):
    return load_prompt_set(repo_root / "prompts")


@pytest.fixture
def knowledge(repo_root):
    return StaticKnowledge.from_directory(repo_root / "knowledge" / "master-notes")


def _project(scope: MarketScope = MarketScope.DOMESTIC) -> Project:
    return Project(project_id=PROJECT, company_name="Fictional Sensing", market_scope=[scope])


def _candidate(client_id: str = "cli_1") -> ClientCandidate:
    return ClientCandidate(
        project_id=PROJECT,
        client_name=ALPHA,
        country="VN",
        industry="water utilities",
        discovery_rationale="their measurement problem matches our capability",
        source_ids=["src_1"],
        fit=[FitAssessment(criterion=c, level=FitLevel.UNKNOWN) for c in FitCriterion],
        priority=PriorityDecision(band=SalesPriority.P2),
        client_id=client_id,
    )


def _finding(finding_id: str, mn: str, text: str, source_id: str | None = "src_1"):
    return ResearchFinding(
        project_id=PROJECT,
        finding=text,
        evidence_type=EvidenceType.FACT,
        confidence=Confidence.MEDIUM,
        mn_basis=[mn],
        source_id=source_id,
        finding_id=finding_id,
    )


def _claims(*claims) -> dict:
    return {"claims": list(claims)}


def _run(llm, prompts, *, candidate=None, findings=None, scope=MarketScope.DOMESTIC, **kwargs):
    candidate = candidate or _candidate()
    return run_client_analysis(
        project=_project(scope),
        client_ids=[candidate.client_id],
        candidates=[candidate],
        findings=findings or [],
        sources=[],
        our_solution=OUR_SOLUTION,
        capability="multi-parameter measurement",
        llm=llm,
        prompts=prompts,
        market_scope=scope,
        **kwargs,
    )


# -- shape -------------------------------------------------------------------

def test_there_are_nineteen_dimensions_in_four_groups() -> None:
    assert len(list(AnalysisDimension)) == 19
    grouped = [d for fid in FRAMEWORK_GROUPS for d in dimensions_for(fid)]
    assert sorted(d.value for d in grouped) == sorted(d.value for d in AnalysisDimension)
    assert set(DIMENSION_FRAMEWORK.values()) == set(FRAMEWORK_GROUPS)


def test_every_dimension_comes_back_even_when_nothing_answered_it(prompts) -> None:
    outcome = _run(EchoLLM(), prompts)
    assert len(outcome.analyses) == 1
    analysis = outcome.analyses[0]
    assert len(analysis.claims) == 19
    assert {c.dimension for c in analysis.claims} == set(AnalysisDimension)


def test_one_call_per_framework_group(prompts) -> None:
    """Nineteen answers in one response get the last few filled in carelessly."""
    outcome = _run(EchoLLM(), prompts)
    stages = [record.stage for record in outcome.transmissions]
    assert stages == [f"analyze_client_{fid.lower()}" for fid in FRAMEWORK_GROUPS]


def test_the_claims_are_ordered_for_grouping(prompts) -> None:
    """A mobile card list groups by Master Note; the order makes that a slice, not a sort."""
    outcome = _run(EchoLLM(), prompts)
    order = [c.dimension for c in outcome.analyses[0].claims]
    assert order == list(AnalysisDimension)


# -- offline end to end -------------------------------------------------------

def test_offline_end_to_end_with_echo(prompts) -> None:
    """No API key, no network. The offline provider settles nothing, so nothing is settled."""
    outcome = _run(EchoLLM(), prompts, findings=[_finding("f1", "MN03", "수동 채수에 의존한다")])

    assert outcome.transmissions, "the pipeline must have made calls"
    analysis = outcome.analyses[0]
    settled = [c for c in analysis.claims if c.statement]
    assert settled == [], "an offline provider has no evidence to settle anything from"
    assert all(c.missing_evidence for c in analysis.claims)


def test_offline_end_to_end_with_manual_search(prompts, research_prompts, knowledge) -> None:
    """Search, ingest and extract are the Phase 3 machinery, unchanged."""
    search = ManualSearch(
        [
            SearchResult(
                title="Fictional operations review",
                snippet=f"{ALPHA} published a 2026 procurement notice for measurement equipment.",
                publisher="Fictional Institute",
                published_date="2026-04-02",
                retrieved_at="2026-09-18T00:00:00+00:00",
                country="VN",
                market_scope=MarketScope.INTERNATIONAL,
            )
        ]
    )
    llm = ScriptedLLM(
        {
            "queries": [
                {
                    "queries": [
                        {
                            "query": "procurement notice",
                            "target_dimension": "PROCUREMENT_CONTEXT",
                        }
                    ]
                }
            ],
            "claims": [_claims()],
        }
    )
    outcome = run_client_analysis(
        project=_project(MarketScope.INTERNATIONAL),
        client_ids=["cli_1"],
        candidates=[_candidate()],
        findings=[],
        sources=[],
        our_solution=OUR_SOLUTION,
        capability="multi-parameter measurement",
        llm=llm,
        prompts=prompts,
        research_prompts=research_prompts,
        knowledge=knowledge,
        search=search,
        market_scope=MarketScope.INTERNATIONAL,
    )

    assert outcome.criteria and outcome.criteria[0].queries
    assert outcome.sources, "the search results became sources"
    assert all(s.source_origin.value == "SEARCH_RESULT" for s in outcome.sources)
    assert outcome.analyses


def test_search_is_optional(prompts) -> None:
    """A classroom without network access still runs the analysis on existing findings."""
    outcome = _run(EchoLLM(), prompts, findings=[_finding("f1", "MN03", "문제")])
    assert outcome.criteria == [], "no criteria stage without a provider"
    assert outcome.analyses


# -- a settled analysis -------------------------------------------------------

def _settling_llm() -> ScriptedLLM:
    return ScriptedLLM(
        {
            "claims": [
                _claims(
                    {
                        "dimension": "PROBLEM",
                        "statement": "건기에 측정 주기를 늘려야 하는데 수동 채수에 의존한다",
                        "evidence_refs": ["F1"],
                    },
                    {"dimension": "KBF", "statement": "유지보수 편의", "evidence_refs": ["F1"]},
                ),
                _claims(
                    {
                        "dimension": "COMPETITOR",
                        "statement": "현지 공급사가 단항목 측정기를 공급한다",
                        "evidence_refs": ["F1"],
                        "organization_name": ALPHA,
                    },
                ),
                _claims(
                    {
                        "dimension": "SALES_ACCESS_ROUTE",
                        "statement": "공개 입찰 공고를 통해 접근 가능하다",
                        "evidence_refs": ["F1"],
                        "access_route": "PUBLIC_TENDER",
                    },
                ),
                _claims(),
            ]
        }
    )


def test_a_settled_claim_keeps_its_evidence(prompts) -> None:
    findings = [
        _finding("f1", "MN03", "건기에 측정 주기를 늘려야 하는데 수동 채수에 의존한다"),
    ]
    outcome = _run(_settling_llm(), prompts, findings=findings)
    analysis = outcome.analyses[0]
    problem = analysis.claim_for(AnalysisDimension.PROBLEM)
    assert problem.statement
    assert problem.finding_ids == ["f1"]
    assert problem.evidence_type is EvidenceType.FACT
    assert problem.framework_basis == ["MN03"]


def test_an_access_route_is_a_named_route(prompts) -> None:
    findings = [_finding("f1", "MN05", f"{ALPHA}의 공개 입찰 공고가 게시되었다")]
    outcome = _run(_settling_llm(), prompts, findings=findings)
    route = outcome.analyses[0].claim_for(AnalysisDimension.SALES_ACCESS_ROUTE)
    assert route.access_route is not None and route.access_route.value == "PUBLIC_TENDER"


def test_the_analysis_validates_against_its_own_invariants(prompts) -> None:
    findings = [_finding("f1", "MN03", "수동 채수에 의존한다")]
    outcome = _run(_settling_llm(), prompts, findings=findings)
    by_id = {f.finding_id: f for f in findings}
    assert evidence.check_client_analysis(outcome.analyses[0], known_finding_ids=by_id) == []


# -- international -------------------------------------------------------------

def test_international_uses_the_same_engine(prompts) -> None:
    outcome = _run(EchoLLM(), prompts, scope=MarketScope.INTERNATIONAL)
    analysis = outcome.analyses[0]
    assert len(analysis.claims) == 19, "the common dimensions are unchanged"
    assert len(analysis.international_claims) == 8
    assert {c.dimension for c in analysis.international_claims} == set(InternationalDimension)


def test_a_domestic_run_produces_no_international_claims(prompts) -> None:
    outcome = _run(EchoLLM(), prompts, scope=MarketScope.DOMESTIC)
    assert outcome.analyses[0].international_claims == []


def test_the_international_call_is_one_extra_call(prompts) -> None:
    domestic = _run(EchoLLM(), prompts, scope=MarketScope.DOMESTIC)
    overseas = _run(EchoLLM(), prompts, scope=MarketScope.INTERNATIONAL)
    assert len(overseas.transmissions) == len(domestic.transmissions) + 1


# -- persistence and serialization ----------------------------------------------

def test_only_analyses_reach_storage(prompts) -> None:
    storage = MemoryStorage()
    outcome = _run(EchoLLM(), prompts)
    persist(outcome, storage)
    assert len(storage.get_client_analyses(PROJECT)) == len(outcome.analyses)
    assert not hasattr(storage, "save_analysis_claim")
    assert not hasattr(storage, "save_partner_profile")


def test_the_analysis_round_trips_through_json(prompts) -> None:
    """Two enums on one nested object, which is where a serializer usually breaks."""
    from core.models import ClientAnalysis

    findings = [_finding("f1", "MN05", f"{ALPHA}의 공개 입찰 공고가 게시되었다")]
    outcome = _run(
        _settling_llm(), prompts, findings=findings, scope=MarketScope.INTERNATIONAL
    )
    original = outcome.analyses[0]

    payload = json.loads(json.dumps(as_dict(original), ensure_ascii=False))
    restored = from_dict(ClientAnalysis, payload)

    assert restored == original
    assert isinstance(restored.claims[0].dimension, AnalysisDimension)
    assert isinstance(restored.international_claims[0].dimension, InternationalDimension)
    route = restored.claim_for(AnalysisDimension.SALES_ACCESS_ROUTE)
    assert route.access_route is not None and route.access_route.value == "PUBLIC_TENDER"
    assert isinstance(restored.claims[0].evidence_type, EvidenceType)
    assert isinstance(restored.claims[0].confidence, Confidence)


def test_the_sample_analysis_loads_and_validates(repo_root) -> None:
    from core.models import ClientAnalysis

    path = repo_root / "examples" / "sample_project" / "client_analysis.json"
    records = json.loads(path.read_text(encoding="utf-8"))
    for record in records:
        analysis = from_dict(ClientAnalysis, record)
        assert evidence.check_client_analysis(analysis) == []
        assert len(analysis.claims) == 19


# -- language ------------------------------------------------------------------

def test_every_dimension_has_a_label_in_both_languages(repo_root) -> None:
    for lang in ("ko", "en"):
        with (repo_root / "locales" / f"{lang}.json").open(encoding="utf-8") as fh:
            enums = json.load(fh)["enums"]
        for dimension in AnalysisDimension:
            assert dimension.value in enums["AnalysisDimension"], f"{lang}: {dimension.value}"
        for dimension in InternationalDimension:
            assert dimension.value in enums["InternationalDimension"], f"{lang}: {dimension.value}"


def test_the_core_writes_no_user_facing_prose(prompts) -> None:
    """Gap placeholders are English identifiers, not sentences for a reader."""
    outcome = _run(EchoLLM(), prompts)
    for claim in outcome.analyses[0].claims:
        for gap in claim.missing_evidence:
            assert gap.isascii(), "a Korean sentence in the core belongs in locales/*.json"


def test_the_policy_refuses_a_nonsensical_limit() -> None:
    with pytest.raises(ValueError):
        AnalysisPolicy(max_clients_per_run=0)
