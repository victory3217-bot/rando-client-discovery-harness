# -*- coding: utf-8 -*-
"""What deep analysis refuses to keep.

The failures here are quieter than the discovery ones. Nobody invents a company at this stage;
they invent a buyer, a budget, or an advantage — answers that sound like the sort of thing a
document would say, attached to findings that never said it.

Every organization in these fixtures is invented.
"""
from __future__ import annotations

import pytest

from core import evidence
from core.analysis import (
    AnalysisFlagCode,
    AnalysisRejectionCode,
    apply_cross_dimension_rules,
    is_established,
    resolve_claim,
    resolve_international,
    source_ids_for,
)
from core.analysis.claims import bounded
from core.analysis.dimensions import DIMENSION_CEILING, DIMENSION_KIND, Kind
from core.analysis.models import ClaimDraft, InternationalDraft, PartnerProfile
from core.models import (
    MAX_CLAIM_STATEMENT_CHARS,
    AnalysisClaim,
    AnalysisDimension,
    ClientAnalysis,
    Confidence,
    EvidenceType,
    InternationalClaim,
    InternationalDimension,
    MarketScope,
    ResearchFinding,
)

D = AnalysisDimension
PROJECT = "prj_analysis_validation"
ALPHA = "Fictional Alpha Water Systems"


def _finding(
    finding_id: str,
    *,
    mn: str = "MN03",
    kind: EvidenceType = EvidenceType.FACT,
    confidence: Confidence = Confidence.MEDIUM,
    text: str = "조달 공고에 계측 설비 교체가 포함되어 있다",
    source_id: str | None = "src_1",
) -> ResearchFinding:
    return ResearchFinding(
        project_id=PROJECT,
        finding=text,
        evidence_type=kind,
        confidence=confidence,
        mn_basis=[mn],
        source_id=source_id if kind is EvidenceType.FACT else None,
        finding_id=finding_id,
    )


def _resolve(draft, findings, **kwargs):
    keyed = {f.finding_id: f for f in findings}
    passages = {f.finding_id: f.finding for f in findings}
    return resolve_claim(draft, keyed, passages=passages, **kwargs)


# -- a statement needs something behind it ----------------------------------

def test_a_statement_with_no_reference_is_dropped() -> None:
    """A buyer nobody can check is the most expensive kind of guess in this pipeline."""
    claim, _, _ = _resolve(ClaimDraft(dimension=D.BUYER, statement="조달팀"), [])
    assert claim.statement is None
    assert claim.evidence_type is EvidenceType.MISSING_EVIDENCE
    assert claim.missing_evidence, "and it says what would settle it"


@pytest.mark.parametrize("dimension", [D.BUYER, D.DECISION_MAKER, D.BUDGET_OWNER])
def test_the_roles_cannot_be_asserted_without_evidence(dimension) -> None:
    claim, _, _ = _resolve(ClaimDraft(dimension=dimension, statement="구매 담당 부서"), [])
    assert claim.statement is None


def test_company_size_is_not_budget_evidence() -> None:
    """The default move: they are large, therefore they have money.

    Nothing structural can read the sentence — what stops it is that the claim must cite a
    finding, and a finding about headcount is not a finding about budget. Here the model cites
    nothing at all, which is the shape the guess usually arrives in.
    """
    claim, _, _ = _resolve(
        ClaimDraft(dimension=D.BUDGET_EVIDENCE, statement="대규모 공기업이므로 예산이 있다"), []
    )
    assert claim.statement is None
    assert claim.confidence is Confidence.UNKNOWN


def test_an_unresolvable_reference_is_recorded() -> None:
    _, rejections, _ = _resolve(
        ClaimDraft(dimension=D.PROBLEM, statement="문제", evidence_refs=["fnd_nope"]),
        [_finding("fnd_1")],
    )
    assert any(r.code == AnalysisRejectionCode.UNKNOWN_EVIDENCE_REF for r in rejections)


def test_a_long_statement_is_refused_not_truncated() -> None:
    value, too_long = bounded("가" * (MAX_CLAIM_STATEMENT_CHARS + 1))
    assert too_long and value is None, "nothing stored, not even a shortened version"


