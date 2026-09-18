# -*- coding: utf-8 -*-
"""What the pipeline refuses to keep.

A language model asked for structured output will produce structured output, whether or not it
has grounds for it. Schema validation catches a wrong *shape*; these tests cover the harder
case — a well-formed answer that cites something which does not exist, or claims more certainty
than the evidence carries.

What this can and cannot do is worth being clear about. Every rule here blocks an *unsupported*
claim. None of them can catch a *wrong reading* of a passage that really was supplied: that is
a judgement, which is why the output is for a person to review and why nothing in this harness
decides anything.
"""
from __future__ import annotations

import pytest

from adapters.intake import IntakeSession
from adapters.prompts import load_prompt_set
from core import evidence
from core.models import (
    Confidence,
    EvidenceType,
    FileType,
    KeyIssue,
    ResearchFinding,
    SourceCategory,
    SourceMetadata,
    SourceOrigin,
    SWOTCategory,
    SWOTIssue,
)
from core.research import (
    SNIPPET_LOCATOR,
    ConfidenceSignals,
    FlagCode,
    RejectionCode,
    ReviewFlag,
    ResearchPolicy,
    cap,
    ceiling_for,
    classify_swot,
    derive_key_issues,
    extract_findings,
    infer_findings,
    looks_like_a_directive,
    reasons_for,
)
from scripted_llm import ScriptedLLM

PROJECT = "prj_validation"
TODAY = "2026-09-18"


@pytest.fixture
def prompts(repo_root):
    return load_prompt_set(repo_root / "prompts")


@pytest.fixture
def knowledge(repo_root):
    from adapters.knowledge.static import StaticKnowledge

    return StaticKnowledge.from_directory(repo_root / "knowledge" / "master-notes")


@pytest.fixture
def ingested():
    with IntakeSession(PROJECT) as session:
        return session.ingest(
            bytearray("확인 가능한 문장 하나.\n\n두 번째 문장.".encode("utf-8")),
            file_type=FileType.TXT,
            source_category=SourceCategory.EXTERNAL_BUSINESS_DATA,
            source_date="2026-04-02",
        )


def _extract(ingested, prompts, knowledge, payload, **kwargs):
    llm = ScriptedLLM({"extract": [payload]})
    return extract_findings(
        ingested.candidates,
        knowledge.get_framework("MN03"),
        llm=llm,
        prompts=prompts,
        project_id=PROJECT,
        sources_by_id={ingested.source.source_id: ingested.source},
        today=TODAY,
        **kwargs,
    )


# -- fabricated references --------------------------------------------------

def test_fact_citing_an_unknown_passage_is_dropped(ingested, prompts, knowledge) -> None:
    """The characteristic failure: a confident claim citing evidence never sent."""
    findings, rejections, _ = _extract(
        ingested, prompts, knowledge,
        {"findings": [ScriptedLLM.fact("E99", "존재하지 않는 근거를 인용한 주장")]},
    )
    assert findings == []
    assert rejections and rejections[0].code == RejectionCode.UNKNOWN_EVIDENCE_REF


def test_fact_with_no_reference_at_all_is_dropped(ingested, prompts, knowledge) -> None:
    findings, rejections, _ = _extract(
        ingested, prompts, knowledge,
        {"findings": [{"evidence_ref": None, "finding": "출처 없는 사실",
                       "evidence_type": "FACT", "confidence": "HIGH"}]},
    )
    assert findings == []
    assert rejections


def test_unusable_evidence_type_is_dropped(ingested, prompts, knowledge) -> None:
    findings, rejections, _ = _extract(
        ingested, prompts, knowledge,
        {"findings": [{"evidence_ref": "E1", "finding": "x",
                       "evidence_type": "DEFINITELY_TRUE", "confidence": "HIGH"}]},
    )
    assert findings == []
    assert rejections and rejections[0].code == RejectionCode.UNUSABLE_EVIDENCE_TYPE


def test_empty_statement_is_dropped(ingested, prompts, knowledge) -> None:
    findings, rejections, _ = _extract(
        ingested, prompts, knowledge,
        {"findings": [{"evidence_ref": "E1", "finding": "   ",
                       "evidence_type": "FACT", "confidence": "HIGH"}]},
    )
    assert findings == [] and rejections


