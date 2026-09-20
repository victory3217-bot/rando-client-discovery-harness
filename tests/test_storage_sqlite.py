# -*- coding: utf-8 -*-
"""The first adapter that keeps anything, held to the behaviour of the one that does not.

``MemoryStorage`` is the reference. Wherever these tests could assert a value they assert
agreement instead — same calls, same results, both adapters — because the pipeline must not
behave differently depending on which one an application wired. Two of those agreements are
easy to break by accident and are checked explicitly: saving the same entity twice appends
rather than upserts (only ``save_project`` replaces), and reads come back in insertion order.

The rest is what a file-backed adapter adds and an in-memory one cannot have: a schema
version, a journal mode, an error boundary, threads, a second process reading the same
commit, and a file on disk that can be searched for things that should never be in it.
"""
from __future__ import annotations

import ast
import json
import sqlite3
import threading
from pathlib import Path

import pytest

from adapters.intake import IntakeSession
from adapters.storage.memory import MemoryStorage
from adapters.storage.null import NullStorage
from adapters.storage.sqlite import SCHEMA_VERSION, SQLiteStorage, SQLiteStorageError
from core.interfaces import StorageProvider
from core.intake import IntakePolicy
from core.models import (
    AccessRoute,
    AnalysisClaim,
    AnalysisDimension,
    ClientAnalysis,
    ClientCandidate,
    Confidence,
    EvidenceNeed,
    EvidenceRef,
    EvidenceTiming,
    EvidenceType,
    FileType,
    FitAssessment,
    FitCriterion,
    FitLevel,
    InternationalClaim,
    InternationalDimension,
    KeyIssue,
    MarketScope,
    ObjectionBasis,
    ObjectiveSource,
    OrganizationIdentity,
    PricingResult,
    PricingStatus,
    PriorityDecision,
    PriorityReasonCode,
    Project,
    ProposalObjection,
    ProposalObjective,
    ProposalStatus,
    ProposalStrategy,
    ResearchFinding,
    SalesPriority,
    SelectedSolutionElement,
    SourceCategory,
    SourceMetadata,
    SourceOrigin,
    StoryStep,
    StoryStepType,
    StrategyStatement,
    SWOTCategory,
    SWOTIssue,
)

PROJECT = "prj_sqlite"
D = AnalysisDimension


def _all_bytes(db: Path) -> bytes:
    """The database **and its WAL sidecar**.

    In WAL mode a freshly committed row lives in ``<db>-wal`` until a checkpoint moves it.
    Reading only the main file would make a privacy canary pass for the wrong reason — the
    positive control at the end of that test is what caught this.
    """
    return b"".join(
        path.read_bytes() for path in sorted(db.parent.iterdir()) if path.name.startswith(db.name)
    )


def _corrupt(db: Path, content: bytes) -> None:
    """Make the database unreadable, sidecars included.

    Overwriting only the main file leaves a valid WAL that SQLite can recover from, so the
    read would succeed and the test would prove nothing.
    """
    for path in sorted(db.parent.iterdir()):
        if path.name.startswith(db.name) and path != db:
            path.unlink()
    db.write_bytes(content)


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "harness.sqlite3"


@pytest.fixture
def storage(db: Path) -> SQLiteStorage:
    return SQLiteStorage(db)


# -- a fully populated instance of every entity ----------------------------
#
# Nesting is the point: a value object that survives `as_dict` but not `from_dict` would pass
# a shallow round-trip and lose an enum, a dataclass or a list on the way back.


def _project() -> Project:
    return Project(
        company_name="Fictional Sensor Works",
        market_scope=[MarketScope.DOMESTIC, MarketScope.INTERNATIONAL],
        target_countries=["KR", "VN"],
        target_industries=["water utilities"],
        project_id=PROJECT,
    )


def _source() -> SourceMetadata:
    return SourceMetadata(
        project_id=PROJECT,
        source_category=SourceCategory.EXTERNAL_BUSINESS_DATA,
        source_origin=SourceOrigin.UPLOADED_FILE,
        file_type=FileType.MD,
        display_label="메콩델타 시장 메모 (가상)",
        source_id="src_1",
    )


def _finding() -> ResearchFinding:
    return ResearchFinding(
        project_id=PROJECT,
        finding="수동 채수로는 측정 주기를 늘리지 못한다",
        evidence_type=EvidenceType.FACT,
        confidence=Confidence.MEDIUM,
        mn_basis=["MN03", "MN06"],
        source_id="src_1",
        finding_id="fnd_1",
    )