# -- evidence type comes from the question ----------------------------------

def test_a_direct_dimension_backed_by_a_fact_is_a_fact() -> None:
    claim, _, _ = _resolve(
        ClaimDraft(dimension=D.PROBLEM, statement="수동 채수에 의존한다", evidence_refs=["f1"]),
        [_finding("f1", mn="MN03", kind=EvidenceType.FACT)],
    )
    assert claim.evidence_type is EvidenceType.FACT


def test_a_direct_dimension_backed_only_by_inference_is_an_inference() -> None:
    claim, _, _ = _resolve(
        ClaimDraft(dimension=D.PROBLEM, statement="수동 채수에 의존한다", evidence_refs=["f1"]),
        [_finding("f1", kind=EvidenceType.INFERENCE, source_id=None)],
    )
    assert claim.evidence_type is EvidenceType.INFERENCE


def test_a_synthesis_dimension_is_never_a_fact_however_solid_its_inputs() -> None:
    """Three facts joined into a conclusion make an inference.

    The joining is the claim, and no document performed it. Deriving the type from the
    supporting findings would promote every synthesis the moment its inputs were good, which is
    exactly backwards — and it is the rule this phase was redesigned to avoid.
    """
    facts = [_finding(f"f{i}", mn="MN04", kind=EvidenceType.FACT) for i in range(1, 4)]
    claim, _, _ = _resolve(
        ClaimDraft(
            dimension=D.COMPETITIVE_ADVANTAGE,
            statement="우리가 앞선다",
            evidence_refs=["f1", "f2", "f3"],
        ),
        facts,
    )
    assert all(f.evidence_type is EvidenceType.FACT for f in facts)
    assert claim.evidence_type is EvidenceType.INFERENCE


def test_a_mixed_dimension_needs_a_fact_read_through_its_own_framework() -> None:
    """A tender's evaluation table really does state the buying factors. A fact about
    something else does not make this one stated."""
    off_framework = _finding("f1", mn="MN06", kind=EvidenceType.FACT)
    claim, _, _ = _resolve(
        ClaimDraft(dimension=D.KBF, statement="단가 중심", evidence_refs=["f1"]), [off_framework]
    )
    assert claim.evidence_type is EvidenceType.INFERENCE

    on_framework = _finding("f2", mn="MN03", kind=EvidenceType.FACT)
    claim, _, _ = _resolve(
        ClaimDraft(dimension=D.KBF, statement="평가표에 명시", evidence_refs=["f2"]), [on_framework]
    )
    assert claim.evidence_type is EvidenceType.FACT


def test_every_dimension_has_a_kind() -> None:
    assert set(DIMENSION_KIND) == set(AnalysisDimension)
    assert set(DIMENSION_KIND.values()) == {Kind.DIRECT, Kind.MIXED, Kind.SYNTHESIS}


# -- confidence --------------------------------------------------------------

def test_confidence_is_capped_where_the_dimension_says_so() -> None:
    high = _finding("f1", mn="MN03", kind=EvidenceType.FACT, confidence=Confidence.HIGH)
    claim, _, _ = _resolve(
        ClaimDraft(dimension=D.BUYER, statement="조달팀", evidence_refs=["f1"]), [high]
    )
    assert claim.confidence is Confidence.MEDIUM, "who buys changes without announcement"


def test_an_uncapped_dimension_may_reach_high() -> None:
    """Nothing is lowered for being Phase 5.

    A dated, attributed, corroborated statement of what a customer does today is worth what the
    research rules say it is worth, and capping the whole phase would throw that away.
    """
    assert D.PROBLEM not in DIMENSION_CEILING
    high = _finding("f1", mn="MN03", kind=EvidenceType.FACT, confidence=Confidence.HIGH)
    claim, _, _ = _resolve(
        ClaimDraft(dimension=D.PROBLEM, statement="수동 채수", evidence_refs=["f1"]), [high]
    )
    assert claim.confidence is Confidence.HIGH


