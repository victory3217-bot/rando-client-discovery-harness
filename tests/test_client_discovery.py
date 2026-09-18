# -*- coding: utf-8 -*-
"""Client discovery: criteria, organizations, fit, and the offline runs.

Every organization here is invented. ``Fictional Alpha Water Systems`` and
``Fictional Delta Industrial Services`` exist only in this file.
"""
from __future__ import annotations

import pytest

from adapters.intake import IntakeSession
from adapters.llm.echo import EchoLLM
from adapters.prompts import load_client_prompt_set
from adapters.search.manual import ManualSearch
from adapters.storage.memory import MemoryStorage
from core import evidence
from core.client import (
    AccessRoute,
    DiscoveryPolicy,
    PurchaseSignal,
    assess_fit,
    build_criteria,
    direct_source_ids,
    find_organizations,
    findings_for,
    persist,
    run_discovery,
    verify_mentions,
)
from core.client.models import OrganizationMention
from core.interfaces.search import SearchResult
from core.models import (
    ClientStatus,
    Confidence,
    EvidenceType,
    FileType,
    FitCriterion,
    FitLevel,
    KeyIssue,
    MarketScope,
    Project,
    ResearchFinding,
    SalesPriority,
    SourceCategory,
    SourceOrigin,
    aggregate_finding_ids,
    aggregate_missing_evidence,
)
from core.research import ingest_search_results
from core.research.models import RejectionCode
from scripted_llm import ScriptedLLM

PROJECT = "prj_discovery"
ALPHA = "Fictional Alpha Water Systems"
DELTA = "Fictional Delta Industrial Services"


@pytest.fixture
def prompts(repo_root):
    return load_client_prompt_set(repo_root / "prompts")


@pytest.fixture
def uploaded():
    """A document that names an organization, ingested for real."""
    body = (
        f"{ALPHA}는 건기 염분 상승 구간에서 측정 주기를 늘려야 한다.\n\n"
        f"{ALPHA}의 2026년 조달 공고에 수질 계측 설비 교체가 포함되어 있다.\n\n"
        "현장 인력이 수동 채수에 의존하고 있다.\n"
    )
    with IntakeSession(PROJECT) as session:
        return session.ingest(
            bytearray(body.encode("utf-8")),
            file_type=FileType.TXT,
            source_category=SourceCategory.EXTERNAL_BUSINESS_DATA,
            source_date="2026-04-02",
        )


def _finding(mn: str, text: str, source_id: str, **kwargs) -> ResearchFinding:
    defaults = dict(
        project_id=PROJECT,
        finding=text,
        evidence_type=EvidenceType.FACT,
        mn_basis=[mn],
        confidence=Confidence.MEDIUM,
        source_id=source_id,
    )
    defaults.update(kwargs)
    return ResearchFinding(**defaults)


def _project() -> Project:
    return Project(
        project_id=PROJECT,
        company_name="Fictional Sensing",
        market_scope=[MarketScope.INTERNATIONAL],
        target_countries=["VN"],
    )


def _key_issue() -> KeyIssue:
    return KeyIssue(
        project_id=PROJECT,
        statement="어느 시장을 먼저 볼 것인가",
        decision_area="market_priority",
        swot_issue_ids=["swt_1"],
        strategic_implication="근거는 A를 가리키나 B가 미확인이다",
    )


def _assessment(criterion: str, level: str, refs=None, **extra) -> dict:
    payload = {"criterion": criterion, "level": level, "evidence_refs": refs or [], "reason": "근거 요약"}
    payload.update(extra)
    return payload


def _all_eight(level: str = "UNKNOWN", refs=None, **overrides) -> list[dict]:
    """Eight assessments, with named overrides applied."""
    out = []
    for criterion in FitCriterion:
        payload = overrides.get(criterion.value)
        if payload is None:
            payload = _assessment(criterion.value, level, refs)
        out.append(payload)
    return out


# -- prompts ---------------------------------------------------------------

def test_client_prompts_load_and_stay_provider_neutral(prompts, repo_root) -> None:
    assert prompts.build_criteria and prompts.find_organizations and prompts.assess_fit
    for path in sorted((repo_root / "prompts" / "discovery").glob("*.md")):
        text = path.read_text(encoding="utf-8").lower()
        for vendor in ("claude", "gpt-", "gemini", "anthropic", "openai"):
            assert vendor not in text, f"{path.name} names a provider"


def test_criteria_prompt_forbids_naming_a_company(prompts) -> None:
    assert "do not name any organization" in prompts.build_criteria.lower()


# -- criteria ---------------------------------------------------------------