def _swot() -> SWOTIssue:
    return SWOTIssue(
        project_id=PROJECT,
        category=SWOTCategory.OPPORTUNITY,
        statement="상시 계측 수요가 확인된다",
        finding_ids=["fnd_1"],
        issue_id="swt_1",
    )


def _key_issue() -> KeyIssue:
    return KeyIssue(
        project_id=PROJECT,
        statement="측정 주기를 확보할 방법을 정해야 한다",
        decision_area="계측 주기 확보",
        strategic_implication="상시 계측으로 인력 증원 없이 주기를 늘린다",
        swot_issue_ids=["swt_1"],
        key_issue_id="key_1",
    )


def _candidate() -> ClientCandidate:
    return ClientCandidate(
        project_id=PROJECT,
        client_name="Fictional Alpha Water Systems",
        country="VN",
        industry="water utilities",
        discovery_rationale="상시 계측 도입을 검토한다는 기록이 있다",
        identity=OrganizationIdentity(
            legal_name="Fictional Alpha Water Systems Co., Ltd.",
            domain="alpha.example",
            organization_identifier="FICTIONAL-0000",
        ),
        fit=[
            FitAssessment(
                criterion=FitCriterion.PROBLEM_FIT,
                level=FitLevel.STRONG,
                reason="수동 채수 의존이 문서로 확인된다",
                finding_ids=["fnd_1"],
                source_ids=["src_1"],
                missing_evidence=["예산 규모"],
            ),
            FitAssessment(
                criterion=FitCriterion.PURCHASING_POTENTIAL,
                level=FitLevel.EVIDENCE_NEEDED,
                missing_evidence=["조달 이력"],
            ),
        ],
        priority=PriorityDecision(
            band=SalesPriority.P2,
            reason_codes=[PriorityReasonCode.INSUFFICIENT_EVIDENCE],
            missing_evidence=["예산 규모"],
        ),
        market_scope=MarketScope.INTERNATIONAL,
        source_ids=["src_1"],
        key_issue_ids=["key_1"],
        finding_ids=["fnd_1"],
        missing_evidence=["예산 규모"],
        client_id="cli_1",
    )


def _analysis() -> ClientAnalysis:
    claims = [
        AnalysisClaim(
            dimension=dimension,
            statement=f"{dimension.value} 확인된 내용",
            finding_ids=["fnd_1"],
            evidence_type=EvidenceType.FACT,
            confidence=Confidence.MEDIUM,
            framework_basis=["MN06"],
            organization_name=(
                "Fictional Alpha Water Systems" if dimension is D.COMPETITOR else None
            ),
            access_route=(
                AccessRoute.PUBLIC_TENDER if dimension is D.SALES_ACCESS_ROUTE else None
            ),
        )
        for dimension in AnalysisDimension
    ]
    return ClientAnalysis(
        project_id=PROJECT,
        client_id="cli_1",
        client_name="Fictional Alpha Water Systems",
        country="VN",
        industry="water utilities",
        our_solution="다항목 수질 계측 모듈",
        claims=claims,
        international_claims=[
            InternationalClaim(
                dimension=InternationalDimension.TARIFF,
                statement="협정세율 적용 대상이다",
                finding_ids=["fnd_1"],
                evidence_type=EvidenceType.FACT,
                confidence=Confidence.MEDIUM,
                framework_basis=["MN06"],
            )
        ],
        market_scope=MarketScope.INTERNATIONAL,
        finding_ids=["fnd_1"],
        missing_evidence=["예산 규모"],
        analysis_id="cla_1",
    )