def test_confidence_follows_the_weakest_support() -> None:
    findings = [
        _finding("f1", confidence=Confidence.HIGH),
        _finding("f2", confidence=Confidence.LOW),
    ]
    claim, _, _ = _resolve(
        ClaimDraft(dimension=D.PROBLEM, statement="문제", evidence_refs=["f1", "f2"]), findings
    )
    assert claim.confidence is Confidence.LOW


def test_snippet_only_support_is_flagged() -> None:
    finding = _finding("f1", source_id="src_search")
    _, _, flags = _resolve(
        ClaimDraft(dimension=D.PROBLEM, statement="문제", evidence_refs=["f1"]),
        [finding],
        direct_source_ids=set(),
    )
    assert any(f.code == AnalysisFlagCode.SNIPPET_ONLY_EVIDENCE for f in flags)


# -- named organizations -----------------------------------------------------

def test_a_name_the_evidence_does_not_contain_is_refused() -> None:
    claim, rejections, _ = _resolve(
        ClaimDraft(
            dimension=D.COMPETITOR,
            statement="이 공급사가 현재 납품 중이다",
            evidence_refs=["f1"],
            organization_name="Pan-Asia Heavy Electronics",
        ),
        [_finding("f1", mn="MN04", text="현지 공급사 대부분이 단항목 측정기를 판매한다")],
    )
    assert claim.organization_name is None
    assert claim.statement is None, "a sentence about an organization that is not there"
    assert any(r.code == AnalysisRejectionCode.NAME_NOT_IN_EVIDENCE for r in rejections)


def test_a_name_the_evidence_contains_is_kept() -> None:
    claim, rejections, _ = _resolve(
        ClaimDraft(
            dimension=D.COMPETITOR,
            statement="동일 시장에서 단항목 측정기를 공급한다",
            evidence_refs=["f1"],
            organization_name=ALPHA,
        ),
        [_finding("f1", mn="MN04", text=f"{ALPHA}가 단항목 측정기를 공급하고 있다")],
    )
    assert claim.organization_name == ALPHA
    assert not rejections


def test_the_phase_four_verifier_is_reused_unchanged() -> None:
    """Including its refusal to guess an alias."""
    claim, _, _ = _resolve(
        ClaimDraft(
            dimension=D.CURRENT_SOLUTION,
            statement="현재 공급사",
            evidence_refs=["f1"],
            organization_name="ABC Corporation",
        ),
        [_finding("f1", mn="MN04", text="ABC Holdings announced a programme")],
    )
    assert claim.organization_name is None


def test_a_name_on_a_dimension_that_cannot_carry_one_is_dropped() -> None:
    claim, _, _ = _resolve(
        ClaimDraft(
            dimension=D.PROBLEM,
            statement="문제",
            evidence_refs=["f1"],
            organization_name=ALPHA,
        ),
        [_finding("f1", text=f"{ALPHA}는 수동 채수에 의존한다")],
    )
    assert claim.organization_name is None, "PROBLEM is not a named-organization dimension"


def test_a_partner_profile_has_nowhere_to_put_a_company() -> None:
    import dataclasses

    fields = {f.name for f in dataclasses.fields(PartnerProfile)}
    assert "name" not in fields and "organization_name" not in fields
    assert fields == {"partner_type", "rationale", "required_evidence"}


# -- the four alternatives stay four -----------------------------------------

def test_current_solution_competitor_substitute_and_workaround_are_separate() -> None:
    """Collapsing them loses the analysis: what they bought, what they do instead, who sells
    the same answer, and what replaces the answer entirely are four different facts."""
    for dimension in (D.CURRENT_SOLUTION, D.COMPETITOR, D.SUBSTITUTE, D.CURRENT_WORKAROUND):
        assert dimension in AnalysisDimension
    assert len({D.CURRENT_SOLUTION, D.COMPETITOR, D.SUBSTITUTE, D.CURRENT_WORKAROUND}) == 4


# -- value proposition --------------------------------------------------------

