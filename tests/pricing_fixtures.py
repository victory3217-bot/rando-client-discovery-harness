# -*- coding: utf-8 -*-
"""Fixture builders for the Phase 7 tests. A tool module, not a test module.

**Every number in here is distinct, and no two of them add, subtract or divide into a third.**
That is the whole design of this file. A test that only asserts "each number in the payload
was one of the numbers supplied" passes a bridge that computed ``10 + 20`` when ``30`` also
happened to be an input. With deliberately awkward values — ``1230007``, ``431009``, ``0.029``
— a computed value cannot coincide with a supplied one, so the same assertion becomes a real
statement about copying.

All data is fictional (``HARNESS.md`` section 9). The client is named as fictional in the
value itself, not only in a comment.
"""
from __future__ import annotations

from typing import Optional, Sequence

from core.models import (
    AnalysisClaim,
    AnalysisDimension,
    ClientAnalysis,
    Confidence,
    EvidenceNeed,
    EvidenceTiming,
    EvidenceType,
    InternationalClaim,
    InternationalDimension,
    MarketScope,
    ObjectiveSource,
    ProposalObjective,
    ProposalStatus,
    ProposalStrategy,
    SelectedSolutionElement,
    StrategyStatement,
)
from core.pricing_bridge import (
    CommercialInput,
    CommercialSourceRef,
    CostItemInput,
    PriceComponentInput,
)

D = AnalysisDimension
I = InternationalDimension

PROJECT = "prj_pricing"
CLIENT = "cli_pricing_1"
ANALYSIS = "cla_pricing_1"
STRATEGY = "prp_pricing_1"

#: One number per contract field, all distinct, none derivable from the others.
VAT_RATE = 0.11
FX_RATE = 1373.0
TARGET_MARGIN = 0.37
SENSOR_PRICE = 1230007
SENSOR_DISCOUNT = 0.13
SENSOR_MARKET_PRICE = 1470011
SERVICE_PRICE = 350003
BOM_AMOUNT = 431009
FEE_RATE = 0.029
SHIPPING_AMOUNT = 17021
SGA_AMOUNT = 2900017
SGA_FREQUENCY = 6
EXPECTED_QUANTITY = 57

#: Every figure the caller supplies, for the "nothing was computed" assertion.
SUPPLIED_NUMBERS = frozenset(
    {
        VAT_RATE,
        FX_RATE,
        TARGET_MARGIN,
        SENSOR_PRICE,
        SENSOR_DISCOUNT,
        SENSOR_MARKET_PRICE,
        SERVICE_PRICE,
        BOM_AMOUNT,
        FEE_RATE,
        SHIPPING_AMOUNT,
        SGA_AMOUNT,
        SGA_FREQUENCY,
    }
)

#: The gap Phase 6 said has to be closed before anybody sets a price. The tests never use
#: this string as an identifier — it is display text. The reference comes from
#: ``budget_gap_ref()``, which is what the gate actually compares.
BUDGET_GAP = "연간 계측 예산 규모"

SETTLED = (
    D.PROBLEM,
    D.KBF,
    D.COMPETITIVE_ADVANTAGE,
    D.VALUE_DRIVER,
    D.PRICE_SENSITIVITY,
    D.BUDGET_EVIDENCE,
    D.PROCUREMENT_CONTEXT,
)


def settled_claim(dimension: AnalysisDimension, statement: Optional[str] = None) -> AnalysisClaim:
    return AnalysisClaim(
        dimension=dimension,
        statement=statement or f"{dimension.value} 에 대해 확인된 내용",
        finding_ids=[f"fnd_{dimension.value.lower()}"],
        evidence_type=EvidenceType.FACT,
        confidence=Confidence.MEDIUM,
        framework_basis=["MN06"],
    )


def build_analysis(
    *,
    market_scope: MarketScope = MarketScope.DOMESTIC,
    settled: Sequence[AnalysisDimension] = SETTLED,
    statements: Optional[dict] = None,
) -> ClientAnalysis:
    statements = statements or {}
    claims = [
        settled_claim(d, statements.get(d))
        if d in settled
        else AnalysisClaim(dimension=d, missing_evidence=[f"gap {d.value}"])
        for d in AnalysisDimension
    ]
    international = []
    if market_scope is MarketScope.INTERNATIONAL:
        international = [
            InternationalClaim(
                dimension=dimension,
                statement=f"{dimension.value} 에 대해 확인된 내용",
                finding_ids=[f"fnd_{dimension.value.lower()}"],
                evidence_type=EvidenceType.FACT,
                confidence=Confidence.MEDIUM,
                framework_basis=["MN06"],
            )
            for dimension in (I.TARIFF, I.CURRENCY_FX)
        ]
    return ClientAnalysis(
        project_id=PROJECT,
        client_id=CLIENT,
        client_name="Fictional Alpha Water Systems",
        country="VN",
        industry="water utilities",
        our_solution="a single-module multi-parameter sensor",
        claims=claims,
        international_claims=international,
        market_scope=market_scope,
        analysis_id=ANALYSIS,
    )


