# -*- coding: utf-8 -*-
"""The research pipeline: Evidence → Finding → SWOT → Key Issue.

Hallucination rejection lives in ``test_research_validation.py``; the boundary check lives in
``test_research_boundary.py``. This module covers the happy paths and the offline runs.
"""
from __future__ import annotations

import pytest

from adapters.intake import IntakeSession
from adapters.llm.echo import EchoLLM
from adapters.prompts import load_prompt_set
from adapters.search.manual import ManualSearch
from adapters.storage.memory import MemoryStorage
from core import evidence
from core.interfaces.search import SearchResult
from core.models import (
    Confidence,
    EvidenceType,
    FileType,
    MarketScope,
    Project,
    SourceCategory,
    SourceOrigin,
    SWOTCategory,
)
from core.research import (
    ResearchPolicy,
    batch_candidates,
    build_evidence_block,
    classify_swot,
    derive_key_issues,
    dimension_brief,
    extract_findings,
    frameworks_for,
    infer_findings,
    ingest_search_results,
    persist,
    run_research,
    shortlist,
    source_from_search_result,
)
from scripted_llm import ScriptedLLM

PROJECT = "prj_research"


@pytest.fixture
def prompts(repo_root):
    return load_prompt_set(repo_root / "prompts")


@pytest.fixture
def knowledge(repo_root):
    from adapters.knowledge.static import StaticKnowledge

    return StaticKnowledge.from_directory(repo_root / "knowledge" / "master-notes")


@pytest.fixture
def ingested():
    """Real intake output, so the research stage is fed what Phase 2 actually produces."""
    body = (
        "메콩델타 상수도 사업자는 건기 염분 상승 구간에서 측정 주기를 늘려야 한다.\n\n"
        "현장 인력이 수동 채수에 의존하고 있어 주기를 늘리기 어렵다.\n\n"
        "현지 경쟁 공급사는 대부분 단항목 측정기를 판매한다.\n"
    )
    with IntakeSession(PROJECT) as session:
        result = session.ingest(
            bytearray(body.encode("utf-8")),
            file_type=FileType.TXT,
            source_category=SourceCategory.EXTERNAL_BUSINESS_DATA,
            display_label="시장 메모 (가상)",
            source_date="2026-04-02",
        )
    return result


def _project() -> Project:
    return Project(
        project_id=PROJECT,
        company_name="Fictional Sensing",
        market_scope=[MarketScope.INTERNATIONAL],
        target_countries=["VN"],
    )


# -- prompts load from disk, core never reads them -------------------------

def test_prompts_are_loaded_by_the_adapter_not_the_core(prompts) -> None:
    assert prompts.extract_findings and prompts.classify_swot and prompts.derive_key_issues
    # Front matter is for the human editor, not the model.
    assert not prompts.extract_findings.startswith("---")
    assert "Evidence rules" in prompts.extract_findings


def test_prompts_stay_provider_neutral(repo_root) -> None:
    """No prompt may name a model or a vendor — provider differences belong in the adapter.

    README.md is excluded because it states the rule, which means quoting the names.
    """
    prompt_files = [
        path for path in sorted((repo_root / "prompts").rglob("*.md")) if path.name != "README.md"
    ]
    assert prompt_files, "there should be prompt files to check"

    for path in prompt_files:
        text = path.read_text(encoding="utf-8").lower()
        for vendor in ("claude", "gpt-", "gemini", "anthropic", "openai"):
            assert vendor not in text, f"{path.name} names a provider: {vendor}"


# -- batching ---------------------------------------------------------------

def test_batching_respects_both_limits(ingested) -> None:
    policy = ResearchPolicy(max_candidates_per_batch=2)
    batches = batch_candidates(ingested.candidates, policy)
    assert all(len(b) <= 2 for b in batches)
    assert sum(len(b) for b in batches) == len(ingested.candidates)


def test_batching_splits_on_character_budget(ingested) -> None:
    policy = ResearchPolicy(max_candidates_per_batch=99, max_evidence_chars_per_batch=30)
    batches = batch_candidates(ingested.candidates, policy)
    assert len(batches) > 1