def _strategy() -> ProposalStrategy:
    return ProposalStrategy(
        project_id=PROJECT,
        client_id="cli_1",
        client_name="Fictional Alpha Water Systems",
        country="VN",
        analysis_id="cla_1",
        objective=ProposalObjective.PILOT,
        objective_source=ObjectiveSource.HUMAN,
        objective_detail="운영 부서와 측정 주기를 확인한다",
        selected_solution_elements=[
            SelectedSolutionElement(ref="S1", text="다항목 수질 측정 모듈"),
            SelectedSolutionElement(ref="S2", text="원격 조회 기능"),
        ],
        proposed_solution="다항목 수질 측정 모듈 / 원격 조회 기능",
        value_proposition=StrategyStatement(
            text="인력 증원 없이 측정 주기를 확보한다",
            dimensions=[D.PROBLEM, D.VALUE_PROPOSITION],
            solution_element_refs=["S1"],
            missing_evidence=["예산 규모"],
        ),
        key_message=StrategyStatement(
            text="측정 주기를 인력 증원 없이 확보한다",
            dimensions=[D.PROBLEM, D.VALUE_DRIVER],
            solution_element_refs=["S1", "S2"],
        ),
        storyline=[
            StoryStep(step_type=StoryStepType.PROBLEM, message="수동 채수", dimensions=[D.PROBLEM]),
            StoryStep(step_type=StoryStepType.NEXT_STEP, message="시범 도입 협의"),
        ],
        objections=[
            ProposalObjection(
                objection="예산 상한",
                basis=ObjectionBasis.EVIDENCE_BACKED,
                dimensions=[D.BUDGET_EVIDENCE],
                response="범위를 조정한다",
                response_dimensions=[D.BUDGET_EVIDENCE],
            ),
            ProposalObjection(objection="인증 미확인", basis=ObjectionBasis.ANTICIPATED),
        ],
        evidence_needs=[
            EvidenceNeed(
                need="연간 계측 예산 규모",
                timing=EvidenceTiming.BEFORE_PRICING,
                dimension=D.BUDGET_EVIDENCE,
            ),
            EvidenceNeed(need="현지 인증 요건", timing=EvidenceTiming.UNCLASSIFIED),
        ],
        status=ProposalStatus.STRATEGY_DRAFTED,
        strategy_id="prp_1",
    )


def _pricing() -> PricingResult:
    return PricingResult(
        project_id=PROJECT,
        client_id="cli_1",
        strategy_id="prp_1",
        analysis_id="cla_1",
        pricing_case_id="pcs_1",
        pricing_payload={
            "schema_version": "1.1",
            "client_id": "cli_1",
            "case_id": "pcs_1",
            "product": {"name": "Sensor", "pricing_model": "one_time", "price_components": []},
            "tax": {"vat_rate": None},
            "fx": {"base_currency": "KRW", "reporting_currency": "USD",
                   "rate_base_per_reporting": None},
            "costs": {"items": []},
            "meta": {"strategy_id": "prp_1", "analysis_id": "cla_1"},
        },
        commercial_context={
            "pricing_case_id": "pcs_1",
            "evidence_needs": [
                {
                    "gap_ref": "gap_61becf8f3fd0bb8b",
                    "need": "연간 계측 예산 규모",
                    "timing": "BEFORE_PRICING",
                    "dimension": "BUDGET_EVIDENCE",
                }
            ],
            "open_gap_counts": {"BEFORE_PRICING": 1, "UNCLASSIFIED": 1},
        },
        status=PricingStatus.PAYLOAD_READY,
        pricing_result_id="prc_1",
    )


#: (save method, get method, builder, expected returned id)
ALL_NINE = [
    ("save_project", "get_project", _project, PROJECT),
    ("save_source_metadata", "get_source_metadata", _source, "src_1"),
    ("save_finding", "get_findings", _finding, "fnd_1"),
    ("save_swot_issue", "get_swot_issues", _swot, "swt_1"),
    ("save_key_issue", "get_key_issues", _key_issue, "key_1"),
    ("save_client", "get_clients", _candidate, "cli_1"),
    ("save_client_analysis", "get_client_analyses", _analysis, "cla_1"),
    ("save_proposal_strategy", "get_proposal_strategies", _strategy, "prp_1"),
    ("save_pricing_result", "get_pricing_results", _pricing, "prc_1"),
]


def _populate(store) -> dict:
    """Save one of each entity, and hand back the objects that were actually saved.

    Returning them is the point. Every entity defaults ``created_at`` from the clock at
    ``timespec="seconds"``, so a test that rebuilds an "expected" value at comparison time is
    comparing two different timestamps whenever the two calls land either side of a second
    boundary — which is a flake, not a finding. What the round-trip contract says is that
    what went in comes back unchanged, so the thing to compare against is what went in.
    """
    saved: dict = {}
    for save, _, build, _id in ALL_NINE:
        entity = build()
        getattr(store, save)(entity)
        saved[save] = entity
    return saved


# -- A: protocol -----------------------------------------------------------

def test_a_sqlite_storage_satisfies_the_protocol(storage) -> None:
    assert isinstance(storage, StorageProvider)
    assert storage.name == "sqlite"


# -- B: all nine round-trip ------------------------------------------------