def test_criteria_provenance_comes_from_the_pipeline(prompts) -> None:
    findings = [_finding("MN03", "측정 주기를 늘려야 한다", "src_1")]
    issues = [_key_issue()]
    llm = ScriptedLLM(
        {
            "criteria": [
                {
                    "relevant_problem": "수동 채수로는 측정 주기를 못 늘린다",
                    "our_capability": "다항목 단일 모듈 측정",
                    "target_industry": "상수도 운영",
                    "purchase_signal": ["PROCUREMENT_ACTIVITY", "NOT_A_SIGNAL"],
                    "access_signal": ["PUBLIC_TENDER"],
                }
            ]
        }
    )
    criteria, records = build_criteria(
        findings, issues, llm=llm, prompts=prompts, project_id=PROJECT,
        capability="다항목 측정", solution="단일 모듈 센서",
    )

    assert criteria is not None
    assert criteria.finding_ids == [findings[0].finding_id]
    assert criteria.key_issue_ids == [issues[0].key_issue_id]
    assert criteria.mn_basis == ["MN03"]
    assert criteria.purchase_signal == [PurchaseSignal.PROCUREMENT_ACTIVITY], "unknown enum dropped"
    assert criteria.access_signal == [AccessRoute.PUBLIC_TENDER]
    assert records


def test_criteria_is_transient(prompts) -> None:
    """No schema, no storage method — it is a specification, not a record."""
    from core.client.models import ClientDiscoveryCriteria

    assert not hasattr(MemoryStorage(), "save_discovery_criteria")
    assert "ClientDiscoveryCriteria" not in {c.__name__ for c in __import__(
        "core.models", fromlist=["ENTITIES"]).ENTITIES}


# -- organizations ----------------------------------------------------------

def test_a_name_in_the_evidence_becomes_an_organization(uploaded, prompts) -> None:
    llm = ScriptedLLM({"organizations": [{"mentions": [{"name": ALPHA, "evidence_ref": "E1"}]}]})
    organizations, hypotheses, rejections, records = find_organizations(
        uploaded.candidates,
        llm=llm,
        prompts=prompts,
        sources_by_id={uploaded.source.source_id: uploaded.source},
    )

    assert rejections == []
    assert len(organizations) == 1
    assert organizations[0].name == ALPHA
    assert organizations[0].source_ids == [uploaded.source.source_id]
    assert organizations[0].snippet_only is False
    assert records


def test_hypotheses_describe_a_type_and_carry_no_name(uploaded, prompts) -> None:
    import dataclasses

    from core.client.models import DiscoveryHypothesis

    llm = ScriptedLLM(
        {"organizations": [{"mentions": [], "hypotheses": [
            {"organization_profile": "교체 계획이 있는 지역 공공 상수도 운영사",
             "required_evidence": ["조달 공고"]}
        ]}]}
    )
    _, hypotheses, _, _ = find_organizations(
        uploaded.candidates, llm=llm, prompts=prompts,
        sources_by_id={uploaded.source.source_id: uploaded.source},
    )

    assert len(hypotheses) == 1
    assert "name" not in {f.name for f in dataclasses.fields(DiscoveryHypothesis)}
    assert hypotheses[0].required_evidence == ["조달 공고"]


def test_mentions_group_into_one_organization() -> None:
    mentions = [
        OrganizationMention(name=ALPHA, evidence_ref="E1", source_id="src_1", locator="line 1"),
        OrganizationMention(name=f"{ALPHA} Co., Ltd.", evidence_ref="E2", source_id="src_2",
                            locator="snippet"),
    ]
    organizations = verify_mentions(mentions)
    assert len(organizations) == 1
    assert set(organizations[0].source_ids) == {"src_1", "src_2"}
    assert organizations[0].snippet_only is False, "one non-snippet source is enough"


def test_snippet_only_organizations_are_marked() -> None:
    organizations = verify_mentions(
        [OrganizationMention(name=DELTA, evidence_ref="E1", source_id="src_9", locator="snippet")]
    )
    assert organizations[0].snippet_only is True


# -- fit --------------------------------------------------------------------

def test_all_eight_criteria_always_come_back(uploaded, prompts) -> None:
    organizations = verify_mentions(
        [OrganizationMention(name=ALPHA, evidence_ref="E1", source_id=uploaded.source.source_id,
                             locator="line 1")]
    )
    llm = ScriptedLLM({"fit": [{"discovery_rationale": "우리 센서를 그들의 수동 채수 문제에",
                                "assessments": [_assessment("PROBLEM_FIT", "UNKNOWN")]}]})
    assessments, rationale, _, _, _ = assess_fit(
        organizations[0], [], llm=llm, prompts=prompts,
        sources_by_id={uploaded.source.source_id: uploaded.source},
    )

    assert len(assessments) == 8
    assert {a.criterion for a in assessments} == set(FitCriterion)
    assert rationale
    unassessed = [a for a in assessments if a.missing_evidence == ["not assessed in this run"]]
    assert len(unassessed) == 7, "a criterion nobody judged says UNKNOWN, it is not absent"


