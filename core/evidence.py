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
    MAX_FIT_REASON_CHARS,
    ClientAnalysis,
    ClientCandidate,
    EvidenceType,
    FitCriterion,
    FitLevel,
    KeyIssue,
    ProposalStrategy,
    ResearchFinding,
    SourceMetadata,
    SourceOrigin,
    SWOTIssue,
    aggregate_finding_ids,
    aggregate_missing_evidence,
)

#: The only evidence type that names a source document directly.
#:
#: An inference does not: it rests on other findings, and is traced through
#: ``supporting_finding_ids``. Giving it a ``source_id`` copied from the first of those would
#: dress a conclusion up as something a document actually said — the single most convincing way
#: for an analysis to mislead the person reading it.
_DIRECT_TYPES = (EvidenceType.FACT,)

#: Fields that only a direct observation may carry.
_DIRECT_SOURCE_FIELDS = ("source_id", "source_type", "page_or_section", "source_date")


def require(violations: list[str]) -> None:
    """Raise :class:`EvidenceRuleViolation` if ``violations`` is non-empty."""
    if violations:
        raise EvidenceRuleViolation(violations)


def check_finding(
    finding: ResearchFinding,
    known_finding_ids: Optional[Iterable[str]] = None,
) -> list[str]:
    """Each evidence type has to be traceable in the way that type actually works.

    ``FACT`` points at one source passage. ``INFERENCE`` points at the findings it was reasoned
    from and at no source of its own. ``ASSUMPTION`` and ``MISSING_EVIDENCE`` point at nothing,
    and say so.
    """
    violations: list[str] = []
    kind = finding.evidence_type

    if not finding.finding.strip():
        violations.append("finding: statement is empty")

    if not finding.mn_basis:
        violations.append(
            f"finding {finding.finding_id}: mn_basis is empty — every finding is produced by "
            "a Master Note question"
        )

    if kind in _DIRECT_TYPES:
        if not finding.source_id:
            violations.append(
                f"finding {finding.finding_id}: FACT requires source_id (use INFERENCE, "
                "ASSUMPTION or MISSING_EVIDENCE when nothing states it directly)"
            )
        if finding.supporting_finding_ids:
            violations.append(
                f"finding {finding.finding_id}: FACT must not carry supporting_finding_ids — "
                "a direct observation rests on its source, not on other findings"
            )

    elif kind is EvidenceType.INFERENCE:
        if not finding.supporting_finding_ids:
            violations.append(
                f"finding {finding.finding_id}: INFERENCE requires supporting_finding_ids — "
                "an inference that cannot name what it was reasoned from is an assertion"
            )
        elif known_finding_ids is not None:
            known = set(known_finding_ids)
            unknown = [fid for fid in finding.supporting_finding_ids if fid not in known]
            if unknown:
                violations.append(
                    f"finding {finding.finding_id}: supporting_finding_ids not found {unknown}"
                )
        borrowed = [name for name in _DIRECT_SOURCE_FIELDS if getattr(finding, name) is not None]
        if borrowed:
            violations.append(
                f"finding {finding.finding_id}: INFERENCE must leave {borrowed} unset — "
                "borrowing a source field would present a conclusion as a quotation"
            )

    else:  # ASSUMPTION, MISSING_EVIDENCE
        if finding.source_id:
            violations.append(
                f"finding {finding.finding_id}: {kind.value} must not carry source_id"
            )
        if finding.supporting_finding_ids:
            violations.append(
                f"finding {finding.finding_id}: {kind.value} must not carry "
                "supporting_finding_ids"
            )
        if kind is EvidenceType.MISSING_EVIDENCE and not (finding.evidence_summary or "").strip():
            violations.append(
                f"finding {finding.finding_id}: MISSING_EVIDENCE must say in evidence_summary "
                "what would close the gap, otherwise it is only a shrug"
            )

    return violations