@pytest.mark.parametrize("save,get,build,expected_id", ALL_NINE, ids=[n[0] for n in ALL_NINE])
def test_b_every_entity_round_trips(storage, save, get, build, expected_id) -> None:
    entity = build()
    assert getattr(storage, save)(entity) == expected_id

    read = getattr(storage, get)(PROJECT)
    restored = read if save == "save_project" else read[0]
    assert restored == entity
    assert type(restored) is type(entity)


# -- C: Phase 5 nesting ----------------------------------------------------

def test_c_nested_analysis_value_objects_come_back_as_objects(storage) -> None:
    storage.save_client_analysis(_analysis())
    restored = storage.get_client_analyses(PROJECT)[0]

    assert len(restored.claims) == len(AnalysisDimension)
    for claim in restored.claims:
        assert isinstance(claim, AnalysisClaim)
        assert isinstance(claim.dimension, AnalysisDimension)
        assert isinstance(claim.evidence_type, EvidenceType)
        assert isinstance(claim.confidence, Confidence)

    competitor = restored.claim_for(D.COMPETITOR)
    assert competitor.organization_name == "Fictional Alpha Water Systems"
    route = restored.claim_for(D.SALES_ACCESS_ROUTE)
    assert route.access_route is AccessRoute.PUBLIC_TENDER

    overseas = restored.international_claims[0]
    assert isinstance(overseas, InternationalClaim)
    assert overseas.dimension is InternationalDimension.TARIFF
    assert restored.market_scope is MarketScope.INTERNATIONAL


def test_c2_candidate_fit_and_priority_survive(storage) -> None:
    storage.save_client(_candidate())
    restored = storage.get_clients(PROJECT)[0]

    assert all(isinstance(f, FitAssessment) for f in restored.fit)
    assert restored.fit[0].criterion is FitCriterion.PROBLEM_FIT
    assert restored.fit[0].level is FitLevel.STRONG
    assert restored.fit[1].level is FitLevel.EVIDENCE_NEEDED
    assert isinstance(restored.priority, PriorityDecision)
    assert restored.priority.band is SalesPriority.P2
    assert restored.priority.reason_codes == [PriorityReasonCode.INSUFFICIENT_EVIDENCE]
    assert isinstance(restored.identity, OrganizationIdentity)
    assert restored.identity.legal_name == "Fictional Alpha Water Systems Co., Ltd."
    assert restored.market_scope is MarketScope.INTERNATIONAL


# -- D: ref and text stay apart --------------------------------------------

def test_d_proposal_refs_and_text_survive_separately(storage) -> None:
    storage.save_proposal_strategy(_strategy())
    restored = storage.get_proposal_strategies(PROJECT)[0]

    assert [(e.ref, e.text) for e in restored.selected_solution_elements] == [
        ("S1", "다항목 수질 측정 모듈"),
        ("S2", "원격 조회 기능"),
    ]
    assert all(isinstance(e, SelectedSolutionElement) for e in restored.selected_solution_elements)

    assert isinstance(restored.key_message, StrategyStatement)
    assert restored.key_message.solution_element_refs == ["S1", "S2"]
    assert restored.key_message.dimensions == [D.PROBLEM, D.VALUE_DRIVER]

    assert [s.step_type for s in restored.storyline] == [
        StoryStepType.PROBLEM,
        StoryStepType.NEXT_STEP,
    ]
    assert restored.objections[0].basis is ObjectionBasis.EVIDENCE_BACKED
    assert restored.objections[1].basis is ObjectionBasis.ANTICIPATED
    assert restored.evidence_needs[0].timing is EvidenceTiming.BEFORE_PRICING
    assert restored.evidence_needs[1].timing is EvidenceTiming.UNCLASSIFIED
    assert restored.objective is ProposalObjective.PILOT
    assert restored.objective_source is ObjectiveSource.HUMAN


# -- E: pricing, including the gap refs the UI round-trips -----------------

def test_e_pricing_result_and_its_gap_context_survive(storage) -> None:
    storage.save_pricing_result(_pricing())
    restored = storage.get_pricing_results(PROJECT)[0]

    assert restored.status is PricingStatus.PAYLOAD_READY
    assert restored.pricing_case_id == "pcs_1" != restored.strategy_id
    assert restored.pricing_payload["case_id"] == "pcs_1"
    assert "commercial_context" not in restored.pricing_payload

    gap = restored.commercial_context["evidence_needs"][0]
    assert gap["gap_ref"] == "gap_61becf8f3fd0bb8b"
    assert gap["need"] == "연간 계측 예산 규모"
    assert restored.commercial_context["open_gap_counts"]["BEFORE_PRICING"] == 1
    # null stayed null; it did not become 0 on the way through JSON.
    assert restored.pricing_payload["tax"]["vat_rate"] is None