def test_one_bad_finding_does_not_lose_the_good_ones(ingested, prompts, knowledge) -> None:
    findings, rejections, _ = _extract(
        ingested, prompts, knowledge,
        {"findings": [
            ScriptedLLM.fact("E99", "지어낸 인용"),
            ScriptedLLM.fact("E1", "실제 근거가 있는 사실"),
        ]},
    )
    assert len(findings) == 1 and len(rejections) == 1


def test_rejections_are_recorded_not_silently_discarded(ingested, prompts, knowledge) -> None:
    """A run that quietly drops half its output looks like a run that produced little."""
    _, rejections, _ = _extract(
        ingested, prompts, knowledge,
        {"findings": [ScriptedLLM.fact("E42", "x"), ScriptedLLM.fact("E43", "y")]},
    )
    assert len(rejections) == 2
    assert all(r.stage == "extract_findings" and r.code for r in rejections)


def test_inference_citing_unknown_findings_is_dropped(prompts, knowledge) -> None:
    fact = ResearchFinding(
        project_id=PROJECT, finding="근거", evidence_type=EvidenceType.FACT,
        mn_basis=["MN04"], source_id="src_1",
    )
    llm = ScriptedLLM({"infer": [{"inferences": [ScriptedLLM.inference(["F99"], "근거 없는 추론")]}]})
    inferences, rejections, _ = infer_findings(
        [fact], knowledge.get_framework("MN04"), llm=llm, prompts=prompts, project_id=PROJECT
    )
    assert inferences == [] and rejections


def test_swot_citing_unknown_findings_is_dropped(prompts) -> None:
    fact = ResearchFinding(
        project_id=PROJECT, finding="근거", evidence_type=EvidenceType.FACT,
        mn_basis=["MN02"], source_id="src_1",
    )
    llm = ScriptedLLM({"swot": [{"items": [ScriptedLLM.swot_item("STRENGTH", "강점", ["F99"])]}]})
    issues, rejections, _ = classify_swot([fact], llm=llm, prompts=prompts, project_id=PROJECT)
    assert issues == []
    assert rejections and rejections[0].code == RejectionCode.NO_FINDING_RESOLVED


def test_key_issue_citing_unknown_swot_is_dropped(prompts) -> None:
    swot = SWOTIssue(project_id=PROJECT, category=SWOTCategory.STRENGTH,
                     statement="강점", finding_ids=["fnd_1"])
    llm = ScriptedLLM(
        {"key_issue": [{"issues": [ScriptedLLM.key_issue("질문", ["S99"])]}]}
    )
    issues, rejections, _flags, _ = derive_key_issues([swot], [], llm=llm, prompts=prompts, project_id=PROJECT)
    assert issues == [] and rejections


def test_key_issue_without_a_decision_area_is_dropped(prompts) -> None:
    swot = SWOTIssue(project_id=PROJECT, category=SWOTCategory.STRENGTH,
                     statement="강점", finding_ids=["fnd_1"])
    llm = ScriptedLLM(
        {"key_issue": [{"issues": [ScriptedLLM.key_issue("질문", ["S1"], decision_area="  ")]}]}
    )
    issues, rejections, _flags, _ = derive_key_issues([swot], [], llm=llm, prompts=prompts, project_id=PROJECT)
    assert issues == []
    assert rejections and rejections[0].code == RejectionCode.MISSING_DECISION_AREA


# -- directive wording is advisory, never a rejection ----------------------

@pytest.mark.parametrize("text", ["지금 결정한다", "we will pursue it", "we should enter Vietnam"])
def test_obvious_directives_still_raise_the_flag(text: str) -> None:
    assert looks_like_a_directive(text)


@pytest.mark.parametrize(
    "text",
    [
        "현재 근거로는 A가 긍정적이나 B·C가 부족하므로 추가 검증이 필요하다",
        "인증 요건을 먼저 확인해야 한다",
        "구매 예산을 확인해야 합니다",
        "this needs to be verified before client discovery",
        "on current evidence this looks favourable, but two conditions are unverified",
    ],
)
def test_decision_support_is_not_treated_as_a_directive(text: str) -> None:
    """Saying something must be *checked* is support; a lexical blacklist confuses the two.

    An earlier version of this rule matched on 해야 한다 and rejected
    인증 요건을 먼저 확인해야 한다, which is exactly the output wanted.
    """
    assert not looks_like_a_directive(text)


