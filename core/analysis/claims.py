# -*- coding: utf-8 -*-
"""Turning a model's answers into claims, and lowering the ones that are not earned.

Two rules here carry most of the weight.

**A claim's evidence type is not its findings' evidence type.** Three facts joined into a
conclusion make an inference: the joining is the claim, and no document performed it. So the
type comes from the dimension's kind (``core/analysis/dimensions.py``), and a SYNTHESIS
dimension cannot be a FACT however solid its inputs.

**A competitive advantage needs somebody to be better than.** Four conditions, and the fourth
is the one that bites: the claim must cite a finding of its own, read through MN04, that is not
already doing duty as the buying factor or as the competitor's identity. Without it, "we are
better" is a description of our product with a comparison bolted on.
"""
from __future__ import annotations

from typing import Optional, Sequence

from core.analysis.dimensions import (
    COMPARATOR_DIMENSIONS,
    DIMENSION_CEILING,
    DIMENSION_FRAMEWORK,
    DIMENSION_KIND,
    INTERNATIONAL_CEILING,
    INTERNATIONAL_FRAMEWORK,
    NAMED_ORGANIZATION_DIMENSIONS,
    ROUTE_DIMENSIONS,
    VALUE_PROPOSITION_CEILING_WITHOUT_KBF,
    VALUE_PROPOSITION_CEILING_WITH_KBF,
    Kind,
)
from core.analysis.models import ClaimDraft, InternationalDraft
from core.client.verify import name_appears_in
from core.models import (
    MAX_CLAIM_STATEMENT_CHARS,
    AnalysisClaim,
    AnalysisDimension,
    Confidence,
    EvidenceType,
    InternationalClaim,
    ResearchFinding,
)
from core.research.confidence import cap, weakest
from core.research.models import Rejection, ReviewFlag


class AnalysisRejectionCode:
    """Why a claim was refused. Codes, never the text that was refused."""

    #: A name the cited passage does not contain.
    NAME_NOT_IN_EVIDENCE = "NAME_NOT_IN_EVIDENCE"
    #: A reference that resolves to no finding in this run.
    UNKNOWN_EVIDENCE_REF = "UNKNOWN_EVIDENCE_REF"
    #: Two answers for the same dimension.
    DUPLICATE_DIMENSION = "DUPLICATE_DIMENSION"
    #: A dimension that does not belong to the group being answered.
    DIMENSION_OUT_OF_GROUP = "DIMENSION_OUT_OF_GROUP"
    #: A statement longer than the schema allows. Refused, never trimmed.
    STATEMENT_TOO_LONG = "STATEMENT_TOO_LONG"
    #: A competitive advantage with nothing to compare against.
    NO_COMPARISON_BASIS = "NO_COMPARISON_BASIS"
    #: A value proposition with no established problem to address.
    NO_PROBLEM_ESTABLISHED = "NO_PROBLEM_ESTABLISHED"
    #: A client id that is not among the selected candidates.
    UNKNOWN_CLIENT_ID = "UNKNOWN_CLIENT_ID"
    #: More clients than one run may analyse. The whole request is refused.
    TOO_MANY_CLIENTS = "TOO_MANY_CLIENTS"
    #: An international claim on a domestic analysis.
    INTERNATIONAL_ON_DOMESTIC = "INTERNATIONAL_ON_DOMESTIC"


class AnalysisFlagCode:
    """Worth a reader's attention, but not grounds for discarding the claim."""

    SNIPPET_ONLY_EVIDENCE = "SNIPPET_ONLY_EVIDENCE"
    VALUE_PROPOSITION_WITHOUT_KBF = "VALUE_PROPOSITION_WITHOUT_KBF"
    PERSON_NAME_POSSIBLE = "PERSON_NAME_POSSIBLE"


STAGE = "analyze_client"