def test_long_passage_is_truncated_not_dropped() -> None:
    from core.intake.models import EvidenceCandidate

    policy = ResearchPolicy(max_chars_per_candidate=20)
    candidate = EvidenceCandidate(project_id=PROJECT, source_id="src_1", text="가" * 500, locator="line 1")
    block = build_evidence_block([candidate], policy)
    assert block.entries[0].truncated
    assert "truncated" in block.entries[0].text
    assert len(block.entries) == 1


def test_default_policy_values_are_the_documented_ones() -> None:
    policy = ResearchPolicy()
    assert policy.max_candidates_per_batch == 12
    assert policy.max_evidence_chars_per_batch == 24_000
    assert policy.max_chars_per_candidate == 4_000
    assert policy.use_keyword_shortlist is False
    assert policy.frameworks == ("MN02", "MN03", "MN04", "MN05", "MN06", "MN07")


# -- framework selection ----------------------------------------------------

def test_all_six_frameworks_run_by_default(knowledge) -> None:
    selected, skipped = frameworks_for(knowledge, batch_text="anything at all")
    assert [f.framework_id for f in selected] == list(ResearchPolicy().frameworks)
    assert skipped == []


def test_operator_choice_overrides_everything(knowledge) -> None:
    policy = ResearchPolicy(use_keyword_shortlist=True)
    selected, skipped = frameworks_for(
        knowledge, policy=policy, requested=["MN03"], batch_text="완전히 무관한 내용"
    )
    assert [f.framework_id for f in selected] == ["MN03"]
    assert skipped == []


def test_shortlist_is_off_unless_asked_for(knowledge) -> None:
    selected, skipped = frameworks_for(knowledge, batch_text="가격 원가 마진")
    assert len(selected) == 6 and skipped == []


def test_shortlist_narrows_and_records_what_it_skipped(knowledge) -> None:
    policy = ResearchPolicy(use_keyword_shortlist=True)
    selected, skipped = frameworks_for(
        knowledge, policy=policy, batch_text="cost price margin channel cost revenue model"
    )
    assert len(selected) < 6
    assert skipped, "a narrowed framework list must say what it left out"
    assert all(isinstance(reason, str) and reason for _, reason in skipped)


def test_shortlist_keeps_everything_when_nothing_matches(knowledge) -> None:
    frameworks = [knowledge.get_framework(f) for f in ("MN02", "MN06")]
    kept, skipped = shortlist(frameworks, "zzzz qqqq")
    assert len(kept) == 2 and skipped == []


def test_dimension_brief_asks_questions(knowledge) -> None:
    brief = dimension_brief(knowledge.get_framework("MN03"), "ko")
    assert "MN03" in brief and "?" in brief


# -- extraction -------------------------------------------------------------

def test_fact_gets_provenance_from_the_cited_passage(ingested, prompts, knowledge) -> None:
    llm = ScriptedLLM({"extract": [{"findings": [ScriptedLLM.fact("E1", "측정 주기를 늘려야 한다")]}]})
    findings, rejections, records = extract_findings(
        ingested.candidates,
        knowledge.get_framework("MN03"),
        llm=llm,
        prompts=prompts,
        project_id=PROJECT,
        sources_by_id={ingested.source.source_id: ingested.source},
        market_scope=MarketScope.INTERNATIONAL,
        country="VN",
    )

    assert rejections == []
    assert len(findings) == 1
    finding = findings[0]
    assert finding.evidence_type is EvidenceType.FACT
    assert finding.source_id == ingested.source.source_id
    assert finding.page_or_section == ingested.candidates[0].locator
    assert finding.source_date == "2026-04-02"
    assert finding.mn_basis == ["MN03"]
    assert evidence.check_finding(finding) == []
    assert len(records) == 1 and records[0].grounded is True


def test_mn_basis_comes_from_the_pipeline_not_the_model(ingested, prompts, knowledge) -> None:
    """EchoLLM synthesising the full entity schema invents a framework id. This is the guard."""
    llm = ScriptedLLM({"extract": [{"findings": [ScriptedLLM.fact("E1", "확인된 사실")]}]})
    findings, _, _ = extract_findings(
        ingested.candidates,
        knowledge.get_framework("MN06"),
        llm=llm,
        prompts=prompts,
        project_id=PROJECT,
        sources_by_id={ingested.source.source_id: ingested.source},
    )
    assert findings[0].mn_basis == ["MN06"]