def test_a_flagged_implication_is_kept_not_discarded(prompts) -> None:
    """Wording raises a review flag. The record stands; a person decides."""
    swot = SWOTIssue(project_id=PROJECT, category=SWOTCategory.OPPORTUNITY,
                     statement="기회", finding_ids=["fnd_1"])
    llm = ScriptedLLM(
        {"key_issue": [{"issues": [
            ScriptedLLM.key_issue("질문", ["S1"], implication="우리는 이 시장을 추진한다")
        ]}]}
    )
    issues, rejections, flags, _ = derive_key_issues(
        [swot], [], llm=llm, prompts=prompts, project_id=PROJECT
    )

    assert len(issues) == 1, "a wording hint must not destroy the record"
    assert issues[0].strategic_implication == "우리는 이 시장을 추진한다"
    assert rejections == []
    assert flags and flags[0].code == FlagCode.IMPLICATION_READS_AS_DIRECTIVE
    assert isinstance(flags[0], ReviewFlag)


# -- a key issue is stored whole or not at all -----------------------------

@pytest.mark.parametrize("implication", [None, "", "   "])
def test_key_issue_without_an_implication_is_rejected_entirely(prompts, implication) -> None:
    """No partial entity. Storage must never hold a KeyIssue that fails its own schema."""
    swot = SWOTIssue(project_id=PROJECT, category=SWOTCategory.OPPORTUNITY,
                     statement="기회", finding_ids=["fnd_1"])
    llm = ScriptedLLM(
        {"key_issue": [{"issues": [
            ScriptedLLM.key_issue("질문", ["S1"], implication=implication)
        ]}]}
    )
    issues, rejections, flags, _ = derive_key_issues(
        [swot], [], llm=llm, prompts=prompts, project_id=PROJECT
    )

    assert issues == []
    assert rejections and rejections[0].code == RejectionCode.MISSING_STRATEGIC_IMPLICATION
    assert flags == []


def test_a_rejected_key_issue_never_reaches_storage(prompts, knowledge) -> None:
    """End to end: the pipeline persists nothing for a refused candidate."""
    from adapters.storage.memory import MemoryStorage
    from core.models import MarketScope, Project
    from core.research import persist, run_research

    llm = ScriptedLLM(
        {
            "extract": [{"findings": [ScriptedLLM.gap("인증 요건 미확인", "인증 목록 필요")]}],
            "swot": [{"items": [ScriptedLLM.swot_item("THREAT", "진입 불확실", ["F1"])]}],
            "key_issue": [{"issues": [ScriptedLLM.key_issue("질문", ["S1"], implication=None)]}],
        }
    )
    with IntakeSession(PROJECT) as session:
        result = session.ingest(
            bytearray("확인 가능한 문장.".encode("utf-8")),
            file_type=FileType.TXT,
            source_category=SourceCategory.EXTERNAL_BUSINESS_DATA,
        )

    outcome = run_research(
        project=Project(project_id=PROJECT, company_name="Fictional",
                        market_scope=[MarketScope.INTERNATIONAL]),
        candidates=result.candidates,
        sources=[result.source],
        knowledge=knowledge,
        llm=llm,
        prompts=prompts,
        frameworks=["MN02"],
        include_inferences=False,
    )

    storage = MemoryStorage()
    persist(outcome, storage)

    assert outcome.key_issues == []
    assert storage.get_key_issues(PROJECT) == []
    assert any(r.code == RejectionCode.MISSING_STRATEGIC_IMPLICATION for r in outcome.rejections)


