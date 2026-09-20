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

from typing import Iterable, Optional, Sequence

from core.errors import EvidenceRuleViolation
from core.models import (
    MAX_CLAIM_STATEMENT_CHARS,
    MAX_FIT_REASON_CHARS,
    AnalysisDimension,
    ClientAnalysis,
    ClientCandidate,
    EvidenceType,
    FitCriterion,
    FitLevel,
    KeyIssue,
    MarketScope,
    ObjectionBasis,
    PricingResult,
    PricingStatus,
    ProposalStatus,
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


def check_client_analysis(
    analysis: ClientAnalysis,
    known_finding_ids: Optional[Iterable[str]] = None,
) -> list[str]:
    """Every dimension answered or openly unanswered, and nothing carrying a second priority.

    The rules mirror ``check_client_candidate``, because the two records fail the same way. A
    claim that is favourable with nothing behind it is an opinion; a dimension that is simply
    absent is indistinguishable from one nobody could settle; and an aggregate that disagrees
    with the claims it was derived from means the record says two things at once.
    """
    violations: list[str] = []

    if not analysis.client_id:
        violations.append(
            f"analysis {analysis.analysis_id}: client_id is empty — an analysis belongs to a "
            "client that was selected, and there is no way to say which"
        )

    seen = [claim.dimension for claim in analysis.claims]
    absent = [d.value for d in AnalysisDimension if d not in seen]
    if absent:
        violations.append(
            f"analysis {analysis.analysis_id}: no claim for {absent} — a dimension nobody "
            "could settle must say so, not be missing"
        )
    duplicated = sorted({d.value for d in seen if seen.count(d) > 1})
    if duplicated:
        violations.append(f"analysis {analysis.analysis_id}: duplicate claims for {duplicated}")

    for claim in analysis.claims:
        violations.extend(_check_claim(analysis.analysis_id, claim))

    if analysis.market_scope is not MarketScope.INTERNATIONAL and analysis.international_claims:
        violations.append(
            f"analysis {analysis.analysis_id}: international_claims on a "
            f"{analysis.market_scope.value} analysis"
        )
    international_seen = [claim.dimension for claim in analysis.international_claims]
    international_duplicated = sorted(
        {d.value for d in international_seen if international_seen.count(d) > 1}
    )
    if international_duplicated:
        violations.append(
            f"analysis {analysis.analysis_id}: duplicate international claims for "
            f"{international_duplicated}"
        )
    for claim in analysis.international_claims:
        violations.extend(_check_claim(analysis.analysis_id, claim))

    parts = list(analysis.claims) + list(analysis.international_claims)
    if analysis.finding_ids != aggregate_finding_ids(parts):
        violations.append(
            f"analysis {analysis.analysis_id}: finding_ids is not the sorted union of the "
            "claims' finding_ids — it is derived from them, not authored separately"
        )
    if analysis.missing_evidence != aggregate_missing_evidence(parts):
        violations.append(
            f"analysis {analysis.analysis_id}: missing_evidence is not the sorted union of "
            "the claims' missing_evidence"
        )

    if known_finding_ids is not None:
        known = set(known_finding_ids)
        unknown = [fid for fid in analysis.finding_ids if fid not in known]
        if unknown:
            violations.append(
                f"analysis {analysis.analysis_id}: references unknown finding_ids {unknown}"
            )

    return violations


def _check_claim(analysis_id: str, claim) -> list[str]:
    """One claim: a statement needs references, and an open question needs a gap."""
    violations: list[str] = []
    name = claim.dimension.value

    if claim.statement and not claim.finding_ids:
        violations.append(
            f"analysis {analysis_id}: {name} states a conclusion with no finding_ids — a "
            "claim nobody can check is an opinion"
        )
    if not claim.statement and not claim.missing_evidence:
        violations.append(
            f"analysis {analysis_id}: {name} is unanswered but does not say what evidence "
            "would settle it"
        )
    if claim.statement and len(claim.statement) > MAX_CLAIM_STATEMENT_CHARS:
        violations.append(
            f"analysis {analysis_id}: {name} statement exceeds {MAX_CLAIM_STATEMENT_CHARS} "
            "characters — a statement is an interpretation, not a copy of the passage"
        )
    if claim.statement and claim.evidence_type is EvidenceType.MISSING_EVIDENCE:
        violations.append(
            f"analysis {analysis_id}: {name} has a statement but an evidence_type of "
            "MISSING_EVIDENCE"
        )
    if getattr(claim, "organization_name", None) and not claim.finding_ids:
        violations.append(
            f"analysis {analysis_id}: {name} names an organization with no finding behind it"
        )

    return violations


def check_proposal_strategy(
    strategy: ProposalStrategy,
    analysis: Optional[ClientAnalysis] = None,
) -> list[str]:
    """Every claim the strategy makes has to point back into an analysis.

    The rules here are mostly about pairs that used to be able to come apart: an objective
    without a source, a response without either evidence or an admission that it has none, an
    evidence-backed objection with nothing behind it. Each one was representable in the old
    flat shape and each one reads, in a finished document, exactly like a supported claim.

    Passing ``analysis`` additionally checks that every referenced dimension is *established*
    there — a reference to a dimension nobody settled is a footnote to an empty page.
    """
    violations: list[str] = []
    sid = strategy.strategy_id

    if not strategy.client_id:
        violations.append("strategy: client_id is required")

    if not strategy.analysis_id:
        violations.append(
            f"strategy {sid}: analysis_id is empty — a strategy reads one ClientAnalysis, and "
            "without it none of its dimension references resolve"
        )

    if analysis is not None:
        if strategy.analysis_id and analysis.analysis_id != strategy.analysis_id:
            violations.append(f"strategy {sid}: analysis_id does not match the analysis given")
        if analysis.client_id != strategy.client_id:
            violations.append(f"strategy {sid}: the analysis belongs to another client")

    # -- the objective and who chose it travel together --------------------
    if (strategy.objective is None) != (strategy.objective_source is None):
        violations.append(
            f"strategy {sid}: objective and objective_source must both be set or both be "
            "absent — an objective nobody owns is one the pipeline chose"
        )
    if strategy.objective is None and strategy.status is not ProposalStatus.NOT_STARTED:
        violations.append(
            f"strategy {sid}: status is {strategy.status.value} with no objective — a strategy "
            "cannot be drafted before anyone has said what it is for"
        )

    # -- what we are offering ----------------------------------------------
    refs = [element.ref for element in strategy.selected_solution_elements]
    duplicated_refs = sorted({ref for ref in refs if refs.count(ref) > 1})
    if duplicated_refs:
        violations.append(
            f"strategy {sid}: the same solution element is selected twice {duplicated_refs}"
        )
    for element in strategy.selected_solution_elements:
        if not element.ref.strip() or not element.text.strip():
            violations.append(
                f"strategy {sid}: a selected solution element is missing its ref or its text — "
                "both come from the caller's list and neither is optional"
            )

    if strategy.proposed_solution and not strategy.selected_solution_elements:
        violations.append(
            f"strategy {sid}: proposed_solution with no selected_solution_elements — what is "
            "offered is assembled from the caller's list, never written freely"
        )

    for label, statement in (
        ("value_proposition", strategy.value_proposition),
        ("key_message", strategy.key_message),
    ):
        violations.extend(
            _check_statement(
                sid,
                label,
                statement,
                [element.ref for element in strategy.selected_solution_elements],
            )
        )

    seen_steps = [step.step_type for step in strategy.storyline]
    duplicated = sorted({s.value for s in seen_steps if seen_steps.count(s) > 1})
    if duplicated:
        violations.append(f"strategy {sid}: duplicate storyline steps {duplicated}")
    for step in strategy.storyline:
        if not step.message.strip():
            violations.append(f"strategy {sid}: {step.step_type.value} step has no message")
        if len(step.message) > MAX_CLAIM_STATEMENT_CHARS:
            violations.append(
                f"strategy {sid}: {step.step_type.value} step exceeds "
                f"{MAX_CLAIM_STATEMENT_CHARS} characters"
            )

    for objection in strategy.objections:
        violations.extend(_check_objection(sid, objection))

    for need in strategy.evidence_needs:
        if not need.need.strip():
            violations.append(f"strategy {sid}: an evidence need has no text")

    if analysis is not None:
        violations.extend(_check_dimension_refs(sid, strategy, analysis))

    return violations


def _check_statement(sid: str, label: str, statement, offered: Sequence[str]) -> list[str]:
    """A statement needs text, a claim behind it, and an offer in front of it.

    ``offered`` is the refs of the selected elements, so the check runs on identifiers rather
    than on prose that happens to match.
    """
    if statement is None:
        return []
    violations: list[str] = []
    if not statement.text.strip():
        violations.append(f"strategy {sid}: {label} is present but empty")
    if len(statement.text) > MAX_CLAIM_STATEMENT_CHARS:
        violations.append(
            f"strategy {sid}: {label} exceeds {MAX_CLAIM_STATEMENT_CHARS} characters"
        )
    if not statement.dimensions:
        violations.append(
            f"strategy {sid}: {label} names no analysis dimension — a sentence the proposal "
            "will make has to say what it rests on"
        )
    if not statement.solution_element_refs:
        violations.append(
            f"strategy {sid}: {label} offers none of the selected solution elements — both "
            "statements exist to propose something, and one proposing nothing in particular "
            "is an observation"
        )
    unknown = sorted(set(statement.solution_element_refs) - set(offered))
    if unknown:
        violations.append(
            f"strategy {sid}: {label} offers {unknown}, which was never selected — the chain "
            "from a sentence to the caller's capability list is broken"
        )
    return violations


def _check_objection(sid: str, objection) -> list[str]:
    violations: list[str] = []
    name = objection.basis.value

    if not objection.objection.strip():
        violations.append(f"strategy {sid}: an objection has no text")
    if objection.basis is ObjectionBasis.EVIDENCE_BACKED and not objection.dimensions:
        violations.append(
            f"strategy {sid}: an {name} objection cites no dimension — then nothing "
            "distinguishes it from one we merely expect"
        )
    if objection.response and not objection.response_dimensions and not objection.missing_evidence:
        violations.append(
            f"strategy {sid}: a response rests on no dimension and admits no gap — an answer "
            "with neither is an assertion dressed as a position"
        )
    return violations


def _check_dimension_refs(
    sid: str, strategy: ProposalStrategy, analysis: ClientAnalysis
) -> list[str]:
    """Every referenced dimension has to be one the analysis actually settled."""
    settled = {
        claim.dimension
        for claim in analysis.claims
        if claim.statement and claim.finding_ids
    }
    unsettled: set[str] = set()

    def check(dimensions) -> None:
        for dimension in dimensions:
            if dimension not in settled:
                unsettled.add(dimension.value)

    for statement in (strategy.value_proposition, strategy.key_message):
        if statement is not None:
            check(statement.dimensions)
    for step in strategy.storyline:
        check(step.dimensions)
    for objection in strategy.objections:
        check(objection.dimensions)
        check(objection.response_dimensions)

    if unsettled:
        return [
            f"strategy {sid}: references dimensions the analysis did not settle "
            f"{sorted(unsettled)}"
        ]
    return []


def check_pricing_result(result: PricingResult) -> list[str]:
    """A pricing case has to say which case it is, and its status has to match what it holds.

    Two kinds of rule are here.

    The first is about **identity across a boundary**. The payload leaves this repository and
    the answer comes back on its own, so the ids inside the payload have to be the record's
    own ids — otherwise the only thing that can rejoin them is a filename, and a filename is
    not a contract.

    The second is about **status not outrunning content**. ``PAYLOAD_READY`` with no payload,
    ``COMPLETED`` with no answer, ``FAILED`` with no code: each of these is a record that
    reads as further along than it is, and a person scanning a list of pricing cases reads
    the status, not the fields.

    The commercial context does not travel. A ``commercial_context`` key inside the payload
    would mean this harness had started extending a contract it does not own — see
    ARCHITECTURE.md section 6.
    """
    violations: list[str] = []
    rid = result.pricing_result_id

    for label, value in (
        ("project_id", result.project_id),
        ("client_id", result.client_id),
        ("pricing_case_id", result.pricing_case_id),
    ):
        if not str(value).strip():
            violations.append(f"pricing result {rid}: {label} is required")

    for label, value in (
        ("strategy_id", result.strategy_id),
        ("analysis_id", result.analysis_id),
    ):
        if not str(value).strip():
            violations.append(
                f"pricing result {rid}: {label} is empty — commercial_context is a copy taken "
                "across a repository boundary, and a copy with no origin cannot be re-checked"
            )

    # -- the payload is this case, or there is no payload -------------------
    payload = result.pricing_payload
    needs_payload = result.status in (
        PricingStatus.HANDOFF_BLOCKED,
        PricingStatus.PAYLOAD_READY,
        PricingStatus.COMPLETED,
    )
    if needs_payload and not payload:
        violations.append(
            f"pricing result {rid}: status is {result.status.value} with no pricing_payload"
        )
    if result.status is PricingStatus.NOT_REQUESTED and payload:
        violations.append(
            f"pricing result {rid}: a payload exists but the status says nobody asked for one"
        )
    if payload:
        if payload.get("client_id") != result.client_id:
            violations.append(
                f"pricing result {rid}: the payload names a different client"
            )
        if payload.get("case_id") != result.pricing_case_id:
            violations.append(
                f"pricing result {rid}: payload case_id is not this case — case_id is the "
                "pricing_case_id, never the strategy_id"
            )
        if "commercial_context" in payload:
            violations.append(
                f"pricing result {rid}: commercial_context is inside the payload. It is ours "
                "and is not sent; the external contract has no field for it"
            )

    # -- the context describes this case ------------------------------------
    context = result.commercial_context
    if context:
        for key, expected in (
            ("pricing_case_id", result.pricing_case_id),
            ("strategy_id", result.strategy_id),
            ("analysis_id", result.analysis_id),
            ("client_id", result.client_id),
        ):
            if key in context and context[key] != expected:
                violations.append(
                    f"pricing result {rid}: commercial_context.{key} does not match the record"
                )

    # -- status and answer travel together ----------------------------------
    if result.status is PricingStatus.COMPLETED and result.engine_result is None:
        violations.append(
            f"pricing result {rid}: COMPLETED with no engine_result"
        )
    if result.engine_result is not None and result.status is not PricingStatus.COMPLETED:
        violations.append(
            f"pricing result {rid}: an engine_result is stored but the status is "
            f"{result.status.value}"
        )
    if result.status is PricingStatus.FAILED and not result.error_code:
        violations.append(f"pricing result {rid}: FAILED with no error_code")
    if result.error_code and result.status is not PricingStatus.FAILED:
        violations.append(
            f"pricing result {rid}: an error_code is recorded but the status is "
            f"{result.status.value}"
        )

    return violations