def test_missing_evidence_must_say_what_would_close_the_gap(ingested, prompts, knowledge) -> None:
    llm = ScriptedLLM({"extract": [{"findings": [ScriptedLLM.gap("인증 요건 미확인", "인증 목록 필요")]}]})
    findings, _, _ = extract_findings(
        ingested.candidates,
        knowledge.get_framework("MN02"),
        llm=llm,
        prompts=prompts,
        project_id=PROJECT,
        sources_by_id={ingested.source.source_id: ingested.source},
    )
    finding = findings[0]
    assert finding.evidence_type is EvidenceType.MISSING_EVIDENCE
    assert finding.source_id is None
    assert finding.evidence_summary == "인증 목록 필요"
    assert evidence.check_finding(finding) == []


def test_pass_one_cannot_produce_an_inference() -> None:
    from core.research.output_schemas import FINDING_BATCH

    allowed = FINDING_BATCH["properties"]["findings"]["items"]["properties"]["evidence_type"]["enum"]
    assert "INFERENCE" not in allowed, "an inference has nothing to reason from in pass 1"


# -- inference --------------------------------------------------------------

def test_inference_names_its_findings_and_borrows_no_source(ingested, prompts, knowledge) -> None:
    facts_llm = ScriptedLLM({"extract": [{"findings": [ScriptedLLM.fact("E1", "수동 채수 의존")]}]})
    framework = knowledge.get_framework("MN04")
    facts, _, _ = extract_findings(
        ingested.candidates,
        framework,
        llm=facts_llm,
        prompts=prompts,
        project_id=PROJECT,
        sources_by_id={ingested.source.source_id: ingested.source},
    )

    llm = ScriptedLLM({"infer": [{"inferences": [ScriptedLLM.inference(["F1"], "비교우위가 될 수 있다")]}]})
    inferences, rejections, _ = infer_findings(
        facts, framework, llm=llm, prompts=prompts, project_id=PROJECT
    )

    assert rejections == []
    inference = inferences[0]
    assert inference.evidence_type is EvidenceType.INFERENCE
    assert inference.supporting_finding_ids == [facts[0].finding_id]
    assert inference.source_id is None
    assert inference.source_type is None
    assert inference.page_or_section is None
    assert inference.source_date is None
    assert evidence.check_finding(inference, known_finding_ids=[facts[0].finding_id]) == []


def test_inference_cannot_be_firmer_than_its_support(ingested, prompts, knowledge) -> None:
    facts_llm = ScriptedLLM(
        {"extract": [{"findings": [ScriptedLLM.fact("E1", "낮은 근거의 사실", confidence="LOW")]}]}
    )
    framework = knowledge.get_framework("MN04")
    facts, _, _ = extract_findings(
        ingested.candidates,
        framework,
        llm=facts_llm,
        prompts=prompts,
        project_id=PROJECT,
        sources_by_id={ingested.source.source_id: ingested.source},
    )
    assert facts[0].confidence is Confidence.LOW

    llm = ScriptedLLM(
        {"infer": [{"inferences": [ScriptedLLM.inference(["F1"], "강한 주장", confidence="HIGH")]}]}
    )
    inferences, _, _ = infer_findings(facts, framework, llm=llm, prompts=prompts, project_id=PROJECT)
    assert inferences[0].confidence is Confidence.LOW


# -- SWOT -------------------------------------------------------------------

def test_swot_cites_the_findings_it_compresses(ingested, prompts, knowledge) -> None:
    facts_llm = ScriptedLLM({"extract": [{"findings": [ScriptedLLM.fact("E1", "수동 채수 의존")]}]})
    facts, _, _ = extract_findings(
        ingested.candidates,
        knowledge.get_framework("MN03"),
        llm=facts_llm,
        prompts=prompts,
        project_id=PROJECT,
        sources_by_id={ingested.source.source_id: ingested.source},
    )

    llm = ScriptedLLM(
        {"swot": [{"items": [ScriptedLLM.swot_item("OPPORTUNITY", "자동 측정 수요", ["F1"])]}]}
    )
    issues, rejections, _ = classify_swot(facts, llm=llm, prompts=prompts, project_id=PROJECT)

    assert rejections == []
    issue = issues[0]
    assert issue.category is SWOTCategory.OPPORTUNITY
    assert issue.finding_ids == [facts[0].finding_id]
    assert issue.mn_basis == ["MN03"], "a SWOT item inherits the frameworks behind its findings"
    assert evidence.check_swot_issue(issue, known_finding_ids=[facts[0].finding_id]) == []