#: Dimensions whose statement should describe a role, a department or a function rather than a
#: person. Enforced by the prompt, flagged here, and never guaranteed — see docs/privacy.md.
ROLE_PREFERRED_DIMENSIONS = (
    AnalysisDimension.BUYER,
    AnalysisDimension.DECISION_MAKER,
    AnalysisDimension.BUDGET_OWNER,
)


def bounded(value) -> tuple[Optional[str], bool]:
    """The stripped statement and whether it broke the length contract.

    Never returns a shortened string. Cutting a provider's sentence at the cap stores a claim
    nobody made and can reverse its meaning where the clause that was cut carried the negation.
    """
    if not isinstance(value, str):
        return None, False
    stripped = value.strip()
    if not stripped:
        return None, False
    if len(stripped) > MAX_CLAIM_STATEMENT_CHARS:
        return None, True
    return stripped, False


def is_established(claim: Optional[AnalysisClaim]) -> bool:
    """Whether a claim actually answers its question.

    A statement with a reference behind it. Everything else — no statement, no reference, or
    the placeholder a missing answer leaves behind — is an open question.
    """
    return bool(claim and claim.statement and claim.finding_ids)


def _evidence_type(
    dimension: AnalysisDimension,
    cited: Sequence[ResearchFinding],
) -> EvidenceType:
    """What kind of statement this is. A property of the question, not of its inputs."""
    if not cited:
        return EvidenceType.MISSING_EVIDENCE

    kind = DIMENSION_KIND[dimension]
    if kind is Kind.SYNTHESIS:
        # However solid the inputs, joining them is reasoning. Deriving this from the
        # supporting findings would promote every synthesis to FACT the moment its inputs
        # were good, which is precisely backwards.
        return EvidenceType.INFERENCE

    facts = [f for f in cited if f.evidence_type is EvidenceType.FACT]
    if not facts:
        return EvidenceType.INFERENCE

    if kind is Kind.MIXED:
        # Occasionally a document states it outright — a tender's evaluation table really does
        # say what the buying factors are. That only counts when the fact was read through this
        # dimension's own framework; a fact about something else does not make this one stated.
        framework = DIMENSION_FRAMEWORK[dimension]
        if not any(framework in f.mn_basis for f in facts):
            return EvidenceType.INFERENCE

    return EvidenceType.FACT


def _confidence(
    dimension: AnalysisDimension,
    cited: Sequence[ResearchFinding],
    *,
    ceiling_override: Optional[Confidence] = None,
) -> Confidence:
    """The weakest supporting confidence, capped by the dimension's ceiling.

    The research rules already decided what each finding is worth, including the snippet cap.
    Nothing is lowered here for being Phase 5: a dated, attributed, corroborated statement of
    who the incumbent supplier is may reach HIGH, and should.
    """
    if not cited:
        return Confidence.UNKNOWN
    level = weakest([f.confidence for f in cited])
    ceiling = ceiling_override or DIMENSION_CEILING.get(dimension)
    return cap(level, ceiling) if ceiling else level


