# -*- coding: utf-8 -*-
"""Evidence invariants — the rules that keep this harness honest.

Every ``check_*`` function returns a list of human-readable violation strings; an empty list
means valid. That matches the convention used by the companion pricing harness
(``validate_client_input(instance) -> list[str]``), so a caller handles both the same way.

Callers that would rather fail loudly wrap a check in :func:`require`.

The rules themselves are documented in HARNESS.md section 6-4. They exist because the failure
mode of an analysis tool is not crashing — it is producing a confident-looking conclusion that
nothing supports.
"""
from __future__ import annotations

from typing import Iterable, Optional

from core.errors import EvidenceRuleViolation
from core.models import (
    ClientAnalysis,
    ClientCandidate,
    EvidenceType,
    ProposalStrategy,
    ResearchFinding,
    SWOTIssue,
)

#: Evidence types that are allowed to exist without pointing at a source document. An assumption
#: and a known gap are both legitimate — as long as they are labelled as such.
_SOURCELESS_TYPES = (EvidenceType.ASSUMPTION, EvidenceType.MISSING_EVIDENCE)


def require(violations: list[str]) -> None:
    """Raise :class:`EvidenceRuleViolation` if ``violations`` is non-empty."""
    if violations:
        raise EvidenceRuleViolation(violations)


def check_finding(finding: ResearchFinding) -> list[str]:
    """A finding must either name its source or admit that it has none."""
    violations: list[str] = []

    if not finding.finding.strip():
        violations.append("finding: statement is empty")

    if not finding.source_id and finding.evidence_type not in _SOURCELESS_TYPES:
        violations.append(
            f"finding {finding.finding_id}: evidence_type={finding.evidence_type.value} "
            "requires source_id (use ASSUMPTION or MISSING_EVIDENCE when there is no source)"
        )

    if not finding.mn_basis:
        violations.append(
            f"finding {finding.finding_id}: mn_basis is empty — every finding is produced by "
            "a Master Note question"
        )

    return violations


def check_swot_issue(
    issue: SWOTIssue,
    known_finding_ids: Optional[Iterable[str]] = None,
) -> list[str]:
    """A SWOT item is a compression of findings, so it cannot exist without them.

    When ``known_finding_ids`` is supplied, the referenced ids are also checked for existence —
    that catches an LLM inventing plausible-looking identifiers.
    """
    violations: list[str] = []

    if not issue.statement.strip():
        violations.append(f"swot {issue.issue_id}: statement is empty")

    if not issue.finding_ids:
        violations.append(
            f"swot {issue.issue_id}: finding_ids is empty — SWOT is the compressed result of "
            "Master Note analysis, not its starting point"
        )
    elif known_finding_ids is not None:
        known = set(known_finding_ids)
        unknown = [fid for fid in issue.finding_ids if fid not in known]
        if unknown:
            violations.append(
                f"swot {issue.issue_id}: references unknown finding_ids {unknown}"
            )

    return violations


def check_client_candidate(
    candidate: ClientCandidate,
    known_finding_ids: Optional[Iterable[str]] = None,
) -> list[str]:
    """A candidate needs a rationale and at least one finding behind it."""
    violations: list[str] = []

    if not candidate.discovery_rationale.strip():
        violations.append(
            f"client {candidate.client_id}: discovery_rationale is empty — a company name "
            "without a rationale is an industry list entry, not a candidate"
        )

    if not candidate.finding_ids:
        violations.append(f"client {candidate.client_id}: finding_ids is empty")
    elif known_finding_ids is not None:
        known = set(known_finding_ids)
        unknown = [fid for fid in candidate.finding_ids if fid not in known]
        if unknown:
            violations.append(
                f"client {candidate.client_id}: references unknown finding_ids {unknown}"
            )

    return violations


def check_client_analysis(analysis: ClientAnalysis) -> list[str]:
    """An analysis with no evidence must say what evidence it is missing."""
    violations: list[str] = []

    if not analysis.evidence and not analysis.missing_evidence:
        violations.append(
            f"analysis {analysis.analysis_id}: evidence is empty, so missing_evidence must "
            "list what needs to be found"
        )

    return violations


def check_proposal_strategy(strategy: ProposalStrategy) -> list[str]:
    """A proposal strategy must be attached to a client and state its objective."""
    violations: list[str] = []

    if not strategy.client_id:
        violations.append("strategy: client_id is required")

    if not (strategy.proposal_objective or "").strip():
        violations.append(
            f"strategy {strategy.strategy_id}: proposal_objective is empty — the strategy "
            "comes before the document"
        )

    return violations