def test_swot_without_findings_produces_nothing(prompts) -> None:
    llm = ScriptedLLM()
    issues, rejections, records = classify_swot([], llm=llm, prompts=prompts, project_id=PROJECT)
    assert issues == [] and rejections == [] and records == []
    assert llm.calls == [], "no findings means nothing to send"


def test_swot_issue_no_longer_holds_a_key_issue() -> None:
    import dataclasses

    from core.models import SWOTIssue

    names = {f.name for f in dataclasses.fields(SWOTIssue)}
    assert "key_issue" not in names and "strategic_implication" not in names


# -- key issues -------------------------------------------------------------

def test_key_issue_binds_several_swot_items(prompts) -> None:
    from core.models import ResearchFinding, SWOTIssue

    finding = ResearchFinding(
        project_id=PROJECT,
        finding="근거",
        evidence_type=EvidenceType.ASSUMPTION,
        mn_basis=["MN02"],
        confidence=Confidence.LOW,
        evidence_summary="가정",
    )
    swot = [
        SWOTIssue(project_id=PROJECT, category=SWOTCategory.STRENGTH, statement="강점",
                  finding_ids=[finding.finding_id], mn_basis=["MN02"]),
        SWOTIssue(project_id=PROJECT, category=SWOTCategory.THREAT, statement="위협",
                  finding_ids=[finding.finding_id], mn_basis=["MN05"]),
    ]
    llm = ScriptedLLM(
        {"key_issue": [{"issues": [ScriptedLLM.key_issue("어느 시장을 먼저 볼 것인가", ["S1", "S2"])]}]}
    )

    issues, rejections, flags, _ = derive_key_issues(
        swot, [finding], llm=llm, prompts=prompts, project_id=PROJECT
    )

    assert rejections == [] and flags == []
    issue = issues[0]
    assert len(issue.swot_issue_ids) == 2
    assert finding.finding_id in issue.finding_ids
    assert set(issue.mn_basis) == {"MN02", "MN05"}
    assert issue.confidence is Confidence.LOW, "limited by the weakest supporting finding"
    assert evidence.check_key_issue(
        issue, known_swot_ids=[s.issue_id for s in swot], known_finding_ids=[finding.finding_id]
    ) == []


def test_key_issue_without_swot_produces_nothing(prompts) -> None:
    llm = ScriptedLLM()
    issues, rejections, flags, records = derive_key_issues(
        [], [], llm=llm, prompts=prompts, project_id=PROJECT
    )
    assert issues == [] and records == [] and flags == []
    assert llm.calls == []


# -- search results ---------------------------------------------------------

def test_search_result_becomes_a_source_without_a_fake_file_type() -> None:
    result = SearchResult(
        title="Fictional utility operations review",
        snippet="건기 염분 상승 구간에서 측정 주기 요구가 높아진다.",
        url="https://example.invalid/fictional",
        publisher="Fictional Institute",
        published_date="2026-04-02",
        retrieved_at="2026-09-18T09:00:00+00:00",
        country="VN",
        market_scope=MarketScope.INTERNATIONAL,
    )
    source = source_from_search_result(result, project_id=PROJECT)

    assert source.source_origin is SourceOrigin.SEARCH_RESULT
    assert source.file_type is None and source.file_size is None and source.page_count is None
    assert source.publisher == "Fictional Institute"
    assert source.retrieved_at == "2026-09-18T09:00:00+00:00"
    assert source.source_date == "2026-04-02"
    assert evidence.check_source_metadata(source) == []


def test_search_and_file_evidence_share_one_pipeline_input_type() -> None:
    search = ManualSearch(
        [
            SearchResult(
                title="Fictional market note",
                snippet="현지 경쟁사는 단항목 측정기 위주다.",
                publisher="Fictional Institute",
                retrieved_at="2026-09-18T09:00:00+00:00",
                country="VN",
                market_scope=MarketScope.INTERNATIONAL,
            )
        ]
    )
    hits = search.search("경쟁사", scope=MarketScope.INTERNATIONAL)
    sources, candidates = ingest_search_results(hits, project_id=PROJECT)

    assert len(sources) == 1 and len(candidates) == 1
    assert candidates[0].source_id == sources[0].source_id
    assert candidates[0].locator == "snippet"
    assert type(candidates[0]).__name__ == "EvidenceCandidate"