# -- F: a restart is a new instance over the same file ---------------------

def test_f_everything_survives_a_new_instance(db: Path) -> None:
    first = SQLiteStorage(db)
    saved = _populate(first)
    del first

    second = SQLiteStorage(db)
    # Compared against the objects that were stored, not against fresh ones built now: see
    # ``_populate``. The equality is still the full dataclass, ``created_at`` included.
    assert second.get_project(PROJECT) == saved["save_project"]
    for save, get, _build, _expected_id in ALL_NINE:
        if save == "save_project":
            continue
        assert getattr(second, get)(PROJECT) == [saved[save]], save


# -- G/H: agreement with MemoryStorage -------------------------------------

def test_g_saving_the_same_entity_twice_appends_exactly_as_memory_does(storage) -> None:
    """Not an upsert. A primary key on entity_id would have quietly changed this."""
    memory = MemoryStorage()
    for store in (memory, storage):
        store.save_finding(_finding())
        store.save_finding(_finding())

    assert len(memory.get_findings(PROJECT)) == 2
    assert len(storage.get_findings(PROJECT)) == len(memory.get_findings(PROJECT))


def test_g2_only_the_project_replaces(storage) -> None:
    memory = MemoryStorage()
    renamed = Project(company_name="Renamed Fictional Co", project_id=PROJECT)
    for store in (memory, storage):
        store.save_project(_project())
        store.save_project(renamed)

    assert memory.get_project(PROJECT).company_name == "Renamed Fictional Co"
    assert storage.get_project(PROJECT) == memory.get_project(PROJECT)


def test_h_reads_agree_with_memory_on_order_isolation_and_absence(storage) -> None:
    memory = MemoryStorage()
    other = Project(company_name="Other Fictional Co", project_id="prj_other")

    for store in (memory, storage):
        store.save_project(_project())
        store.save_project(other)
        for index in range(3):
            store.save_finding(
                ResearchFinding(
                    project_id=PROJECT,
                    finding=f"statement {index}",
                    evidence_type=EvidenceType.ASSUMPTION,
                    mn_basis=["MN02"],
                    finding_id=f"fnd_{index}",
                )
            )

    assert [f.finding_id for f in storage.get_findings(PROJECT)] == [
        f.finding_id for f in memory.get_findings(PROJECT)
    ] == ["fnd_0", "fnd_1", "fnd_2"]

    # Project isolation and absence behave identically, including the empty-not-error rule.
    assert storage.get_findings("prj_other") == memory.get_findings("prj_other") == []
    assert storage.get_project("prj_missing") is memory.get_project("prj_missing") is None
    for getter in (
        "get_source_metadata", "get_swot_issues", "get_key_issues", "get_clients",
        "get_client_analyses", "get_proposal_strategies", "get_pricing_results",
    ):
        assert getattr(storage, getter)("prj_missing") == []


def test_h2_returned_lists_are_copies_like_memorys(storage) -> None:
    storage.save_finding(_finding())
    returned = storage.get_findings(PROJECT)
    returned.clear()
    assert len(storage.get_findings(PROJECT)) == 1


# -- I/J: evidence candidates and raw documents have nowhere to go ---------

def test_i_there_is_no_way_to_persist_an_evidence_candidate(storage) -> None:
    """The same absence ``tests/test_privacy.py`` asserts for the protocol, for this adapter."""
    for name in dir(storage):
        assert "candidate" not in name.lower() or name in {
            "save_client", "get_clients",  # ClientCandidate is an entity; EvidenceCandidate is not
        }, name
    assert not hasattr(storage, "save_evidence_candidate")
    assert not hasattr(storage, "save_candidate")


def test_j_the_table_has_no_column_that_could_hold_a_document(db: Path, storage) -> None:
    with sqlite3.connect(db) as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )]
        columns = [r[1] for r in conn.execute("PRAGMA table_info(harness_entity)")]

    assert tables == ["harness_entity"], tables
    assert columns == [
        "row_id", "entity_type", "entity_id", "project_id", "payload_json"
    ], columns
    for column in columns:
        for banned in ("file", "document", "blob", "raw", "prompt", "text_content"):
            assert banned not in column.lower(), column


# -- K/L: nothing happens at import; the file appears when asked -----------