def check_source_metadata(source: SourceMetadata) -> list[str]:
    """A source record must describe the shape it actually has.

    An uploaded file has a type and a size; a retrieved page has a title and a time of
    retrieval. Filling the other set with plausible values would put fiction into the one
    record the whole evidence trail hangs from.
    """
    violations: list[str] = []
    origin = source.source_origin
    file_fields = ("file_type", "file_size", "page_count")
    web_fields = ("title", "publisher", "url", "retrieved_at")

    if origin is SourceOrigin.UPLOADED_FILE:
        if source.file_type is None or source.file_size is None:
            violations.append(
                f"source {source.source_id}: UPLOADED_FILE requires file_type and file_size"
            )
        present = [name for name in web_fields if getattr(source, name) is not None]
        if present:
            violations.append(
                f"source {source.source_id}: UPLOADED_FILE must not carry {present} — "
                "a file has no publisher, and a URL here would be a filename in disguise"
            )

    elif origin is SourceOrigin.SEARCH_RESULT:
        if not (source.title or "").strip():
            violations.append(f"source {source.source_id}: SEARCH_RESULT requires a title")
        if not source.retrieved_at:
            violations.append(
                f"source {source.source_id}: SEARCH_RESULT requires retrieved_at — when it was "
                "read matters as much as when it was published"
            )
        present = [name for name in file_fields if getattr(source, name) is not None]
        if present:
            violations.append(
                f"source {source.source_id}: SEARCH_RESULT must not carry {present} — "
                "inventing a file_type for a web page corrupts the provenance trail"
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


def check_key_issue(
    issue: KeyIssue,
    known_swot_ids: Optional[Iterable[str]] = None,
    known_finding_ids: Optional[Iterable[str]] = None,
) -> list[str]:
    """A key issue is derived from SWOT items, so it cannot exist before them.

    This is the same rule as SWOT-needs-findings, one level up: the chain
    Evidence → Finding → SWOT → Key Issue has no shortcut at any link.
    """
    violations: list[str] = []

    if not issue.statement.strip():
        violations.append(f"key issue {issue.key_issue_id}: statement is empty")

    if not (issue.strategic_implication or "").strip():
        violations.append(
            f"key issue {issue.key_issue_id}: strategic_implication is required — an issue "
            "without one is an observation, and a half-filled record reads as a finished one"
        )

    if not issue.decision_area.strip():
        violations.append(
            f"key issue {issue.key_issue_id}: decision_area is empty — an issue that does not "
            "say what decision it bears on is a summary, not an issue"
        )

    if not issue.swot_issue_ids:
        violations.append(
            f"key issue {issue.key_issue_id}: swot_issue_ids is empty — a key issue is derived "
            "from SWOT items, not written alongside them"
        )
    elif known_swot_ids is not None:
        known = set(known_swot_ids)
        unknown = [sid for sid in issue.swot_issue_ids if sid not in known]
        if unknown:
            violations.append(
                f"key issue {issue.key_issue_id}: references unknown swot_issue_ids {unknown}"
            )

    if known_finding_ids is not None and issue.finding_ids:
        known = set(known_finding_ids)
        unknown = [fid for fid in issue.finding_ids if fid not in known]
        if unknown:
            violations.append(
                f"key issue {issue.key_issue_id}: references unknown finding_ids {unknown}"
            )

    return violations


def check_client_candidate(
    candidate: ClientCandidate,
    known_finding_ids: Optional[Iterable[str]] = None,
    known_source_ids: Optional[Iterable[str]] = None,
) -> list[str]:
    """A named organization has to be one the evidence actually names.

    ``source_ids`` is the control that matters most here. It means **discovery and identity
    provenance**: the sources in which this organization appeared. Requiring at least one is
    what makes an invented company name unable to become a stored candidate, because a name
    nothing mentions has no source to cite.

    Evidence for a *criterion* lives on the assessment, not here. The two answer different
    questions and conflating them would hide the first behind the volume of the second.

    ``finding_ids`` and ``missing_evidence`` are checked against the assessments rather than
    read as independent facts. They are derived fields, and a derived field that disagrees with
    its source is how a record starts claiming two different things at once.
    """
    violations: list[str] = []

    if not candidate.discovery_rationale.strip():
        violations.append(
            f"client {candidate.client_id}: discovery_rationale is empty — a company name "
            "without a rationale is an industry list entry, not a candidate"
        )

    if not candidate.source_ids:
        violations.append(
            f"client {candidate.client_id}: source_ids is empty — a candidate must name the "
            "sources this organization appeared in, or it is a name somebody made up"
        )
    elif known_source_ids is not None:
        known = set(known_source_ids)
        unknown = [sid for sid in candidate.source_ids if sid not in known]
        if unknown:
            violations.append(
                f"client {candidate.client_id}: references unknown source_ids {unknown}"
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

    violations.extend(_check_fit(candidate))
    violations.extend(_check_derived_aggregates(candidate))
    return violations


def _check_derived_aggregates(candidate: ClientCandidate) -> list[str]:
    """The candidate-level roll-ups must be exactly what the assessments add up to."""
    violations: list[str] = []

    expected_findings = aggregate_finding_ids(candidate.fit)
    if candidate.finding_ids and candidate.finding_ids != expected_findings:
        violations.append(
            f"client {candidate.client_id}: finding_ids is not the sorted union of the "
            "assessments' finding_ids — it is derived from them, not authored separately"
        )

    expected_missing = aggregate_missing_evidence(candidate.fit)
    if candidate.missing_evidence != expected_missing:
        violations.append(
            f"client {candidate.client_id}: missing_evidence is not the sorted union of the "
            "assessments' missing_evidence"
        )
    if candidate.priority.missing_evidence != expected_missing:
        violations.append(
            f"client {candidate.client_id}: priority.missing_evidence diverges from the "
            "assessments — both derive from the same canonical set"
        )

    return violations


def _check_fit(candidate: ClientCandidate) -> list[str]:
    """All eight criteria, each with what its level requires."""
    violations: list[str] = []

    seen = [assessment.criterion for assessment in candidate.fit]
    missing = [c.value for c in FitCriterion if c not in seen]
    if missing:
        violations.append(
            f"client {candidate.client_id}: no assessment for {missing} — a criterion nobody "
            "looked at must say UNKNOWN, not be absent"
        )
    duplicated = sorted({c.value for c in seen if seen.count(c) > 1})
    if duplicated:
        violations.append(f"client {candidate.client_id}: duplicate assessments for {duplicated}")

    for assessment in candidate.fit:
        name = assessment.criterion.value
        if assessment.level in (FitLevel.STRONG, FitLevel.MODERATE):
            if not (assessment.finding_ids or assessment.source_ids):
                violations.append(
                    f"client {candidate.client_id}: {name} is {assessment.level.value} with no "
                    "finding_ids or source_ids — a favourable rating nobody can check is an "
                    "opinion"
                )
        if assessment.level is FitLevel.EVIDENCE_NEEDED and not assessment.missing_evidence:
            violations.append(
                f"client {candidate.client_id}: {name} is EVIDENCE_NEEDED but does not say "
                "what evidence would settle it"
            )
        if assessment.reason and len(assessment.reason) > MAX_FIT_REASON_CHARS:
            violations.append(
                f"client {candidate.client_id}: {name} reason exceeds "
                f"{MAX_FIT_REASON_CHARS} characters — a reason is an interpretation, not a "
                "copy of the passage"
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