def _claims(**overrides) -> dict:
    base = {d: AnalysisClaim(dimension=d, missing_evidence=["gap"]) for d in AnalysisDimension}
    base.update(overrides)
    return base


def _settled(dimension, finding_ids=("f1",), framework="MN03") -> AnalysisClaim:
    return AnalysisClaim(
        dimension=dimension,
        statement="설정됨",
        finding_ids=list(finding_ids),
        evidence_type=EvidenceType.FACT,
        confidence=Confidence.MEDIUM,
        framework_basis=[framework],
    )


def test_a_value_proposition_needs_a_problem() -> None:
    claims = _claims(
        **{
            D.VALUE_PROPOSITION: _settled(D.VALUE_PROPOSITION, framework="MN04"),
        }
    )
    rejections, _ = apply_cross_dimension_rules(claims, our_solution="a sensor")
    assert any(r.code == AnalysisRejectionCode.NO_PROBLEM_ESTABLISHED for r in rejections)
    assert claims[D.VALUE_PROPOSITION].statement is None


def test_a_value_proposition_without_buying_factors_survives_at_low() -> None:
    """A hypothesis about an unknown standard is still worth writing down."""
    claims = _claims(
        **{
            D.PROBLEM: _settled(D.PROBLEM),
            D.VALUE_PROPOSITION: _settled(D.VALUE_PROPOSITION, framework="MN04"),
        }
    )
    rejections, flags = apply_cross_dimension_rules(claims, our_solution="a sensor")
    proposition = claims[D.VALUE_PROPOSITION]
    assert proposition.statement is not None
    assert proposition.confidence is Confidence.LOW
    assert any(f.code == AnalysisFlagCode.VALUE_PROPOSITION_WITHOUT_KBF for f in flags)
    assert any("buying factors" in gap for gap in proposition.missing_evidence)


def test_a_value_proposition_with_buying_factors_may_reach_medium() -> None:
    claims = _claims(
        **{
            D.PROBLEM: _settled(D.PROBLEM),
            D.KBF: _settled(D.KBF, finding_ids=("f2",)),
            D.VALUE_PROPOSITION: _settled(D.VALUE_PROPOSITION, framework="MN04"),
        }
    )
    apply_cross_dimension_rules(claims, our_solution="a sensor")
    assert claims[D.VALUE_PROPOSITION].confidence is Confidence.MEDIUM


def test_a_value_proposition_needs_something_of_ours_to_propose() -> None:
    claims = _claims(
        **{
            D.PROBLEM: _settled(D.PROBLEM),
            D.VALUE_PROPOSITION: _settled(D.VALUE_PROPOSITION, framework="MN04"),
        }
    )
    apply_cross_dimension_rules(claims, our_solution="   ")
    assert claims[D.VALUE_PROPOSITION].statement is None


# -- competitive advantage: the four conditions -------------------------------

def _advantage_claims(*, kbf=True, comparator=True, own_finding=True, mn04=True) -> dict:
    overrides = {}
    if kbf:
        overrides[D.KBF] = _settled(D.KBF, finding_ids=("f_kbf",))
    if comparator:
        overrides[D.COMPETITOR] = _settled(D.COMPETITOR, finding_ids=("f_comp",), framework="MN04")
    refs = ["f_kbf", "f_comp"] + (["f_diff"] if own_finding else [])
    overrides[D.COMPETITIVE_ADVANTAGE] = AnalysisClaim(
        dimension=D.COMPETITIVE_ADVANTAGE,
        statement="비교 기준에서 우리가 앞선다",
        finding_ids=refs,
        evidence_type=EvidenceType.INFERENCE,
        confidence=Confidence.MEDIUM,
        framework_basis=["MN04"] if mn04 else ["MN03"],
    )
    return _claims(**overrides)


def test_competitive_advantage_needs_buying_factors() -> None:
    claims = _advantage_claims(kbf=False)
    rejections, _ = apply_cross_dimension_rules(claims, our_solution="a sensor")
    assert any(r.code == AnalysisRejectionCode.NO_COMPARISON_BASIS for r in rejections)
    assert claims[D.COMPETITIVE_ADVANTAGE].statement is None