def test_k_importing_the_adapter_creates_nothing(tmp_path: Path) -> None:
    """Phase 8's deployment proof was caught by the intake canary for exactly this.

    Run in a subprocess rather than with ``importlib.reload``. A reload is both a weaker
    test — the module is already imported, so most import-time work would not repeat — and a
    dangerous one: it rebinds ``SQLiteStorageError`` to a new class object, after which every
    ``pytest.raises(SQLiteStorageError)`` later in this file silently stops matching. That
    is not hypothetical; it is what happened when this test was first written that way.
    """
    import subprocess
    import sys

    repo_root = Path(__file__).resolve().parent.parent
    probe = tmp_path / "probe.py"
    probe.write_text(
        "\n".join(
            [
                "import pathlib, sys, tempfile",
                f"sys.path.insert(0, {str(repo_root)!r})",
                "root = pathlib.Path(tempfile.gettempdir())",
                "cwd = pathlib.Path.cwd()",
                "before_temp, before_cwd = set(root.iterdir()), set(cwd.iterdir())",
                "import adapters.storage.sqlite",
                "print(sorted(p.name for p in set(root.iterdir()) - before_temp))",
                "print(sorted(p.name for p in set(cwd.iterdir()) - before_cwd))",
            ]
        ),
        encoding="utf-8",
    )

    workdir = tmp_path / "work"
    workdir.mkdir()
    result = subprocess.run(
        [sys.executable, str(probe)], capture_output=True, text=True, cwd=workdir
    )
    assert result.returncode == 0, result.stderr
    temp_created, cwd_created = result.stdout.strip().splitlines()
    assert temp_created == "[]", f"import touched the temp directory: {temp_created}"
    assert cwd_created == "[]", f"import touched the working directory: {cwd_created}"


def test_k2_the_module_has_no_import_time_side_effect() -> None:
    """Structural twin of the test above: no call is evaluated at module level."""
    source = (Path(__file__).resolve().parent.parent / "adapters" / "storage" / "sqlite.py")
    tree = ast.parse(source.read_text(encoding="utf-8"))
    offenders = [
        node.lineno
        for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
    ]
    assert not offenders, offenders


def test_l_the_database_appears_only_when_an_instance_is_built(tmp_path: Path) -> None:
    target = tmp_path / "later.sqlite3"
    assert not target.exists()

    SQLiteStorage(target)
    assert target.exists(), "constructing the adapter is what creates the file"


def test_l2_a_missing_parent_directory_is_refused_not_created(tmp_path: Path) -> None:
    """An adapter that makes directories writes where nobody looked."""
    missing = tmp_path / "nope" / "deeper"
    with pytest.raises(SQLiteStorageError) as raised:
        SQLiteStorage(missing / "h.sqlite3")
    assert raised.value.code == "STORAGE_PATH_UNAVAILABLE"
    assert not missing.exists()


# -- M/N/S: two instances, two threads, one file ---------------------------

def test_m_a_second_instance_reads_the_first_ones_commit(db: Path) -> None:
    writer = SQLiteStorage(db)
    reader = SQLiteStorage(db)

    writer.save_finding(_finding())
    assert [f.finding_id for f in reader.get_findings(PROJECT)] == ["fnd_1"]


def test_n_a_background_thread_can_write_while_the_caller_reads(storage) -> None:
    """The application layer's actual shape: a worker thread writes, a poller reads."""
    errors: list[str] = []
    done = threading.Event()

    def write_many() -> None:
        try:
            for index in range(25):
                storage.save_finding(
                    ResearchFinding(
                        project_id=PROJECT,
                        finding=f"s{index}",
                        evidence_type=EvidenceType.ASSUMPTION,
                        mn_basis=["MN02"],
                        finding_id=f"fnd_{index}",
                    )
                )
        except Exception as exc:  # noqa: BLE001 — the test wants the class, not a crash
            errors.append(type(exc).__name__)
        finally:
            done.set()

    worker = threading.Thread(target=write_many)
    worker.start()
    while not done.is_set():
        storage.get_findings(PROJECT)  # must never raise mid-write
    worker.join(timeout=30)

    assert errors == [], errors
    assert len(storage.get_findings(PROJECT)) == 25


def test_s_wal_is_actually_in_force(storage) -> None:
    assert storage.journal_mode() == "wal"


def test_s2_wal_sidecars_are_a_use_time_artefact_not_an_import_one(db: Path) -> None:
    store = SQLiteStorage(db)
    store.save_finding(_finding())
    # -wal/-shm may or may not linger depending on checkpointing; what matters is that they
    # only ever appear beside the caller's own path.
    for sidecar in db.parent.iterdir():
        assert sidecar.name.startswith(db.name), sidecar.name