def resolve_claim(
    draft: ClaimDraft,
    keyed: dict[str, ResearchFinding],
    *,
    passages: Optional[dict[str, str]] = None,
    direct_source_ids: Optional[set[str]] = None,
) -> tuple[AnalysisClaim, list[Rejection], list[ReviewFlag]]:
    """One draft into one claim, refusing what the evidence does not support."""
    rejections: list[Rejection] = []
    flags: list[ReviewFlag] = []
    dimension = draft.dimension
    passages = passages or {}
    direct = direct_source_ids or set()

    resolved = [keyed[ref] for ref in draft.evidence_refs if ref in keyed]
    unresolved = [ref for ref in draft.evidence_refs if ref not in keyed]
    if unresolved:
        rejections.append(
            Rejection(STAGE, AnalysisRejectionCode.UNKNOWN_EVIDENCE_REF, ",".join(unresolved))
        )

    statement = draft.statement
    finding_ids = [f.finding_id for f in resolved]

    # -- a name has to be one the cited passage contains --------------------
    organization_name = None
    if draft.organization_name and dimension in NAMED_ORGANIZATION_DIMENSIONS:
        text = " ".join(
            passages.get(f.finding_id, "") + " " + (f.finding or "") for f in resolved
        )
        if name_appears_in(draft.organization_name, text):
            organization_name = draft.organization_name.strip()
        else:
            rejections.append(
                Rejection(STAGE, AnalysisRejectionCode.NAME_NOT_IN_EVIDENCE, dimension.value)
            )
            # The statement went with it: a sentence about an organization that is not in the
            # evidence is about nothing this harness can show anyone.
            statement = None
            finding_ids = []

    access_route = draft.access_route if dimension in ROUTE_DIMENSIONS else None

    # -- a statement with no reference behind it is an opinion --------------
    if statement and not finding_ids:
        statement = None

    cited = [f for f in resolved if f.finding_id in finding_ids]
    missing = list(draft.missing_evidence)
    if not statement and not missing:
        missing = [f"evidence for {dimension.value.lower().replace('_', ' ')}"]

    claim = AnalysisClaim(
        dimension=dimension,
        statement=statement,
        finding_ids=finding_ids,
        missing_evidence=missing,
        evidence_type=_evidence_type(dimension, cited) if statement else EvidenceType.MISSING_EVIDENCE,
        confidence=_confidence(dimension, cited) if statement else Confidence.UNKNOWN,
        framework_basis=sorted({mn for f in cited for mn in f.mn_basis}),
        organization_name=organization_name,
        access_route=access_route,
    )

    if statement and cited and not any(f.source_id in direct for f in cited if f.source_id):
        if any(f.source_id for f in cited):
            flags.append(ReviewFlag(STAGE, AnalysisFlagCode.SNIPPET_ONLY_EVIDENCE, dimension.value))

    return claim, rejections, flags


def resolve_international(
    draft: InternationalDraft,
    keyed: dict[str, ResearchFinding],
) -> tuple[InternationalClaim, list[Rejection]]:
    """An overseas claim. Always DIRECT: inferring a tariff is guessing at a published number."""
    rejections: list[Rejection] = []
    resolved = [keyed[ref] for ref in draft.evidence_refs if ref in keyed]
    unresolved = [ref for ref in draft.evidence_refs if ref not in keyed]
    if unresolved:
        rejections.append(
            Rejection(STAGE, AnalysisRejectionCode.UNKNOWN_EVIDENCE_REF, ",".join(unresolved))
        )

    statement = draft.statement if resolved else None
    finding_ids = [f.finding_id for f in resolved] if statement else []
    missing = list(draft.missing_evidence)
    if not statement and not missing:
        missing = [f"evidence for {draft.dimension.value.lower().replace('_', ' ')}"]

    if statement:
        facts = [f for f in resolved if f.evidence_type is EvidenceType.FACT]
        evidence_type = EvidenceType.FACT if facts else EvidenceType.INFERENCE
        confidence = cap(weakest([f.confidence for f in resolved]), INTERNATIONAL_CEILING)
    else:
        evidence_type = EvidenceType.MISSING_EVIDENCE
        confidence = Confidence.UNKNOWN

    return (
        InternationalClaim(
            dimension=draft.dimension,
            statement=statement,
            finding_ids=finding_ids,
            missing_evidence=missing,
            evidence_type=evidence_type,
            confidence=confidence,
            framework_basis=sorted({mn for f in resolved for mn in f.mn_basis}) if statement else [],
        ),
        rejections,
    )