def test_empty_snippets_are_dropped_rather_than_stored() -> None:
    sources, candidates = ingest_search_results(
        [SearchResult(title="Empty", snippet="   ", retrieved_at="2026-09-18T00:00:00+00:00")],
        project_id=PROJECT,
    )
    assert sources == [] and candidates == []


def test_evidence_quality_defaults_to_unknown() -> None:
    assert SearchResult(title="t", snippet="s").evidence_quality is Confidence.UNKNOWN


# -- end to end -------------------------------------------------------------

def test_offline_end_to_end_with_echo(ingested, prompts, knowledge) -> None:
    """No API key, no network. The offline provider degrades honestly rather than inventing."""
    outcome = run_research(
        project=_project(),
        candidates=ingested.candidates,
        sources=[ingested.source],
        knowledge=knowledge,
        llm=EchoLLM(),
        prompts=prompts,
    )

    assert outcome.transmissions, "the pipeline must have made calls"
    for finding in outcome.findings:
        assert evidence.check_finding(finding) == []
        assert finding.evidence_type is not EvidenceType.FACT, (
            "an offline provider has no evidence to establish a fact with"
        )


def test_offline_end_to_end_with_manual_search(prompts, knowledge) -> None:
    search = ManualSearch(
        [
            SearchResult(
                title="Fictional operations review",
                snippet="메콩델타 사업자는 수동 채수에 의존한다.",
                publisher="Fictional Institute",
                published_date="2026-04-02",
                retrieved_at="2026-09-18T09:00:00+00:00",
                country="VN",
                market_scope=MarketScope.INTERNATIONAL,
            )
        ]
    )
    hits = search.search("채수", scope=MarketScope.INTERNATIONAL)
    sources, candidates = ingest_search_results(hits, project_id=PROJECT)

    llm = ScriptedLLM(
        {
            "extract": [{"findings": [ScriptedLLM.fact("E1", "수동 채수에 의존한다")]}],
            "swot": [{"items": [ScriptedLLM.swot_item("OPPORTUNITY", "자동화 수요", ["F1"])]}],
            "key_issue": [
                {"issues": [ScriptedLLM.key_issue("이 시장을 먼저 볼 것인가", ["S1"])]}
            ],
        }
    )
    outcome = run_research(
        project=_project(),
        candidates=candidates,
        sources=sources,
        knowledge=knowledge,
        llm=llm,
        prompts=prompts,
        frameworks=["MN03"],
        include_inferences=False,
    )

    assert outcome.findings and outcome.swot_issues and outcome.key_issues
    fact = outcome.facts[0]
    assert fact.source_id == sources[0].source_id
    assert fact.page_or_section == "snippet"


def test_pipeline_persists_only_what_may_be_stored(ingested, prompts, knowledge) -> None:
    storage = MemoryStorage()
    outcome = run_research(
        project=_project(),
        candidates=ingested.candidates,
        sources=[ingested.source],
        knowledge=knowledge,
        llm=EchoLLM(),
        prompts=prompts,
        frameworks=["MN03"],
    )
    persist(outcome, storage)

    assert len(storage.get_findings(PROJECT)) == len(outcome.findings)
    assert not hasattr(storage, "save_evidence_candidate")


def test_outcome_summary_is_counts_only(ingested, prompts, knowledge) -> None:
    outcome = run_research(
        project=_project(),
        candidates=ingested.candidates,
        sources=[ingested.source],
        knowledge=knowledge,
        llm=EchoLLM(),
        prompts=prompts,
        frameworks=["MN02"],
    )
    summary = outcome.summary()
    assert set(summary) == {
        "findings", "by_evidence_type", "swot_issues", "key_issues",
        "rejections", "review_flags", "transmissions",
    }
    for candidate in ingested.candidates:
        assert candidate.text not in str(summary)


def test_default_run_uses_all_six_frameworks(ingested, prompts, knowledge) -> None:
    llm = ScriptedLLM()
    run_research(
        project=_project(),
        candidates=ingested.candidates,
        sources=[ingested.source],
        knowledge=knowledge,
        llm=llm,
        prompts=prompts,
    )
    extraction_calls = [c for c in llm.calls if c["kind"] == "analyze"]
    assert len(extraction_calls) == 6, "one grounded call per framework for a single batch"