def test_findings_are_selected_by_framework_not_reanalysed() -> None:
    findings = [
        _finding("MN03", "고객 문제", "src_1"),
        _finding("MN05", "접근 경로", "src_1"),
        _finding("MN02", "역량", "src_1"),
    ]
    assert len(findings_for(FitCriterion.PROBLEM_FIT, findings)) == 1
    assert findings_for(FitCriterion.ACCESSIBILITY, findings)[0].mn_basis == ["MN05"]
    assert findings_for(FitCriterion.CAPABILITY_FIT, findings)[0].mn_basis == ["MN02"]
    assert len(findings_for(FitCriterion.EVIDENCE_QUALITY, findings)) == 3


# -- search integration -----------------------------------------------------

def test_search_results_feed_the_same_pipeline() -> None:
    search = ManualSearch(
        [
            SearchResult(
                title="Fictional operations review",
                snippet=f"{DELTA} announced a replacement programme.",
                publisher="Fictional Institute",
                retrieved_at="2026-09-18T00:00:00+00:00",
                country="VN",
                market_scope=MarketScope.INTERNATIONAL,
            )
        ]
    )
    hits = search.search("replacement", scope=MarketScope.INTERNATIONAL)
    sources, candidates = ingest_search_results(hits, project_id=PROJECT)

    assert sources[0].source_origin is SourceOrigin.SEARCH_RESULT
    assert candidates[0].locator == "snippet"
    assert direct_source_ids(sources) == set(), "a search result is not direct provenance"


# -- end to end -------------------------------------------------------------

def test_offline_end_to_end_with_echo(uploaded, prompts) -> None:
    """No API key, no network. The offline provider names nobody, so nobody is a candidate."""
    outcome = run_discovery(
        project=_project(),
        candidates=uploaded.candidates,
        sources=[uploaded.source],
        findings=[_finding("MN03", "문제", uploaded.source.source_id)],
        key_issues=[_key_issue()],
        llm=EchoLLM(),
        prompts=prompts,
        capability="다항목 측정",
        solution="단일 모듈 센서",
    )

    assert outcome.transmissions, "the pipeline must have made calls"
    assert outcome.candidates == [], "an offline provider has no evidence to name anyone from"


def test_offline_end_to_end_with_manual_search(prompts) -> None:
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
    hits = search.search("procurement", scope=MarketScope.INTERNATIONAL)
    sources, candidates = ingest_search_results(hits, project_id=PROJECT)
    findings = [_finding("MN03", "측정 설비 교체 계획", sources[0].source_id)]

    llm = ScriptedLLM(
        {
            "criteria": [{"relevant_problem": "측정 주기", "our_capability": "다항목 측정"}],
            "organizations": [{"mentions": [{"name": ALPHA, "evidence_ref": "E1"}]}],
            "fit": [{
                "discovery_rationale": "우리 센서를 그들의 측정 문제에",
                "assessments": _all_eight(
                    "UNKNOWN",
                    PROBLEM_FIT=_assessment("PROBLEM_FIT", "STRONG", ["F1"]),
                    PURCHASING_POTENTIAL=_assessment(
                        "PURCHASING_POTENTIAL", "STRONG", ["F1"],
                        signal_type="PROCUREMENT_ACTIVITY",
                    ),
                ),
            }],
        }
    )
    outcome = run_discovery(
        project=_project(),
        candidates=candidates,
        sources=sources,
        findings=findings,
        key_issues=[_key_issue()],
        llm=llm,
        prompts=prompts,
        capability="다항목 측정",
        solution="단일 모듈 센서",
        country="VN",
        industry="water utilities",
    )

    assert len(outcome.candidates) == 1
    candidate = outcome.candidates[0]
    assert candidate.client_name == ALPHA
    assert candidate.source_ids == [sources[0].source_id]
    assert candidate.key_issue_ids
    assert evidence.check_client_candidate(candidate) == []
    # Everything about this candidate came from a search snippet.
    assert candidate.priority.band is not SalesPriority.P1