# -- O: a save is atomic ---------------------------------------------------

def test_o_a_failed_replace_rolls_back(db: Path, monkeypatch) -> None:
    """``save_project`` deletes then inserts. A crash between the two must not lose the row."""
    storage = SQLiteStorage(db)
    storage.save_project(_project())

    state = {"calls": 0}

    class _InsertFails(sqlite3.Connection):
        """A connection that refuses INSERT. Subclassed because ``execute`` cannot be
        patched on an instance — it is a read-only attribute of the C type."""

        def execute(self, sql, *args, **kwargs):  # type: ignore[override]
            if sql.lstrip().upper().startswith("INSERT"):
                state["calls"] += 1
                raise sqlite3.OperationalError("injected")
            return super().execute(sql, *args, **kwargs)

    def failing_connect(self):
        connection = sqlite3.connect(self.path, timeout=5.0, factory=_InsertFails)
        connection.row_factory = sqlite3.Row
        return connection

    monkeypatch.setattr(SQLiteStorage, "_connect", failing_connect)
    with pytest.raises(SQLiteStorageError):
        storage.save_project(Project(company_name="Should Not Land", project_id=PROJECT))

    monkeypatch.undo()
    assert state["calls"] == 1, "the injected failure did not fire"
    assert SQLiteStorage(db).get_project(PROJECT).company_name == "Fictional Sensor Works"


# -- P/Q/R: the error boundary ---------------------------------------------

def test_p_a_corrupt_database_becomes_a_stable_adapter_error(db: Path) -> None:
    storage = SQLiteStorage(db)
    storage.save_finding(_finding())
    _corrupt(db, b"this is not a database" * 64)

    with pytest.raises(SQLiteStorageError) as raised:
        storage.get_findings(PROJECT)
    assert raised.value.code == "STORAGE_READ_FAILED"
    assert raised.value.sqlite_error_type, "the exception class is kept for debugging"


def test_q_the_error_carries_no_payload_path_or_sql(db: Path) -> None:
    storage = SQLiteStorage(db)
    storage.save_finding(_finding())
    _corrupt(db, b"not a database")

    with pytest.raises(SQLiteStorageError) as raised:
        storage.get_findings(PROJECT)

    text = f"{raised.value} {raised.value!r} {raised.value.args}"
    for leak in (
        str(db), db.name, "SELECT", "INSERT", "harness_entity",
        "수동 채수", "payload_json", "not a database",
    ):
        assert leak not in text, f"{leak!r} reached the error"


def test_q2_a_sqlite_error_never_escapes_as_itself(db: Path) -> None:
    """A caller catching the adapter's error must not also need to know about sqlite3."""
    storage = SQLiteStorage(db)
    _corrupt(db, b"not a database")
    try:
        storage.get_findings(PROJECT)
    except SQLiteStorageError as exc:
        assert exc.__cause__ is None, "the sqlite exception is not chained onwards"
        assert not isinstance(exc, sqlite3.Error)
    else:
        pytest.fail("a corrupt database must not read successfully")


def test_r_an_unsupported_schema_version_is_refused(db: Path) -> None:
    SQLiteStorage(db)
    with sqlite3.connect(db) as conn:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 99}")

    with pytest.raises(SQLiteStorageError) as raised:
        SQLiteStorage(db)
    assert raised.value.code == "STORAGE_SCHEMA_VERSION_UNSUPPORTED"


def test_r2_an_unversioned_database_with_our_table_is_refused(db: Path) -> None:
    """A file from before versions existed is not assumed to be compatible."""
    SQLiteStorage(db)
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA user_version = 0")

    with pytest.raises(SQLiteStorageError) as raised:
        SQLiteStorage(db)
    assert raised.value.code == "STORAGE_SCHEMA_VERSION_UNSUPPORTED"


def test_r3_the_version_is_recorded(storage) -> None:
    assert storage.schema_version() == SCHEMA_VERSION


# -- T: the core still knows nothing about sqlite --------------------------

def test_t_the_core_does_not_depend_on_sqlite() -> None:
    """No import, no call. The word itself is allowed — ``StorageProvider``'s docstring names
    ``"sqlite"`` as an example adapter name, which is the core describing a contract rather
    than depending on an implementation."""
    core = Path(__file__).resolve().parent.parent / "core"
    offenders: list[str] = []
    for path in core.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                offenders += [
                    f"{path.name}:{node.lineno}" for a in node.names if "sqlite" in a.name
                ]
            elif isinstance(node, ast.ImportFrom) and node.module and "sqlite" in node.module:
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, offenders