def test_every_stored_key_issue_satisfies_its_schema(prompts, repo_root) -> None:
    """Whatever survives the pipeline must validate completely, not mostly."""
    import json

    from jsonschema import Draft202012Validator

    from core.models import as_dict

    schema = json.loads(
        (repo_root / "schemas" / "key_issue.schema.json").read_text(encoding="utf-8")
    )
    swot = SWOTIssue(project_id=PROJECT, category=SWOTCategory.OPPORTUNITY,
                     statement="기회", finding_ids=["fnd_1"])
    llm = ScriptedLLM(
        {"key_issue": [{"issues": [
            ScriptedLLM.key_issue("어느 시장을 먼저 볼 것인가", ["S1"]),
            ScriptedLLM.key_issue("두 번째 질문", ["S1"], implication=None),
        ]}]}
    )
    issues, rejections, _flags, _ = derive_key_issues(
        [swot], [], llm=llm, prompts=prompts, project_id=PROJECT
    )

    assert len(issues) == 1 and len(rejections) == 1
    for issue in issues:
        Draft202012Validator(schema).validate(as_dict(issue))


def test_rejections_carry_no_document_text(prompts) -> None:
    """A diagnostic that quotes the document defeats the logging rules."""
    canary = "ZQX-KEYISSUE-CANARY-51bd"
    swot = SWOTIssue(project_id=PROJECT, category=SWOTCategory.OPPORTUNITY,
                     statement="기회", finding_ids=["fnd_1"])
    llm = ScriptedLLM(
        {"key_issue": [{"issues": [
            ScriptedLLM.key_issue(canary, ["S1"], implication=None)
        ]}]}
    )
    _, rejections, _flags, _ = derive_key_issues(
        [swot], [], llm=llm, prompts=prompts, project_id=PROJECT
    )
    assert rejections
    for rejection in rejections:
        assert canary not in str(rejection) and canary not in repr(rejection)


# -- search snippets cannot be verified, so they cannot be HIGH ------------

def _snippet_source(**kwargs) -> SourceMetadata:
    base = dict(
        project_id=PROJECT,
        source_origin=SourceOrigin.SEARCH_RESULT,
        source_category=SourceCategory.EXTERNAL_BUSINESS_DATA,
        title="Fictional operations review",
        publisher="Fictional Institute",
        retrieved_at="2026-09-18T00:00:00+00:00",
        source_date="2026-09-01",
    )
    base.update(kwargs)
    return SourceMetadata(**base)


def test_a_search_snippet_cannot_reach_high_however_good_it_looks() -> None:
    """Publisher, corroboration and recency all satisfied - and still MEDIUM.

    Nothing in this harness has opened the page; a snippet is the few lines a search engine
    chose to show. A later phase that actually retrieves the document would record a different
    origin and could reach HIGH.
    """
    signals = ConfidenceSignals(
        source=_snippet_source(),
        corroborating_source_count=9,
        today=TODAY,
        locator=SNIPPET_LOCATOR,
    )
    assert ceiling_for(EvidenceType.FACT, signals) is Confidence.MEDIUM
    assert "snippet" in reasons_for(EvidenceType.FACT, signals)[0]


def test_the_snippet_cap_survives_a_permissive_policy() -> None:
    policy = ResearchPolicy(corroboration_for_high=1, stale_source_years=100)
    signals = ConfidenceSignals(
        source=_snippet_source(), corroborating_source_count=5, today=TODAY,
        locator=SNIPPET_LOCATOR,
    )
    assert ceiling_for(EvidenceType.FACT, signals, policy=policy) is Confidence.MEDIUM


def test_the_cap_is_about_the_snippet_not_the_origin() -> None:
    """A SEARCH_RESULT source with real document provenance is not capped by this rule."""
    signals = ConfidenceSignals(
        source=_snippet_source(), corroborating_source_count=2, today=TODAY, locator="p.4"
    )
    assert ceiling_for(EvidenceType.FACT, signals) is Confidence.HIGH


