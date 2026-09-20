# -*- coding: utf-8 -*-
"""Adapter contract tests.

Every adapter shipped here is checked against the same expectations an organisation's own
adapter has to meet, so these tests double as the specification for writing one (see
``adapters/README.md``).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from adapters.knowledge.handbook import HandbookKnowledge
from adapters.knowledge.static import StaticKnowledge
from adapters.llm.echo import EchoLLM
from adapters.search.manual import ManualSearch
from adapters.storage.memory import MemoryStorage
from adapters.storage.null import NullStorage
from adapters.storage.sqlite import SQLiteStorage
from core.errors import UnknownFrameworkError
from core.harness import CLIENT_ANALYSIS_FRAMEWORKS, RESEARCH_FRAMEWORKS, create_harness
from core.interfaces import KnowledgeProvider, LLMProvider, SearchProvider, StorageProvider
from core.interfaces.search import SearchResult
from core.models import (
    EvidenceType,
    MarketScope,
    Project,
    ResearchFinding,
    SWOTCategory,
    SWOTIssue,
)


# -- protocol conformance --------------------------------------------------

def test_adapters_satisfy_their_protocols(repo_root: Path, tmp_path: Path) -> None:
    """Structural conformance only: it checks the methods exist, not their signatures.

    The behaviour tests below are what actually pin the contract down.
    """
    cards = repo_root / "knowledge" / "master-notes"
    assert isinstance(NullStorage(), StorageProvider)
    assert isinstance(MemoryStorage(), StorageProvider)
    assert isinstance(SQLiteStorage(tmp_path / "h.sqlite3"), StorageProvider)
    assert isinstance(StaticKnowledge.from_directory(cards), KnowledgeProvider)
    assert isinstance(EchoLLM(), LLMProvider)
    assert isinstance(ManualSearch(), SearchProvider)


def test_every_adapter_names_itself(tmp_path: Path) -> None:
    """``name`` is what an application may safely put in a log line."""
    adapters = (
        NullStorage(),
        MemoryStorage(),
        SQLiteStorage(tmp_path / "h.sqlite3"),
        EchoLLM(),
        ManualSearch(),
    )
    for adapter in adapters:
        assert isinstance(adapter.name, str) and adapter.name
    assert len({a.name for a in adapters}) == len(adapters), "two adapters share a name"


def test_the_three_storage_adapters_are_interchangeable(tmp_path: Path) -> None:
    """The same calls against all three. Only what is *kept* may differ.

    ``SQLiteStorage`` is the one that persists, so it is also the one most able to drift from
    the contract the other two established — this is where that would show.
    """
    project = Project(company_name="Fictional Co")
    finding = ResearchFinding(
        project_id=project.project_id,
        finding="a statement",
        evidence_type=EvidenceType.ASSUMPTION,
        mn_basis=["MN02"],
    )

    for storage in (NullStorage(), MemoryStorage(), SQLiteStorage(tmp_path / "s.sqlite3")):
        assert storage.save_project(project) == project.project_id
        assert storage.save_finding(finding) == finding.finding_id
        # Absence is never an error, whichever adapter is wired.
        assert storage.get_project("prj_missing") is None
        assert storage.get_findings("prj_missing") == []

        kept = storage.get_findings(project.project_id)
        if storage.name == "null":
            assert kept == []
        else:
            assert [f.finding_id for f in kept] == [finding.finding_id]
            assert storage.get_project(project.project_id) == project


# -- null storage ----------------------------------------------------------

def test_null_storage_keeps_nothing_but_returns_ids() -> None:
    storage = NullStorage()
    project = Project(company_name="Fictional Co")

    assert storage.save_project(project) == project.project_id
    assert storage.get_project(project.project_id) is None

    finding = ResearchFinding(
        project_id=project.project_id,
        finding="x",
        evidence_type=EvidenceType.ASSUMPTION,
        mn_basis=["MN02"],
    )
    assert storage.save_finding(finding) == finding.finding_id
    assert storage.get_findings(project.project_id) == []


def test_null_storage_reads_are_empty_not_errors() -> None:
    """Absence is the normal state in ephemeral mode, so a read must not raise."""
    storage = NullStorage()
    assert storage.get_source_metadata("prj_missing") == []
    assert storage.get_swot_issues("prj_missing") == []
    assert storage.get_clients("prj_missing") == []
    assert storage.get_client_analyses("prj_missing") == []
    assert storage.get_proposal_strategies("prj_missing") == []
    assert storage.get_pricing_results("prj_missing") == []


# -- memory storage --------------------------------------------------------

def test_memory_storage_round_trips_and_isolates_projects() -> None:
    storage = MemoryStorage()
    a = Project(company_name="Alpha Fictional")
    b = Project(company_name="Beta Fictional")
    storage.save_project(a)
    storage.save_project(b)

    finding = ResearchFinding(
        project_id=a.project_id,
        finding="a statement",
        evidence_type=EvidenceType.ASSUMPTION,
        mn_basis=["MN02"],
    )
    storage.save_finding(finding)
    storage.save_swot_issue(
        SWOTIssue(
            project_id=a.project_id,
            category=SWOTCategory.STRENGTH,
            statement="s",
            finding_ids=[finding.finding_id],
        )
    )

    assert storage.get_project(a.project_id) == a
    assert [f.finding_id for f in storage.get_findings(a.project_id)] == [finding.finding_id]
    assert storage.get_findings(b.project_id) == []
    assert len(storage.get_swot_issues(a.project_id)) == 1


def test_memory_storage_returns_copies_of_its_lists() -> None:
    """A caller mutating a returned list must not corrupt the store."""
    storage = MemoryStorage()
    project = Project(company_name="Fictional Co")
    storage.save_project(project)
    storage.save_finding(
        ResearchFinding(
            project_id=project.project_id,
            finding="x",
            evidence_type=EvidenceType.ASSUMPTION,
            mn_basis=["MN02"],
        )
    )

    returned = storage.get_findings(project.project_id)
    returned.clear()
    assert len(storage.get_findings(project.project_id)) == 1


def test_memory_storage_clear_leaves_nothing() -> None:
    """An application in ephemeral mode calls this when a session ends."""
    storage = MemoryStorage()
    project = Project(company_name="Fictional Co")
    storage.save_project(project)
    storage.clear()
    assert storage.get_project(project.project_id) is None


# -- static knowledge ------------------------------------------------------

def test_static_knowledge_loads_the_shipped_cards(repo_root: Path) -> None:
    knowledge = StaticKnowledge.from_directory(repo_root / "knowledge" / "master-notes")
    assert knowledge.list_frameworks() == list(RESEARCH_FRAMEWORKS)


def test_every_framework_an_engine_needs_is_available(repo_root: Path) -> None:
    """The constants in core/harness.py and the shipped cards must agree."""
    knowledge = StaticKnowledge.from_directory(repo_root / "knowledge" / "master-notes")
    for framework_id in set(RESEARCH_FRAMEWORKS) | set(CLIENT_ANALYSIS_FRAMEWORKS):
        framework = knowledge.get_framework(framework_id)
        assert framework.framework_id == framework_id
        assert framework.dimensions, f"{framework_id} has no dimensions"


def test_unknown_framework_raises_rather_than_returning_a_blank(repo_root: Path) -> None:
    """An analysis run against an empty framework is worse than one that stops."""
    knowledge = StaticKnowledge.from_directory(repo_root / "knowledge" / "master-notes")
    with pytest.raises(UnknownFrameworkError) as excinfo:
        knowledge.get_framework("MN99")
    assert excinfo.value.code == "UNKNOWN_FRAMEWORK"


# -- handbook knowledge ----------------------------------------------------

def test_handbook_adapter_wraps_another_provider(repo_root: Path, tmp_path: Path) -> None:
    base = StaticKnowledge.from_directory(repo_root / "knowledge" / "master-notes")
    wrapped = HandbookKnowledge(base, tmp_path / "no-such-handbook")

    assert wrapped.list_frameworks() == base.list_frameworks()
    assert wrapped.is_available() is False

    framework = wrapped.get_framework("MN02")
    # A missing handbook is not an error: the cards are self-contained.
    assert framework.reference["handbook_available"] is False
    assert framework.reference["resolved_paths"] == []
    # The base provider must not have been mutated.
    assert "handbook_available" not in base.get_framework("MN02").reference


def test_handbook_adapter_resolves_paths_that_exist(repo_root: Path, tmp_path: Path) -> None:
    # Stand in for the handbook repository rather than depending on it being checked out.
    chapter = tmp_path / "ko" / "chapters"
    chapter.mkdir(parents=True)
    (chapter / "CH02.md").write_text("fictional stand-in", encoding="utf-8")

    wrapped = HandbookKnowledge(
        StaticKnowledge.from_directory(repo_root / "knowledge" / "master-notes"), tmp_path
    )
    framework = wrapped.get_framework("MN02")

    assert wrapped.is_available() is True
    assert framework.reference["handbook_available"] is True
    assert any(p.endswith("CH02.md") for p in framework.reference["resolved_paths"])


# -- echo llm --------------------------------------------------------------

def test_echo_is_deterministic() -> None:
    llm = EchoLLM()
    assert llm.generate("same prompt") == llm.generate("same prompt")
    assert llm.generate("a") != llm.generate("b")


def test_echo_never_returns_the_prompt() -> None:
    """Prompts carry extracted document text. Echoing it back would be a leak channel."""
    secret = "CONFIDENTIAL-CANARY-9f3a"
    llm = EchoLLM()

    assert secret not in llm.generate(f"analyse this: {secret}")
    assert secret not in llm.summarize(secret)
    assert secret not in str(llm.generate_structured(secret, schema={"type": "object"}))
    assert secret not in str(
        llm.analyze(secret, evidence=[secret], schema={"type": "object"})
    )


@pytest.mark.parametrize(
    "name",
    [
        "project",
        "source_metadata",
        "research_finding",
        "swot_issue",
        "client_candidate",
        "client_analysis",
        "proposal_strategy",
        "pricing_result",
    ],
)
def test_echo_output_satisfies_every_entity_schema(name: str, schemas: dict) -> None:
    """Also proves each schema is satisfiable at all — a constraint no one else checks."""
    result = EchoLLM().generate_structured("anything", schema=schemas[name])
    Draft202012Validator(schemas[name]).validate(result)


def test_echo_prefers_the_unanswered_enum_member(schemas: dict) -> None:
    """Placeholder output must never be mistakable for a judgement."""
    candidate = EchoLLM().generate_structured("x", schema=schemas["client_candidate"])
    assert all(assessment["level"] == "UNKNOWN" for assessment in candidate["fit"])
    assert candidate["priority"]["band"] == "UNKNOWN"

    finding = EchoLLM().generate_structured("x", schema=schemas["research_finding"])
    assert finding["evidence_type"] == "MISSING_EVIDENCE"
    assert finding["confidence"] == "UNKNOWN"


# -- manual search ---------------------------------------------------------

def test_manual_search_returns_only_supplied_material() -> None:
    search = ManualSearch()
    assert search.search("anything") == []

    search.add(
        SearchResult(
            title="Fictional market note",
            snippet="desalination demand is rising in the fictional region",
            country="VN",
            market_scope=MarketScope.INTERNATIONAL,
        )
    )
    assert search.search("desalination") == []  # default scope is DOMESTIC
    hits = search.search("desalination", scope=MarketScope.INTERNATIONAL)
    assert len(hits) == 1
    assert hits[0].provider == "manual"


def test_manual_search_filters_by_country_and_respects_limit() -> None:
    search = ManualSearch(
        [
            SearchResult(title=f"note {i}", snippet="water treatment tender", country="VN")
            for i in range(5)
        ]
    )
    assert len(search.search("water")) == 5
    assert len(search.search("water", limit=2)) == 2
    assert search.search("water", country="KR") == []


# -- assembly --------------------------------------------------------------

def test_harness_assembles_and_reports_its_adapters(harness) -> None:
    assert harness.describe() == {
        "storage": "memory",
        "knowledge": "static",
        "llm": "echo",
        "search": "manual",
    }


def test_harness_creates_and_stores_a_project(harness) -> None:
    project = harness.create_project(
        "Fictional Co",
        market_scope=[MarketScope.INTERNATIONAL],
        target_countries=["VN"],
        output_lang="en",
    )
    assert harness.storage.get_project(project.project_id) == project
    assert project.output_lang == "en"


def test_harness_exposes_the_right_frameworks_per_engine(harness) -> None:
    """Client analysis must not repeat the company-level notes."""
    research = [f.framework_id for f in harness.research_frameworks()]
    per_client = [f.framework_id for f in harness.client_analysis_frameworks()]

    assert research == list(RESEARCH_FRAMEWORKS)
    assert per_client == list(CLIENT_ANALYSIS_FRAMEWORKS)
    assert "MN02" not in per_client
    assert "MN07" not in per_client


def test_all_four_providers_are_required() -> None:
    """A defaulted provider would mean the core importing an adapter."""
    with pytest.raises(TypeError):
        create_harness(storage=NullStorage(), knowledge=None, llm=None)  # type: ignore[call-arg]