def test_competitive_advantage_needs_somebody_to_be_better_than() -> None:
    claims = _advantage_claims(comparator=False)
    rejections, _ = apply_cross_dimension_rules(claims, our_solution="a sensor")
    assert any(r.code == AnalysisRejectionCode.NO_COMPARISON_BASIS for r in rejections)


def test_competitive_advantage_needs_evidence_of_its_own() -> None:
    """Re-citing the buying factor and the competitor proves both exist.

    It says nothing about a difference between them and us, which is the entire claim.
    """
    claims = _advantage_claims(own_finding=False)
    rejections, _ = apply_cross_dimension_rules(claims, our_solution="a sensor")
    assert any(r.code == AnalysisRejectionCode.NO_COMPARISON_BASIS for r in rejections)
    assert claims[D.COMPETITIVE_ADVANTAGE].statement is None


def test_competitive_advantage_needs_that_evidence_read_through_mn04() -> None:
    claims = _advantage_claims(mn04=False)
    rejections, _ = apply_cross_dimension_rules(claims, our_solution="a sensor")
    assert any(r.code == AnalysisRejectionCode.NO_COMPARISON_BASIS for r in rejections)


def test_competitive_advantage_survives_all_four_conditions() -> None:
    claims = _advantage_claims()
    rejections, _ = apply_cross_dimension_rules(claims, our_solution="a sensor")
    assert not any(r.code == AnalysisRejectionCode.NO_COMPARISON_BASIS for r in rejections)
    assert claims[D.COMPETITIVE_ADVANTAGE].statement is not None


def test_a_product_feature_alone_is_not_an_advantage() -> None:
    """The whole point, stated as one case: nothing named on the other side."""
    claims = _claims(
        **{
            D.COMPETITIVE_ADVANTAGE: _settled(D.COMPETITIVE_ADVANTAGE, framework="MN04"),
        }
    )
    apply_cross_dimension_rules(claims, our_solution="단일 모듈 다항목 측정")
    assert claims[D.COMPETITIVE_ADVANTAGE].statement is None


# -- sources are derived, not stored -----------------------------------------

def test_source_ids_are_not_a_field() -> None:
    import dataclasses

    for cls in (AnalysisClaim, InternationalClaim):
        names = {f.name for f in dataclasses.fields(cls)}
        assert "source_ids" not in names, f"{cls.__name__} stores a second copy of provenance"


def test_source_ids_are_reachable_through_the_findings() -> None:
    findings = [_finding("f1", source_id="src_a"), _finding("f2", source_id="src_b")]
    claim = AnalysisClaim(dimension=D.PROBLEM, statement="문제", finding_ids=["f1", "f2"])
    assert source_ids_for(claim, {f.finding_id: f for f in findings}) == ["src_a", "src_b"]


# -- the entity invariants ----------------------------------------------------

def _analysis(**overrides) -> ClientAnalysis:
    claims = [AnalysisClaim(dimension=d, missing_evidence=["gap"]) for d in AnalysisDimension]
    base = dict(
        project_id=PROJECT,
        client_id="cli_1",
        client_name=ALPHA,
        country="VN",
        industry="water",
        our_solution="a sensor",
        claims=claims,
        missing_evidence=["gap"],
    )
    base.update(overrides)
    return ClientAnalysis(**base)


def test_all_nineteen_dimensions_must_be_present() -> None:
    short = _analysis(claims=[AnalysisClaim(dimension=D.BUYER, missing_evidence=["gap"])])
    violations = evidence.check_client_analysis(short)
    assert any("no claim for" in v for v in violations)


def test_a_duplicated_dimension_is_invalid() -> None:
    claims = [AnalysisClaim(dimension=d, missing_evidence=["gap"]) for d in AnalysisDimension]
    claims.append(AnalysisClaim(dimension=D.BUYER, missing_evidence=["gap"]))
    violations = evidence.check_client_analysis(_analysis(claims=claims))
    assert any("duplicate claims" in v for v in violations)


