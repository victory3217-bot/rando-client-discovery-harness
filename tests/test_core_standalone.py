# -*- coding: utf-8 -*-
"""Delete everything but the core, and the core still works.

This is the automated form of the last success criterion in HARNESS.md: "Reference Web App을
제거해도 Harness Core는 독립적으로 동작한다."

The test copies ``core/`` alone into an empty directory and runs it there. Nothing else from
this repository is present — no ``adapters/``, no ``schemas/``, no ``knowledge/``, no
reference application. If the core has quietly grown a dependency on any of them, the
subprocess fails and so does this test.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Exercises the parts of the core a caller actually depends on: entity construction, the
# evidence invariants, and the framework constants that encode which Master Notes each engine
# uses.
STANDALONE_SCRIPT = """
import sys

from core import evidence
from core.errors import EvidenceRuleViolation
from core.harness import CLIENT_ANALYSIS_FRAMEWORKS, RESEARCH_FRAMEWORKS
from core.models import (
    AnalysisClaim, AnalysisDimension, ClientAnalysis, ClientCandidate, Confidence,
    EvidenceType, FitAssessment, FitCriterion,
    FitLevel, MarketScope, PriorityDecision, Project, ResearchFinding, SWOTCategory, SWOTIssue,
    aggregate_finding_ids, as_dict,
)

project = Project(company_name="Standalone Co", market_scope=[MarketScope.INTERNATIONAL])
assert project.project_id.startswith("prj_")

finding = ResearchFinding(
    project_id=project.project_id,
    finding="a grounded statement",
    evidence_type=EvidenceType.FACT,
    confidence=Confidence.MEDIUM,
    mn_basis=["MN02"],
    source_id="src_abc",
)
assert evidence.check_finding(finding) == []

issue = SWOTIssue(
    project_id=project.project_id,
    category=SWOTCategory.OPPORTUNITY,
    statement="an opportunity",
    finding_ids=[finding.finding_id],
)
assert evidence.check_swot_issue(issue, known_finding_ids=[finding.finding_id]) == []

orphan = SWOTIssue(
    project_id=project.project_id, category=SWOTCategory.THREAT, statement="ungrounded"
)
assert evidence.check_swot_issue(orphan) != []

try:
    evidence.require(evidence.check_swot_issue(orphan))
except EvidenceRuleViolation as exc:
    assert exc.code == "EVIDENCE_RULE_VIOLATION"
else:
    raise AssertionError("require() did not raise on a violation")

analysis = ClientAnalysis(
    project_id=project.project_id, client_id="cli_x", client_name="Fictional Buyer",
    country="VN", industry="water treatment",
    claims=[
        AnalysisClaim(dimension=d, missing_evidence=["procurement cycle"])
        for d in AnalysisDimension
    ],
    missing_evidence=["procurement cycle"],
)
assert evidence.check_client_analysis(analysis) == []
assert len(analysis.claims) == 19

# A dimension that is simply absent is indistinguishable from one nobody could settle.
short = ClientAnalysis(
    project_id=project.project_id, client_id="cli_x", client_name="Fictional Buyer",
    country="VN", industry="water treatment",
    claims=[AnalysisClaim(dimension=AnalysisDimension.BUYER, missing_evidence=["who buys"])],
    missing_evidence=["who buys"],
)
assert evidence.check_client_analysis(short) != []

fit = [
    FitAssessment(
        criterion=c,
        level=FitLevel.MODERATE if c is FitCriterion.PROBLEM_FIT else FitLevel.UNKNOWN,
        finding_ids=[finding.finding_id] if c is FitCriterion.PROBLEM_FIT else [],
    )
    for c in FitCriterion
]
candidate = ClientCandidate(
    project_id=project.project_id, client_name="Fictional Buyer", country="VN",
    industry="water treatment", discovery_rationale="their problem matches our capability",
    source_ids=["src_abc"],
    # Derived from the assessments, not authored alongside them.
    finding_ids=aggregate_finding_ids(fit),
    fit=fit,
    priority=PriorityDecision(),
)
assert evidence.check_client_candidate(candidate) == []
assert len(candidate.fit) == 8
assert candidate.fit_for(FitCriterion.PROBLEM_FIT) is not None
assert candidate.finding_ids == [finding.finding_id]

drifted = ClientCandidate(
    project_id=project.project_id, client_name="Fictional Buyer", country="VN",
    industry="water treatment", discovery_rationale="their problem matches our capability",
    source_ids=["src_abc"], finding_ids=[finding.finding_id, "fnd_nobody_cited"], fit=fit,
)
assert evidence.check_client_candidate(drifted) != []

sourceless = ClientCandidate(
    project_id=project.project_id, client_name="Invented Co", country="VN", industry="x",
    discovery_rationale="a name nothing mentions",
    fit=[FitAssessment(criterion=c) for c in FitCriterion],
)
assert evidence.check_client_candidate(sourceless) != []

assert RESEARCH_FRAMEWORKS == ("MN02", "MN03", "MN04", "MN05", "MN06", "MN07")
assert CLIENT_ANALYSIS_FRAMEWORKS == ("MN03", "MN04", "MN05", "MN06")

payload = as_dict(finding)
assert payload["evidence_type"] == "FACT"

assert not [m for m in sys.modules if m.startswith("adapters")]
print("CORE_STANDALONE_OK")
"""


def test_core_runs_with_nothing_else_present(tmp_path: Path) -> None:
    shutil.copytree(REPO_ROOT / "core", tmp_path / "core")

    # Prove the isolation is real rather than assumed.
    assert not (tmp_path / "adapters").exists()
    assert not (tmp_path / "schemas").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["core"]

    completed = subprocess.run(
        [sys.executable, "-c", STANDALONE_SCRIPT],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0, (
        "the core does not work on its own:\n"
        f"stdout: {completed.stdout}\nstderr: {completed.stderr}"
    )
    assert "CORE_STANDALONE_OK" in completed.stdout


def test_core_needs_only_the_standard_library(tmp_path: Path) -> None:
    """The core must not require anything from ``requirements.txt``.

    ``jsonschema`` is used by the tests and by adapters, never by the core itself. Running the
    core with an empty import path for site-packages would be fragile across environments, so
    this checks the import graph instead: every module the core imports resolves to the
    standard library or to ``core`` itself.
    """
    import ast

    third_party: set[str] = set()
    stdlib = set(sys.stdlib_module_names)

    for path in sorted((REPO_ROOT / "core").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            for name in names:
                top = name.split(".", 1)[0]
                if top not in stdlib and top != "core":
                    third_party.add(f"{path.name}: {name}")

    assert not third_party, (
        f"the core imports non-stdlib modules: {sorted(third_party)}. "
        "Dependencies belong in adapters, so that an embedding system can bring its own."
    )