def apply_cross_dimension_rules(
    claims: dict[AnalysisDimension, AnalysisClaim],
    *,
    our_solution: str,
) -> tuple[list[Rejection], list[ReviewFlag]]:
    """The two claims that depend on other claims. Mutates ``claims`` in place.

    Run after every framework group, because a competitive advantage in MN04 depends on a
    buying factor from MN03 and neither group can see the other while it is being answered.
    """
    rejections: list[Rejection] = []
    flags: list[ReviewFlag] = []

    D = AnalysisDimension
    kbf = claims.get(D.KBF)
    problem = claims.get(D.PROBLEM)

    # -- value proposition: a problem and something to offer ----------------
    proposition = claims.get(D.VALUE_PROPOSITION)
    if proposition and proposition.statement:
        if not is_established(problem) or not our_solution.strip():
            # Without a problem it is a description of our product addressed to nobody.
            rejections.append(
                Rejection(STAGE, AnalysisRejectionCode.NO_PROBLEM_ESTABLISHED, D.VALUE_PROPOSITION.value)
            )
            _unsettle(proposition, "the customer problem this would address")
        elif is_established(kbf):
            proposition.confidence = cap(proposition.confidence, VALUE_PROPOSITION_CEILING_WITH_KBF)
        else:
            # Allowed, but it is a hypothesis about an unknown buying standard. The gap is
            # recorded rather than the claim removed.
            proposition.confidence = cap(
                proposition.confidence, VALUE_PROPOSITION_CEILING_WITHOUT_KBF
            )
            flags.append(
                ReviewFlag(STAGE, AnalysisFlagCode.VALUE_PROPOSITION_WITHOUT_KBF, D.KBF.value)
            )
            _add_gap(proposition, "the customer's buying factors, to test this against")

    # -- competitive advantage: four conditions -----------------------------
    advantage = claims.get(D.COMPETITIVE_ADVANTAGE)
    if advantage and advantage.statement:
        comparators = [claims.get(d) for d in COMPARATOR_DIMENSIONS]
        established_comparators = [c for c in comparators if is_established(c)]

        spent: set[str] = set()
        if is_established(kbf):
            spent.update(kbf.finding_ids)
        for comparator in established_comparators:
            spent.update(comparator.finding_ids)

        own = [fid for fid in advantage.finding_ids if fid not in spent]
        own_is_mn04 = "MN04" in advantage.framework_basis

        if not is_established(kbf):
            _fail_advantage(advantage, rejections, "the buying factors the comparison rests on")
        elif not established_comparators:
            _fail_advantage(advantage, rejections, "who or what we are being compared with")
        elif not own:
            # Re-citing the buying factor and the competitor's name proves both exist. It says
            # nothing about a difference between them and us.
            _fail_advantage(advantage, rejections, "evidence of a difference from that alternative")
        elif not own_is_mn04:
            _fail_advantage(advantage, rejections, "comparison evidence read through MN04")

    return rejections, flags


def _fail_advantage(claim: AnalysisClaim, rejections: list[Rejection], gap: str) -> None:
    rejections.append(
        Rejection(STAGE, AnalysisRejectionCode.NO_COMPARISON_BASIS, claim.dimension.value)
    )
    _unsettle(claim, gap)


def _unsettle(claim: AnalysisClaim, gap: str) -> None:
    """Take the claim back to an open question, keeping what it would need to close."""
    claim.statement = None
    claim.finding_ids = []
    claim.framework_basis = []
    claim.evidence_type = EvidenceType.MISSING_EVIDENCE
    claim.confidence = Confidence.UNKNOWN
    _add_gap(claim, gap)


def _add_gap(claim: AnalysisClaim, gap: str) -> None:
    if gap not in claim.missing_evidence:
        claim.missing_evidence.append(gap)


def source_ids_for(claim, findings_by_id: dict[str, ResearchFinding]) -> list[str]:
    """The sources behind a claim, through its findings.

    Derived rather than stored. A second copy on the claim would be a second thing to keep in
    step with the first, and the answer is one lookup away.
    """
    out: list[str] = []
    for finding_id in claim.finding_ids:
        finding = findings_by_id.get(finding_id)
        if finding and finding.source_id and finding.source_id not in out:
            out.append(finding.source_id)
    return sorted(out)