def test_a_fact_extracted_from_a_search_snippet_comes_out_medium(prompts, knowledge) -> None:
    """The rule reaching all the way through the pipeline, not just the helper."""
    from core.interfaces.search import SearchResult
    from core.research import ingest_search_results

    sources, candidates = ingest_search_results(
        [
            SearchResult(
                title="Fictional operations review",
                snippet="메콩델타 사업자는 수동 채수에 의존한다.",
                publisher="Fictional Institute",
                published_date="2026-09-01",
                retrieved_at="2026-09-18T00:00:00+00:00",
            )
        ],
        project_id=PROJECT,
    )
    llm = ScriptedLLM(
        {"extract": [{"findings": [
            ScriptedLLM.fact("E1", "수동 채수에 의존한다", confidence="HIGH")
        ]}]}
    )
    findings, _, _ = extract_findings(
        candidates,
        knowledge.get_framework("MN03"),
        llm=llm,
        prompts=prompts,
        project_id=PROJECT,
        sources_by_id={s.source_id: s for s in sources},
        today=TODAY,
    )
    assert findings[0].confidence is Confidence.MEDIUM


# -- confidence -------------------------------------------------------------

def _source(**kwargs) -> SourceMetadata:
    base = dict(
        project_id=PROJECT,
        source_origin=SourceOrigin.UPLOADED_FILE,
        source_category=SourceCategory.COMPANY_DATA,
        file_type=FileType.PDF,
        file_size=100,
        source_date="2026-01-01",
    )
    base.update(kwargs)
    return SourceMetadata(**base)


def test_company_data_alone_does_not_earn_high() -> None:
    """Being the client's own deck says nothing about whether it is right about the market."""
    signals = ConfidenceSignals(source=_source(), today=TODAY)
    assert ceiling_for(EvidenceType.FACT, signals) is Confidence.MEDIUM


def test_a_publisher_alone_does_not_earn_high() -> None:
    signals = ConfidenceSignals(
        source=_source(
            source_origin=SourceOrigin.SEARCH_RESULT,
            source_category=SourceCategory.EXTERNAL_BUSINESS_DATA,
            file_type=None, file_size=None,
            title="t", publisher="Fictional Institute", retrieved_at="2026-09-18T00:00:00+00:00",
        ),
        today=TODAY,
    )
    assert ceiling_for(EvidenceType.FACT, signals) is Confidence.MEDIUM


def test_high_needs_authority_and_corroboration_and_recency() -> None:
    signals = ConfidenceSignals(source=_source(), corroborating_source_count=2, today=TODAY)
    assert ceiling_for(EvidenceType.FACT, signals) is Confidence.HIGH


def test_a_stale_source_cannot_support_high() -> None:
    signals = ConfidenceSignals(
        source=_source(source_date="2015-01-01"), corroborating_source_count=3, today=TODAY
    )
    assert ceiling_for(EvidenceType.FACT, signals) is Confidence.MEDIUM


def test_an_undated_source_cannot_support_high() -> None:
    signals = ConfidenceSignals(
        source=_source(source_date=None), corroborating_source_count=3, today=TODAY
    )
    assert ceiling_for(EvidenceType.FACT, signals) is Confidence.MEDIUM


def test_no_source_record_means_unknown() -> None:
    assert ceiling_for(EvidenceType.FACT, ConfidenceSignals()) is Confidence.UNKNOWN


def test_assumption_and_gap_are_pinned() -> None:
    assert ceiling_for(EvidenceType.ASSUMPTION) is Confidence.LOW
    assert ceiling_for(EvidenceType.MISSING_EVIDENCE) is Confidence.UNKNOWN


def test_inference_is_limited_by_its_weakest_support() -> None:
    ceiling = ceiling_for(
        EvidenceType.INFERENCE, supporting=[Confidence.HIGH, Confidence.LOW, Confidence.MEDIUM]
    )
    assert ceiling is Confidence.LOW


def test_cap_lowers_but_never_raises() -> None:
    assert cap(Confidence.HIGH, Confidence.MEDIUM) is Confidence.MEDIUM
    assert cap(Confidence.LOW, Confidence.HIGH) is Confidence.LOW, "a cautious answer stands"
    assert cap(Confidence.UNKNOWN, Confidence.HIGH) is Confidence.UNKNOWN


def test_an_overconfident_model_answer_is_brought_down(ingested, prompts, knowledge) -> None:
    findings, _, _ = _extract(
        ingested, prompts, knowledge,
        {"findings": [ScriptedLLM.fact("E1", "단일 출처의 주장", confidence="HIGH")]},
    )
    assert findings[0].confidence is Confidence.MEDIUM


