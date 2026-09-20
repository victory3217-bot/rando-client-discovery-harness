# -*- coding: utf-8 -*-
"""The Evidence invariants (HARNESS.md section 6-4).

These are the rules that separate this harness from a tool that produces confident-sounding
output nothing supports. Each test states the failure it prevents.
"""
from __future__ import annotations

import pytest

from core import evidence
from core.errors import EvidenceRuleViolation
from core.models import (
    AnalysisClaim,
    AnalysisDimension,
    ClientAnalysis,
    ClientCandidate,
    Confidence,
    EvidenceType,
    ProposalStrategy,
    ResearchFinding,
    SWOTCategory,
    SWOTIssue,
)

PROJECT = "prj_test"


def _finding(**kwargs) -> ResearchFinding:
    defaults = dict(
        project_id=PROJECT,
        finding="the buyer publishes a quarterly procurement schedule",
        evidence_type=EvidenceType.FACT,
        confidence=Confidence.HIGH,
        mn_basis=["MN03"],
        source_id="src_1",
    )
    defaults.update(kwargs)
    return ResearchFinding(**defaults)


# -- findings --------------------------------------------------------------

def test_grounded_finding_passes() -> None:
    assert evidence.check_finding(_finding()) == []


def test_fact_needs_a_source() -> None:
    """Prevents: an LLM stating a market fact that came from nowhere."""
    violations = evidence.check_finding(_finding(evidence_type=EvidenceType.FACT, source_id=None))
    assert violations and "source_id" in violations[0]


def test_inference_needs_supporting_findings_not_a_source() -> None:
    """An inference rests on other findings, and must not dress itself up as a quotation.

    Copying the first supporting finding's source_id onto an inference would make a conclusion
    look like something a document said - the most convincing way for an analysis to mislead.
    """
    borrowed = _finding(evidence_type=EvidenceType.INFERENCE, source_id="src_1")
    assert evidence.check_finding(borrowed) != []

    grounded = _finding(
        evidence_type=EvidenceType.INFERENCE,
        source_id=None,
        supporting_finding_ids=["fnd_real"],
    )
    assert evidence.check_finding(grounded) == []

    ungrounded = _finding(evidence_type=EvidenceType.INFERENCE, source_id=None)
    assert evidence.check_finding(ungrounded) != []


def test_assumption_may_have_no_source() -> None:
    """An honest gap is allowed; an unlabelled one is not."""
    finding = _finding(
        evidence_type=EvidenceType.ASSUMPTION, source_id=None, evidence_summary="가정임"
    )
    assert evidence.check_finding(finding) == []


def test_missing_evidence_must_say_what_would_close_the_gap() -> None:
    """"We don't know" without "what would tell us" is a shrug, not a research output."""
    silent = _finding(
        evidence_type=EvidenceType.MISSING_EVIDENCE, source_id=None, evidence_summary=None
    )
    assert evidence.check_finding(silent) != []

    useful = _finding(
        evidence_type=EvidenceType.MISSING_EVIDENCE,
        source_id=None,
        evidence_summary="조달 공고 이력이 있으면 확인 가능",
    )
    assert evidence.check_finding(useful) == []


def test_finding_needs_a_framework_basis() -> None:
    """Prevents: findings that cannot be traced back to the question that produced them."""
    violations = evidence.check_finding(_finding(mn_basis=[]))
    assert violations and "mn_basis" in violations[0]


def test_empty_finding_statement_is_rejected() -> None:
    assert evidence.check_finding(_finding(finding="   ")) != []


# -- swot ------------------------------------------------------------------

def test_swot_needs_findings() -> None:
    """Prevents the single most common misuse: asking a model to 'write a SWOT'."""
    issue = SWOTIssue(project_id=PROJECT, category=SWOTCategory.STRENGTH, statement="fast")
    violations = evidence.check_swot_issue(issue)
    assert violations and "finding_ids" in violations[0]


def test_swot_rejects_invented_finding_ids() -> None:
    """Prevents: plausible-looking identifiers that refer to nothing."""
    issue = SWOTIssue(
        project_id=PROJECT,
        category=SWOTCategory.WEAKNESS,
        statement="thin service coverage",
        finding_ids=["fnd_does_not_exist"],
    )
    violations = evidence.check_swot_issue(issue, known_finding_ids=["fnd_real"])
    assert violations and "unknown finding_ids" in violations[0]


def test_swot_with_real_findings_passes() -> None:
    issue = SWOTIssue(
        project_id=PROJECT,
        category=SWOTCategory.OPPORTUNITY,
        statement="scheduled procurement gives a predictable entry point",
        finding_ids=["fnd_real"],
        mn_basis=["MN03"],
    )
    assert evidence.check_swot_issue(issue, known_finding_ids=["fnd_real"]) == []


# -- clients ---------------------------------------------------------------

def test_candidate_without_rationale_is_rejected() -> None:
    """Prevents: an industry company list presented as a discovery result."""
    candidate = ClientCandidate(
        project_id=PROJECT,
        client_name="Fictional Buyer",
        country="VN",
        industry="water treatment",
        discovery_rationale="   ",
        finding_ids=["fnd_real"],
    )
    violations = evidence.check_client_candidate(candidate)
    assert violations and "discovery_rationale" in violations[0]


def test_candidate_without_findings_is_rejected() -> None:
    candidate = ClientCandidate(
        project_id=PROJECT,
        client_name="Fictional Buyer",
        country="VN",
        industry="water treatment",
        discovery_rationale="their stated problem matches our capability",
        finding_ids=[],
    )
    assert evidence.check_client_candidate(candidate) != []


def test_analysis_with_no_evidence_must_declare_the_gap() -> None:
    """Prevents: an empty analysis that reads as a completed one."""
    silent = ClientAnalysis(
        project_id=PROJECT,
        client_id="cli_1",
        client_name="Fictional Buyer",
        country="VN",
        industry="water treatment",
    )
    # Nineteen unanswered dimensions, none of them saying what would settle it.
    assert evidence.check_client_analysis(silent) != []

    honest = ClientAnalysis(
        project_id=PROJECT,
        client_id="cli_1",
        client_name="Fictional Buyer",
        country="VN",
        industry="water treatment",
        claims=[
            AnalysisClaim(dimension=dimension, missing_evidence=["procurement cycle"])
            for dimension in AnalysisDimension
        ],
        missing_evidence=["procurement cycle"],
    )
    assert evidence.check_client_analysis(honest) == []


# -- proposal --------------------------------------------------------------

def test_strategy_needs_an_objective() -> None:
    """Prevents: generating a proposal document before deciding what it is for."""
    strategy = ProposalStrategy(
        project_id=PROJECT, client_id="cli_1", client_name="Fictional Buyer", country="VN"
    )
    violations = evidence.check_proposal_strategy(strategy)
    assert violations and "proposal_objective" in violations[0]

    strategy.proposal_objective = "secure a paid pilot in the next procurement cycle"
    assert evidence.check_proposal_strategy(strategy) == []


# -- raising -------------------------------------------------------------

def test_require_raises_with_every_violation() -> None:
    """A person fixing an analysis should see all the problems at once, not the first one."""
    broken = _finding(evidence_type=EvidenceType.FACT, source_id=None, mn_basis=[], finding="")
    violations = evidence.check_finding(broken)
    assert len(violations) == 3

    with pytest.raises(EvidenceRuleViolation) as excinfo:
        evidence.require(violations)

    assert excinfo.value.code == "EVIDENCE_RULE_VIOLATION"
    assert len(excinfo.value.violations) == 3


def test_require_is_silent_when_valid() -> None:
    evidence.require([])