def test_the_pipeline_derives_the_candidate_aggregates(uploaded, prompts) -> None:
    """Candidate-level evidence fields are rolled up, not collected a second time.

    The point is not that the numbers agree today. It is that there is one place the
    relationship lives, so revising an assessment cannot leave a stale copy behind at candidate
    level saying something different.
    """
    findings = [
        _finding("MN03", "측정 주기", uploaded.source.source_id),
        _finding("MN02", "역량", uploaded.source.source_id),
    ]
    llm = ScriptedLLM(
        {
            "criteria": [{"relevant_problem": "측정 주기", "our_capability": "다항목 측정"}],
            "organizations": [{"mentions": [{"name": ALPHA, "evidence_ref": "E1"}]}],
            "fit": [{
                "discovery_rationale": "우리 센서를 그들의 측정 문제에",
                "assessments": _all_eight(
                    "UNKNOWN",
                    PROBLEM_FIT=_assessment("PROBLEM_FIT", "STRONG", ["F1"]),
                    CAPABILITY_FIT=_assessment("CAPABILITY_FIT", "MODERATE", ["F2"]),
                    ACCESSIBILITY={
                        "criterion": "ACCESSIBILITY", "level": "EVIDENCE_NEEDED",
                        "missing_evidence": ["실제 접근 채널"],
                    },
                ),
            }],
        }
    )
    outcome = run_discovery(
        project=_project(),
        candidates=uploaded.candidates,
        sources=[uploaded.source],
        findings=findings,
        key_issues=[_key_issue()],
        llm=llm,
        prompts=prompts,
        capability="다항목 측정",
        solution="단일 모듈 센서",
    )

    candidate = outcome.candidates[0]
    assert candidate.finding_ids == aggregate_finding_ids(candidate.fit)
    assert candidate.finding_ids == sorted(candidate.finding_ids), "sorted, so it is stable"
    assert candidate.missing_evidence == aggregate_missing_evidence(candidate.fit)
    assert candidate.priority.missing_evidence == candidate.missing_evidence
    assert "실제 접근 채널" in candidate.missing_evidence
    assert evidence.check_client_candidate(candidate) == []


def test_an_over_long_rationale_refuses_the_candidate_rather_than_trimming_it(
    uploaded, prompts
) -> None:
    """Nothing is stored, and the reason it was not is recorded under its own code."""
    llm = ScriptedLLM(
        {
            "criteria": [{"relevant_problem": "측정 주기", "our_capability": "다항목 측정"}],
            "organizations": [{"mentions": [{"name": ALPHA, "evidence_ref": "E1"}]}],
            "fit": [{
                "discovery_rationale": "우리 센서를 " * 400,
                "assessments": _all_eight("UNKNOWN"),
            }],
        }
    )
    outcome = run_discovery(
        project=_project(),
        candidates=uploaded.candidates,
        sources=[uploaded.source],
        findings=[_finding("MN03", "문제", uploaded.source.source_id)],
        key_issues=[_key_issue()],
        llm=llm,
        prompts=prompts,
        capability="다항목 측정",
        solution="단일 모듈 센서",
    )

    assert outcome.candidates == []
    codes = [r.code for r in outcome.rejections]
    assert RejectionCode.RATIONALE_TOO_LONG in codes
    assert RejectionCode.EMPTY_STATEMENT not in codes, "it was not empty — name the real fault"
    for rejection in outcome.rejections:
        assert "우리 센서를" not in repr(rejection)


def test_pipeline_persists_only_candidates(uploaded, prompts) -> None:
    storage = MemoryStorage()
    outcome = run_discovery(
        project=_project(),
        candidates=uploaded.candidates,
        sources=[uploaded.source],
        findings=[_finding("MN03", "문제", uploaded.source.source_id)],
        key_issues=[],
        llm=EchoLLM(),
        prompts=prompts,
        capability="c",
        solution="s",
    )
    persist(outcome, storage)
    assert len(storage.get_clients(PROJECT)) == len(outcome.candidates)
    assert not hasattr(storage, "save_discovery_criteria")


def test_outcome_summary_is_counts_only_and_names_nobody(uploaded, prompts) -> None:
    llm = ScriptedLLM({"organizations": [{"mentions": [{"name": ALPHA, "evidence_ref": "E1"}]}]})
    outcome = run_discovery(
        project=_project(),
        candidates=uploaded.candidates,
        sources=[uploaded.source],
        findings=[_finding("MN03", "문제", uploaded.source.source_id)],
        key_issues=[],
        llm=llm,
        prompts=prompts,
        capability="c",
        solution="s",
    )
    summary = outcome.summary()
    assert set(summary) == {
        "candidates", "by_band", "hypotheses", "rejections", "review_flags", "transmissions",
    }
    assert ALPHA not in str(summary)