def test_the_reason_for_a_cap_is_explainable() -> None:
    reasons = reasons_for(EvidenceType.FACT, ConfidenceSignals(source=_source(), today=TODAY))
    assert any("source supports it" in reason for reason in reasons)


def test_corroboration_threshold_is_policy_driven() -> None:
    policy = ResearchPolicy(corroboration_for_high=1)
    signals = ConfidenceSignals(source=_source(), corroborating_source_count=1, today=TODAY)
    assert ceiling_for(EvidenceType.FACT, signals, policy=policy) is Confidence.HIGH


# -- invariants the entities enforce on their own ---------------------------

def test_inference_may_not_borrow_a_source_field() -> None:
    finding = ResearchFinding(
        project_id=PROJECT, finding="추론", evidence_type=EvidenceType.INFERENCE,
        mn_basis=["MN04"], supporting_finding_ids=["fnd_1"], source_id="src_1",
    )
    violations = evidence.check_finding(finding)
    assert violations and "must leave" in violations[0]


def test_inference_without_support_is_rejected() -> None:
    finding = ResearchFinding(
        project_id=PROJECT, finding="근거 없는 추론", evidence_type=EvidenceType.INFERENCE,
        mn_basis=["MN04"],
    )
    violations = evidence.check_finding(finding)
    assert violations and "supporting_finding_ids" in violations[0]


def test_fact_may_not_carry_supporting_findings() -> None:
    finding = ResearchFinding(
        project_id=PROJECT, finding="사실", evidence_type=EvidenceType.FACT,
        mn_basis=["MN02"], source_id="src_1", supporting_finding_ids=["fnd_1"],
    )
    assert evidence.check_finding(finding) != []


def test_assumption_may_not_carry_a_source() -> None:
    finding = ResearchFinding(
        project_id=PROJECT, finding="가정", evidence_type=EvidenceType.ASSUMPTION,
        mn_basis=["MN05"], source_id="src_1", evidence_summary="가정임",
    )
    assert evidence.check_finding(finding) != []


def test_missing_evidence_must_say_what_is_needed() -> None:
    finding = ResearchFinding(
        project_id=PROJECT, finding="모른다", evidence_type=EvidenceType.MISSING_EVIDENCE,
        mn_basis=["MN02"],
    )
    violations = evidence.check_finding(finding)
    assert violations and "close the gap" in violations[0]


def test_key_issue_needs_swot_behind_it() -> None:
    issue = KeyIssue(
        project_id=PROJECT,
        statement="질문",
        decision_area="market_priority",
        strategic_implication="근거는 A를 가리키나 B가 미확인이다",
    )
    violations = evidence.check_key_issue(issue)
    assert violations and "swot_issue_ids" in violations[0]


def test_key_issue_needs_a_strategic_implication() -> None:
    """Required, because a record stored with it blank reads like a finished one."""
    issue = KeyIssue(
        project_id=PROJECT,
        statement="질문",
        decision_area="market_priority",
        swot_issue_ids=["swt_1"],
    )
    violations = evidence.check_key_issue(issue)
    assert any("strategic_implication" in v for v in violations)


def test_uploaded_file_may_not_look_like_a_web_page() -> None:
    source = _source(url="https://example.invalid/x")
    violations = evidence.check_source_metadata(source)
    assert violations and "filename in disguise" in violations[0]


def test_search_result_may_not_invent_a_file_type() -> None:
    source = SourceMetadata(
        project_id=PROJECT,
        source_origin=SourceOrigin.SEARCH_RESULT,
        source_category=SourceCategory.EXTERNAL_BUSINESS_DATA,
        title="t", retrieved_at="2026-09-18T00:00:00+00:00",
        file_type=FileType.HTML, file_size=1024,
    )
    violations = evidence.check_source_metadata(source)
    assert violations and "corrupts the provenance trail" in violations[0]


def test_search_result_needs_a_retrieval_time() -> None:
    source = SourceMetadata(
        project_id=PROJECT,
        source_origin=SourceOrigin.SEARCH_RESULT,
        source_category=SourceCategory.EXTERNAL_BUSINESS_DATA,
        title="t",
    )
    assert any("retrieved_at" in v for v in evidence.check_source_metadata(source))