def test_t2_the_adapter_adds_no_third_party_dependency() -> None:
    """``sqlite3`` is standard library. Nothing new enters requirements.txt for this."""
    source = Path(__file__).resolve().parent.parent / "adapters" / "storage" / "sqlite.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert imported <= {
        "__future__", "json", "sqlite3", "threading", "contextlib", "pathlib", "typing", "core"
    }, imported


# -- the privacy canary: the file itself -----------------------------------

RAW_CANARY = "ZZSQLRAWZZ"
FILENAME_CANARY = "fictional_customer_contract.pdf"
EMAIL_CANARY = "person@example.test"
PHONE_CANARY = "010-0000-0000"


def test_the_database_file_holds_no_raw_document_filename_or_contact(db: Path) -> None:
    """Intake carries all four canaries. Only what an entity legitimately holds may land.

    The document goes through the real intake path, so this is not a test of a mock: the
    bytes exist, they become evidence candidates, and the adapter is then handed the two
    records that are allowed to be stored — the source metadata and a finding derived from
    it. What must not be in the file afterwards is the document, its name, or a person.
    """
    storage = SQLiteStorage(db)
    body = (
        f"# 시장 메모\n\n{RAW_CANARY} 내부 단가표 12,400원\n\n"
        f"문의: {EMAIL_CANARY} / {PHONE_CANARY}\n"
    ).encode("utf-8")

    with IntakeSession(PROJECT, policy=IntakePolicy()) as session:
        result = session.ingest(
            bytearray(body),
            file_type=FileType.MD,
            source_category=SourceCategory.EXTERNAL_BUSINESS_DATA,
            # No display_label: the uploader supplied none, and the filename is structurally
            # unable to reach intake in the first place.
        )
        assert result.candidates, "intake produced nothing to test with"
        storage.save_source_metadata(result.source)

    storage.save_finding(
        ResearchFinding(
            project_id=PROJECT,
            finding="수동 채수로는 측정 주기를 늘리지 못한다",
            evidence_type=EvidenceType.FACT,
            confidence=Confidence.MEDIUM,
            mn_basis=["MN03"],
            source_id=result.source.source_id,
        )
    )

    text = _all_bytes(db).decode("utf-8", errors="ignore")
    for canary in (RAW_CANARY, FILENAME_CANARY, EMAIL_CANARY, PHONE_CANARY, "내부 단가표"):
        assert canary not in text, f"{canary!r} reached the database file"

    # And the test can actually see content — otherwise the assertions above prove nothing.
    assert "수동 채수로는 측정 주기를 늘리지 못한다" in text


def test_a_legitimate_statement_is_stored_and_that_is_not_a_leak(db: Path) -> None:
    """The distinction the canary above depends on, stated on its own.

    A ``ResearchFinding.finding`` is an interpretation somebody chose to keep; a document's
    text is not. Both are strings, and only the second one is a leak.
    """
    storage = SQLiteStorage(db)
    storage.save_client_analysis(_analysis())
    text = _all_bytes(db).decode("utf-8", errors="ignore")

    assert "확인된 내용" in text, "structured claims are stored, by design"
    assert RAW_CANARY not in text


def test_the_stored_payload_is_the_cores_own_serialisation(db: Path) -> None:
    """No bespoke encoder: what is on disk is exactly ``as_dict`` rendered as JSON."""
    from core.models import as_dict

    storage = SQLiteStorage(db)
    strategy = _strategy()
    storage.save_proposal_strategy(strategy)

    with sqlite3.connect(db) as conn:
        stored = conn.execute(
            "SELECT payload_json FROM harness_entity WHERE entity_type='proposal_strategy'"
        ).fetchone()[0]

    assert json.loads(stored) == as_dict(strategy)


# -- the three adapters answer the same questions --------------------------

def test_all_three_storage_adapters_agree_on_absence(storage) -> None:
    for adapter in (NullStorage(), MemoryStorage(), storage):
        assert adapter.get_project("prj_missing") is None
        assert adapter.get_findings("prj_missing") == []


def test_sqlite_has_no_clear_because_it_is_a_persistence_adapter(storage) -> None:
    """``MemoryStorage.clear()`` ends an ephemeral session. On a database it is a wipe.

    It is deliberately absent rather than implemented, and it is not part of
    ``StorageProvider``, so nothing in the core expects it.
    """
    assert not hasattr(storage, "clear")
    assert hasattr(MemoryStorage(), "clear")
