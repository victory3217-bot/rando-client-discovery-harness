# -*- coding: utf-8 -*-
"""Run the Phase 1 harness end to end, offline, on a fictional company.

    python examples/run_example.py

No API key, no network, no database: memory storage, static knowledge cards, the deterministic
echo LLM and manual search. What this demonstrates is the part of the harness that exists in
Phase 1 — entities, evidence invariants, framework access, adapter wiring and localisation.
The analysis engines themselves arrive in Phases 3-6.

Everything in examples/sample_project/ is invented. See HARNESS.md section 9.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

if hasattr(sys.stdout, "reconfigure"):  # Korean output on a cp949 console
    sys.stdout.reconfigure(encoding="utf-8")

from adapters.knowledge.handbook import HandbookKnowledge  # noqa: E402
from adapters.knowledge.static import StaticKnowledge  # noqa: E402
from adapters.llm.echo import EchoLLM  # noqa: E402
from adapters.search.manual import ManualSearch  # noqa: E402
from adapters.storage.memory import MemoryStorage  # noqa: E402
from core import evidence  # noqa: E402
from core.harness import create_harness  # noqa: E402
from core.interfaces.search import SearchResult  # noqa: E402
from core.models import (  # noqa: E402
    ClientAnalysis,
    ClientCandidate,
    MarketScope,
    Project,
    ProposalStrategy,
    ResearchFinding,
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

    # ---- 3. sources: metadata only -----------------------------------------
    _rule("3. Sources (metadata only, no filenames, no document text)")
    for record in harness.storage.get_source_metadata(project.project_id):
        status = labels["enums"]["ProcessingStatus"][record.processing_status.value]
        detail = f" [{record.error_code}]" if record.error_code else ""
        print(
            f"  {record.source_id}  {record.file_type.value:<5} {record.file_size:>9,}B  "
            f"{status}{detail}"
        )

    # ---- 4. evidence invariants --------------------------------------------
    # The point of the harness: nothing gets past this without a traceable basis.
    _rule("4. Evidence invariants")
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

    # ---- 5. frameworks ------------------------------------------------------
    _rule("5. Frameworks (analysis questions, not facts)")
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

    # ---- 6. client pipeline -------------------------------------------------
    _rule("6. Client pipeline")
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

    _rule("7. What is still missing (recorded, not hidden)")
    for record in analyses:
        print(f"  {record.client_name}:")
        for item in record.missing_evidence:
            print(f"    - {item}")

    # ---- 8. llm swap --------------------------------------------------------
    _rule("8. LLM interface")
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

    _rule("9. Not built yet")
    for phase, item in [
        ("2", "File intake, temporary processing, evidence extraction, cleanup"),
        ("3", "Market research, Master Note diagnosis, SWOT generation"),
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