def test_an_analysis_without_a_client_is_invalid() -> None:
    violations = evidence.check_client_analysis(_analysis(client_id=""))
    assert any("client_id is empty" in v for v in violations)


def test_a_statement_without_references_is_invalid() -> None:
    claims = [AnalysisClaim(dimension=d, missing_evidence=["gap"]) for d in AnalysisDimension]
    claims[0] = AnalysisClaim(
        dimension=claims[0].dimension, statement="결론", evidence_type=EvidenceType.FACT
    )
    violations = evidence.check_client_analysis(_analysis(claims=claims, missing_evidence=["gap"]))
    assert any("no finding_ids" in v for v in violations)


def test_an_unanswered_dimension_must_say_what_would_settle_it() -> None:
    claims = [AnalysisClaim(dimension=d, missing_evidence=["gap"]) for d in AnalysisDimension]
    claims[0] = AnalysisClaim(dimension=claims[0].dimension)
    violations = evidence.check_client_analysis(_analysis(claims=claims))
    assert any("would settle it" in v for v in violations)


def test_the_aggregates_must_equal_the_claims() -> None:
    claims = [AnalysisClaim(dimension=d, missing_evidence=["gap"]) for d in AnalysisDimension]
    claims[0].finding_ids = ["f1"]
    violations = evidence.check_client_analysis(
        _analysis(claims=claims, finding_ids=["f1", "f_invented"], missing_evidence=["gap"])
    )
    assert any("sorted union" in v for v in violations)


def test_the_missing_evidence_aggregate_must_equal_the_claims() -> None:
    violations = evidence.check_client_analysis(_analysis(missing_evidence=["something else"]))
    assert any("missing_evidence is not the sorted union" in v for v in violations)


def test_unknown_finding_ids_are_caught() -> None:
    claims = [AnalysisClaim(dimension=d, missing_evidence=["gap"]) for d in AnalysisDimension]
    claims[0].finding_ids = ["f_ghost"]
    claims[0].statement = "결론"
    claims[0].evidence_type = EvidenceType.FACT
    violations = evidence.check_client_analysis(
        _analysis(claims=claims, finding_ids=["f_ghost"], missing_evidence=["gap"]),
        known_finding_ids={"f1"},
    )
    assert any("unknown finding_ids" in v for v in violations)


# -- international ------------------------------------------------------------

def test_a_domestic_analysis_carries_no_international_claims() -> None:
    violations = evidence.check_client_analysis(
        _analysis(
            market_scope=MarketScope.DOMESTIC,
            international_claims=[
                InternationalClaim(
                    dimension=InternationalDimension.TARIFF, missing_evidence=["gap"]
                )
            ],
        )
    )
    assert any("international_claims on a DOMESTIC" in v for v in violations)


def test_there_are_eight_international_dimensions() -> None:
    assert len(list(InternationalDimension)) == 8


def test_an_international_claim_without_evidence_is_a_gap() -> None:
    claim, _ = resolve_international(
        InternationalDraft(dimension=InternationalDimension.TARIFF, statement="관세 없음"), {}
    )
    assert claim.statement is None
    assert claim.evidence_type is EvidenceType.MISSING_EVIDENCE
    assert claim.missing_evidence


def test_an_international_claim_with_evidence_is_kept() -> None:
    finding = _finding("f1", mn="MN06")
    claim, _ = resolve_international(
        InternationalDraft(
            dimension=InternationalDimension.TARIFF,
            statement="계측 장비는 관세 면제 품목이다",
            evidence_refs=["f1"],
        ),
        {"f1": finding},
    )
    assert claim.statement is not None
    assert claim.evidence_type is EvidenceType.FACT
    assert claim.confidence is Confidence.MEDIUM


def test_is_established_needs_both_a_statement_and_a_reference() -> None:
    assert not is_established(None)
    assert not is_established(AnalysisClaim(dimension=D.BUYER, statement="조달팀"))
    assert not is_established(AnalysisClaim(dimension=D.BUYER, finding_ids=["f1"]))
    assert is_established(
        AnalysisClaim(dimension=D.BUYER, statement="조달팀", finding_ids=["f1"])
    )