def build_strategy(
    *,
    gaps: Optional[Sequence[EvidenceNeed]] = None,
    elements: Sequence[tuple[str, str]] = (("S1", "다항목 수질 센서"), ("S2", "설치 및 교정 서비스")),
) -> ProposalStrategy:
    if gaps is None:
        gaps = [
            EvidenceNeed(
                need=BUDGET_GAP,
                timing=EvidenceTiming.BEFORE_PRICING,
                dimension=D.BUDGET_EVIDENCE,
            ),
            EvidenceNeed(need="접근 경로", timing=EvidenceTiming.BEFORE_PROPOSAL),
            EvidenceNeed(need="인증 요건", timing=EvidenceTiming.UNCLASSIFIED),
            EvidenceNeed(need="유지보수 조건", timing=EvidenceTiming.OPTIONAL),
        ]
    return ProposalStrategy(
        project_id=PROJECT,
        client_id=CLIENT,
        client_name="Fictional Alpha Water Systems",
        country="VN",
        analysis_id=ANALYSIS,
        strategy_id=STRATEGY,
        objective=ProposalObjective.POC,
        objective_source=ObjectiveSource.HUMAN,
        selected_solution_elements=[
            SelectedSolutionElement(ref=ref, text=text) for ref, text in elements
        ],
        proposed_solution=" / ".join(text for _, text in elements),
        key_message=StrategyStatement(
            text="측정 주기를 인력 증원 없이 확보한다",
            dimensions=[D.PROBLEM, D.VALUE_DRIVER],
            solution_element_refs=["S1"],
        ),
        status=ProposalStatus.STRATEGY_DRAFTED,
        evidence_needs=list(gaps),
    )


def build_commercial(**overrides) -> CommercialInput:
    """The caller's cost sheet. Overridable field by field for the negative cases."""
    defaults = dict(
        contract_version="1.1",
        product_name="Multi-parameter water sensor",
        pricing_model="hybrid",
        base_currency="KRW",
        reporting_currency="USD",
        vat_rate=VAT_RATE,
        rate_base_per_reporting=FX_RATE,
        target_contribution_margin_rate=TARGET_MARGIN,
        expected_quantity=EXPECTED_QUANTITY,
        commercial_conditions=["결제 60일", "보증 24개월"],
        price_components=[
            PriceComponentInput(
                solution_element_ref="S1",
                component_id="sensor",
                component_type="one_time",
                currency="KRW",
                actual_price=SENSOR_PRICE,
                price_includes_vat=True,
                discount_rate=SENSOR_DISCOUNT,
                target_market_price=SENSOR_MARKET_PRICE,
                source=CommercialSourceRef(
                    source_type="quote",
                    source_ref="fnd_budget_evidence",
                    as_of_date="2026-09-01",
                    evidence_type=EvidenceType.FACT,
                ),
            ),
            PriceComponentInput(
                solution_element_ref="S2",
                component_id="service",
                component_type="recurring_annual",
                currency="KRW",
                actual_price=SERVICE_PRICE,
                price_includes_vat=False,
            ),
        ],
        cost_items=[
            CostItemInput(
                item_id="bom",
                label="자재원가",
                cost_category="product_service_direct_cost",
                basis="per_unit",
                applies_to_component="sensor",
                amount=BOM_AMOUNT,
                currency="KRW",
                source=CommercialSourceRef(
                    source_ref="src_costsheet", evidence_type=EvidenceType.INFERENCE
                ),
            ),
            CostItemInput(
                item_id="channel_fee",
                label="채널수수료",
                cost_category="variable_selling_delivery",
                basis="rate_of_gross_payment",
                applies_to_component="sensor",
                rate=FEE_RATE,
            ),
            CostItemInput(
                item_id="shipping",
                label="배송비",
                cost_category="variable_selling_delivery",
                basis="per_order",
                applies_to_component="sensor",
                amount=SHIPPING_AMOUNT,
                currency="KRW",
            ),
            CostItemInput(
                item_id="sga",
                label="판관비",
                cost_category="fixed_operating_cost",
                basis="per_month",
                applies_to_component="shared",
                amount=SGA_AMOUNT,
                currency="KRW",
                allocation_rule="blended_only",
                frequency_per_year=SGA_FREQUENCY,
            ),
        ],
    )
    defaults.update(overrides)
    return CommercialInput(**defaults)


def numeric_leaves(node, path: str = "") -> dict:
    """Every number in a document, keyed by its path. Booleans are not numbers here."""
    found: dict[str, float] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            found.update(numeric_leaves(value, f"{path}.{key}" if path else key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.update(numeric_leaves(value, f"{path}[{index}]"))
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        found[path] = node
    return found


def budget_gap_ref(strategy: Optional[ProposalStrategy] = None) -> str:
    """The ``gap_ref`` of the blocking gap on a fixture strategy.

    Tests ask for the reference rather than constructing one, for the same reason a UI would:
    the ref is derived from the gap, and anything that derives it a second way is a second
    implementation of the rule.
    """
    from core.pricing_bridge import open_before_pricing

    blocking = open_before_pricing(strategy or build_strategy())
    assert len(blocking) == 1, "the default fixture has exactly one blocking gap"
    return blocking[0].gap_ref


def all_blocking_refs(strategy: ProposalStrategy) -> list[str]:
    from core.pricing_bridge import open_before_pricing

    return [gap.gap_ref for gap in open_before_pricing(strategy)]
