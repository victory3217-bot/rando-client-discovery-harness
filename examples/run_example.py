# -*- coding: utf-8 -*-
"""Run the harness end to end, offline, on a fictional company.

    python examples/run_example.py

No API key, no network and no database: memory storage, static knowledge cards, the
deterministic echo LLM and manual search. The intake path creates no temporary file.

What this demonstrates is what exists today — adapter wiring, live file intake with provenance,
the research pipeline running against an offline provider, evidence invariants, framework access
and localisation. Client discovery onwards is not built, and the last section says so rather
than faking it.

Section 5 is worth reading carefully: the offline provider returns nothing, because it has no
knowledge of this market and therefore no fact to establish. Section 6 shows what a completed
diagnosis looks like, using the fictional sample project.

The documents ingested in section 3 are built in memory here. Everything in
examples/sample_project/ is invented too. See HARNESS.md section 9.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

if hasattr(sys.stdout, "reconfigure"):  # Korean output on a cp949 console
    sys.stdout.reconfigure(encoding="utf-8")

from adapters.intake import IntakeSession  # noqa: E402
from adapters.prompts import load_prompt_set  # noqa: E402
from adapters.knowledge.handbook import HandbookKnowledge  # noqa: E402
from adapters.knowledge.static import StaticKnowledge  # noqa: E402
from adapters.llm.echo import EchoLLM  # noqa: E402
from adapters.search.manual import ManualSearch  # noqa: E402
from adapters.storage.memory import MemoryStorage  # noqa: E402
from core import evidence  # noqa: E402
from core.intake import IntakePolicy, provenance_of  # noqa: E402
from core.research import ResearchPolicy, ingest_search_results, run_research  # noqa: E402
from core.harness import create_harness  # noqa: E402
from core.interfaces.search import SearchResult  # noqa: E402
from core.models import (  # noqa: E402
    ClientAnalysis,
    ClientCandidate,
    FileType,
    KeyIssue,
    MarketScope,
    Project,
    ProposalStrategy,
    ResearchFinding,
    SourceCategory,
    SourceMetadata,
    SWOTIssue,
    from_dict,
)

SAMPLE_DIR = REPO_ROOT / "examples" / "sample_project"


def _load(name: str, entity_cls: type) -> list:
    with (SAMPLE_DIR / f"{name}.json").open(encoding="utf-8") as fh:
        payload = json.load(fh)
    records = payload if isinstance(payload, list) else [payload]
    return [from_dict(entity_cls, record) for record in records]


def _labels(lang: str) -> dict:
    with (REPO_ROOT / "locales" / f"{lang}.json").open(encoding="utf-8") as fh:
        return json.load(fh)


def _rule(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def main() -> int:
    # ---- 1. wire the harness ------------------------------------------------
    # This is the only place an embedding system has to change. Swap any of the four and
    # nothing downstream is aware of it.
    harness = create_harness(
        storage=MemoryStorage(),
        knowledge=HandbookKnowledge(
            StaticKnowledge.from_directory(REPO_ROOT / "knowledge" / "master-notes"),
            # A path, not a copy: the methodology stays in its own repository.
            REPO_ROOT.parent / "business-planning-handbook",
        ),
        llm=EchoLLM(),
        search=ManualSearch(
            [
                SearchResult(
                    title="메콩델타 상수도 운영 현황 (가상 자료)",
                    snippet="건기 염분 상승 구간에서 수질 측정 주기 요구가 높아진다.",
                    country="VN",
                    market_scope=MarketScope.INTERNATIONAL,
                )
            ]
        ),
    )

    _rule("1. Adapters")
    for role, name in harness.describe().items():
        print(f"  {role:<10} {name}")

    # ---- 2. load the fictional project -------------------------------------
    project = _load("project", Project)[0]
    sources = _load("source_metadata", SourceMetadata)
    findings = _load("research_finding", ResearchFinding)
    issues = _load("swot_issue", SWOTIssue)
    sample_key_issues = _load("key_issue", KeyIssue)
    candidates = _load("client_candidate", ClientCandidate)
    analyses = _load("client_analysis", ClientAnalysis)
    strategies = _load("proposal_strategy", ProposalStrategy)

    harness.storage.save_project(project)
    for record in sources:
        harness.storage.save_source_metadata(record)
    for record in findings:
        harness.storage.save_finding(record)
    for record in issues:
        harness.storage.save_swot_issue(record)
    for record in sample_key_issues:
        harness.storage.save_key_issue(record)
    for record in candidates:
        harness.storage.save_client(record)
    for record in analyses:
        harness.storage.save_client_analysis(record)
    for record in strategies:
        harness.storage.save_proposal_strategy(record)

    lang = project.output_lang
    labels = _labels(lang)

    _rule("2. Project")
    print(f"  {labels['fields']['company_name']}: {project.company_name}")
    print(
        f"  {labels['fields']['market_scope']}: "
        + ", ".join(labels["enums"]["MarketScope"][s.value] for s in project.market_scope)
    )
    print(f"  {labels['fields']['target_countries']}: {', '.join(project.target_countries)}")
    print(
        f"  storage_mode: {labels['enums']['StorageMode'][project.storage_mode.value]}"
        f"  ({labels['messages']['ephemeral_notice']})"
    )

    # ---- 3. live file intake ------------------------------------------------
    # Documents are built here rather than shipped as files: .gitignore blocks uploaded
    # document types, and a public repository is better off without opaque binaries in it.
    _rule("3. File intake (live, parsed in memory, no temporary file created)")

    uploads = [
        (
            FileType.MD,
            SourceCategory.EXTERNAL_BUSINESS_DATA,
            "메콩델타 시장 메모 (가상)",
            "# 시장 개요\n\n"
            "메콩델타 상수도 사업자는 건기 염분 상승 구간에서 측정 주기를 늘려야 한다.\n\n"
            "## 운영 현황\n\n"
            "현장 인력이 수동 채수에 의존하고 있어 주기를 늘리기 어렵다.\n",
        ),
        (
            FileType.CSV,
            SourceCategory.EXTERNAL_BUSINESS_DATA,
            "사업자 운영 집계 (가상)",
            "utility,region,plants,note\n"
            "Fictional Aqua,Delta,2,수동 채수 의존\n"
            "Fictional Utility 2,Delta,1,측정 주기 확대 검토\n",
        ),
        (
            FileType.HTML,
            SourceCategory.USER_PROVIDED,
            None,  # no label supplied; the application shows a placeholder instead
            "<html><head><style>.x{}</style>"
            "<script>var t='not evidence';</script></head><body>"
            "<!-- internal note, not evidence -->"
            "<h2>조달 일정</h2><p>연 2회 조달 공고가 게시된다.</p></body></html>",
        ),
    ]

    ingested: list = []
    with IntakeSession(project.project_id, policy=IntakePolicy()) as intake:
        for index, (file_type, category, label, body) in enumerate(uploads, start=1):
            result = intake.ingest(
                bytearray(body.encode("utf-8")),
                file_type=file_type,
                source_category=category,
                display_label=label,
            )
            harness.storage.save_source_metadata(result.source)
            ingested.append(result)

            # No label is not an error: the application supplies a placeholder it does not store.
            shown = result.source.display_label or f"Source {index:02d}"
            status = labels["enums"]["ProcessingStatus"][result.source.processing_status.value]
            print(
                f"  {result.source.source_id[:12]}…  {file_type.value:<5} "
                f"{status:<10} candidates={len(result.candidates)}  {shown}"
            )
            for candidate in result.candidates[:2]:
                excerpt = candidate.text.replace("\n", " ")[:54]
                print(f"      [{candidate.locator}] {excerpt}…")

    html_text = " ".join(c.text for c in ingested[2].candidates)
    print("\n  script / style / comment content excluded from evidence:",
          all(term not in html_text for term in ("not evidence", ".x{")))
    print("  repr of a candidate never shows the text:")
    print(f"      {ingested[0].candidates[0]!r}")

    # The handover to Phase 3: interpretation is still to come, provenance already exists.
    provenance = provenance_of(ingested[0].candidates[0], ingested[0].source)
    print("\n  provenance a finding must carry:")
    for key, value in provenance.items():
        shown_value = value.value if hasattr(value, "value") else value
        print(f"      {key}: {shown_value}")
    print("  (Phase 2 assigns no evidence_type — that judgement needs a Master Note question)")

    # ---- 4. sources: metadata only -----------------------------------------
    _rule("4. Sources on record (metadata only, no filenames, no document text)")
    # A file and a retrieved page are different shapes, and the record says which it is rather
    # than giving a web page a fabricated file type.
    for record in harness.storage.get_source_metadata(project.project_id):
        status = labels["enums"]["ProcessingStatus"][record.processing_status.value]
        origin = labels["enums"]["SourceOrigin"][record.source_origin.value]
        detail = f" [{record.error_code}]" if record.error_code else ""

        if record.file_type is not None:
            shape = f"{record.file_type.value:<5} {record.file_size:>9,}B"
        else:
            shape = f"{(record.publisher or '출처 미상')[:24]:<24}"

        print(f"  {record.source_id[:12]}…  {origin:<10} {shape}  {status}{detail}")

    # ---- 5. research pipeline (live, offline) -------------------------------
    # Evidence -> Finding -> SWOT -> Key Issue. The offline provider has no knowledge, so it
    # answers "not established" throughout - which is the honest result and still exercises
    # every stage, every validation rule and every provenance link.
    _rule("5. Research pipeline (live, offline provider)")

    prompt_set = load_prompt_set(REPO_ROOT / "prompts")
    research_candidates = [c for r in ingested for c in r.candidates]
    research_sources = [r.source for r in ingested]

    search_hits = harness.search.search("측정", scope=MarketScope.INTERNATIONAL)
    found_sources, found_candidates = ingest_search_results(
        search_hits, project_id=project.project_id, retrieved_at="2026-09-18T09:05:00+00:00"
    )
    for record in found_sources:
        harness.storage.save_source_metadata(record)
    research_sources += found_sources
    research_candidates += found_candidates

    print(f"  input: {len(research_candidates)} candidates from {len(research_sources)} sources")
    print("         (uploaded files and a search result, one pipeline input type)")

    outcome = run_research(
        project=project,
        candidates=research_candidates,
        sources=research_sources,
        knowledge=harness.knowledge,
        llm=harness.llm,
        prompts=prompt_set,
        policy=ResearchPolicy(),
        frameworks=["MN03", "MN06"],
        today="2026-09-18",
    )

    summary = outcome.summary()
    print(f"  calls: {summary['transmissions']} (2 frameworks x 1 batch, all through one gateway)")
    print(f"  findings: {summary['findings']}  swot: {summary['swot_issues']}"
          f"  key issues: {summary['key_issues']}  rejected: {summary['rejections']}")
    print("  the offline provider produced nothing, which is the correct answer: it has no")
    print("  knowledge of this market, so there is no fact for it to establish. A run that")
    print("  returned findings here would be inventing them.")

    for finding in outcome.findings[:2]:
        print(f"    [{finding.mn_basis[0]}] {finding.evidence_type.value}"
              f"/{finding.confidence.value}: {finding.finding[:44]}")

    # ---- 6. what a completed diagnosis looks like ---------------------------
    # From the fictional sample project, since the offline provider cannot produce one.
    _rule("6. Key issues from the sample project (what a real run produces)")
    for record in harness.storage.get_key_issues(project.project_id):
        print(f"  [{record.decision_area}] {record.statement}")
        print(f"      SWOT {len(record.swot_issue_ids)}건 · 근거 {len(record.finding_ids)}건 · "
              f"{labels['fields']['confidence']}: "
              f"{labels['enums']['Confidence'][record.confidence.value]}")
        if record.strategic_implication:
            print(f"      → {record.strategic_implication[:76]}…")
        for gap in record.missing_evidence[:2]:
            print(f"      ? {gap}")
    print("\n  a key issue binds several SWOT items — it is the question a person must now")
    print("  answer, and the implication supports that decision rather than making it")

    # ---- 7. evidence invariants --------------------------------------------
    # The point of the harness: nothing gets past this without a traceable basis.
    _rule("7. Evidence invariants")
    known_ids = [f.finding_id for f in findings]
    violations: list[str] = []
    for record in findings:
        violations += evidence.check_finding(record)
    for record in issues:
        violations += evidence.check_swot_issue(record, known_finding_ids=known_ids)
    for record in candidates:
        violations += evidence.check_client_candidate(record, known_finding_ids=known_ids)
    for record in analyses:
        violations += evidence.check_client_analysis(record)
    for record in strategies:
        violations += evidence.check_proposal_strategy(record)

    if violations:
        print("  FAILED:")
        for violation in violations:
            print(f"    - {violation}")
        return 1
    print(
        f"  OK - {len(findings)} findings, {len(issues)} SWOT items, "
        f"{len(candidates)} candidates, {len(analyses)} analyses, "
        f"{len(strategies)} strategies all trace back to evidence"
    )

    by_type: dict[str, int] = {}
    for record in findings:
        key = labels["enums"]["EvidenceType"][record.evidence_type.value]
        by_type[key] = by_type.get(key, 0) + 1
    print("  " + " / ".join(f"{k}: {v}" for k, v in sorted(by_type.items())))

    # ---- 8. frameworks ------------------------------------------------------
    _rule("8. Frameworks (analysis questions, not facts)")
    for framework in harness.research_frameworks():
        available = framework.reference.get("handbook_available")
        mark = "handbook found" if available else "cards only"
        print(
            f"  {framework.framework_id}  {framework.title(lang)}  "
            f"({len(framework.dimensions)} dimensions, {mark})"
        )

    per_client = [f.framework_id for f in harness.client_analysis_frameworks()]
    print(f"\n  per-client analysis uses only: {', '.join(per_client)}")
    print("  (MN02 and MN07 diagnose the company, so they are not repeated per client)")

    sample = harness.knowledge.get_framework("MN03")
    print(f"\n  {sample.framework_id} — {sample.title(lang)}")
    for dimension in sample.dimensions[:3]:
        print(f"    - {dimension.label(lang)}: {dimension.question(lang)}")
    print(f"    ... and {len(sample.dimensions) - 3} more")

    # ---- 9. client pipeline -------------------------------------------------
    _rule("9. Client pipeline")
    for record in harness.storage.get_clients(project.project_id):
        print(f"  {record.client_name}  ({record.country}, {record.industry})")
        print(
            f"    {labels['fields']['problem_fit']}: "
            f"{labels['enums']['FitLevel'][record.fit_screening.problem_fit.value]}"
            f" / {labels['fields']['purchasing_potential']}: "
            f"{labels['enums']['FitLevel'][record.priority.purchasing_potential.value]}"
            f" / {labels['fields']['sales_priority']}: "
            f"{labels['enums']['SalesPriority'][record.priority.sales_priority.value]}"
        )

    _rule("10. What is still missing (recorded, not hidden)")
    for record in analyses:
        print(f"  {record.client_name}:")
        for item in record.missing_evidence:
            print(f"    - {item}")

    # ---- 11. llm swap -------------------------------------------------------
    _rule("11. LLM interface")
    finding_schema_path = REPO_ROOT / "schemas" / "research_finding.schema.json"
    with finding_schema_path.open(encoding="utf-8") as fh:
        finding_schema = json.load(fh)

    produced = harness.llm.generate_structured(
        "이 자료에서 MN03 관점의 발견사항을 추출하라.",
        schema=finding_schema,
        output_lang=lang,
    )
    print(f"  provider: {harness.llm.name}")
    print(f"  evidence_type: {produced['evidence_type']}   confidence: {produced['confidence']}")
    print("  (the offline provider answers 'not established' rather than inventing a finding)")
    print(f"\n  {labels['messages']['transmission_notice']}")

    _rule("12. Not built yet")
    for phase, item in [
        ("4-5", "Client discovery, prioritisation, top-3 deep analysis"),
        ("6-7", "Proposal strategy generation, pricing adapter"),
        ("8-9", "Reference dashboard, report output"),
    ]:
        print(f"  Phase {phase:<4} {item}")

    # Ephemeral mode: leave nothing behind, even in memory.
    harness.storage.clear()
    print("\nmemory storage cleared.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
