# -*- coding: utf-8 -*-
"""What this bridge must never do: invent a number, price something nobody offered, or guess.

Phase 7's failure mode is not a crash. It is a payload that looks complete — every field
populated, every metric computable — because a blank was filled with a zero, a rate was
applied to an amount, or a claim about a client's budget became a price. Every test here is
aimed at one of those.

The numbers in ``pricing_fixtures`` are chosen so that no arithmetic combination of them
coincides with another, which is what makes "this number was copied" a checkable statement
rather than a hopeful one.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from core.models import (
    AnalysisDimension,
    EvidenceNeed,
    EvidenceTiming,
    EvidenceType,
    MarketScope,
    PricingStatus,
)

D = AnalysisDimension
from core.pricing_bridge import (
    CommercialSourceRef,
    CostItemInput,
    PriceComponentInput,
    PricingFlagCode,
    PricingRejectionCode,
    attach_engine_result,
    build_pricing_payload,
    gaps_for,
    open_before_pricing,
    run_pricing_handoff,
    safe_identifier,
)
from pricing_fixtures import (
    BOM_AMOUNT,
    BUDGET_GAP,
    CLIENT,
    EXPECTED_QUANTITY,
    FEE_RATE,
    FX_RATE,
    SENSOR_DISCOUNT,
    SENSOR_MARKET_PRICE,
    SENSOR_PRICE,
    SERVICE_PRICE,
    SGA_AMOUNT,
    SGA_FREQUENCY,
    SHIPPING_AMOUNT,
    SUPPLIED_NUMBERS,
    TARGET_MARGIN,
    VAT_RATE,
    all_blocking_refs,
    budget_gap_ref,
    build_analysis,
    build_commercial,
    build_strategy,
    numeric_leaves,
)

BRIDGE = Path(__file__).resolve().parent.parent / "core" / "pricing_bridge"


def _run(**overrides):
    kwargs = dict(
        analysis=build_analysis(),
        strategy=build_strategy(),
        commercial=build_commercial(),
    )
    kwargs.update(overrides)
    return run_pricing_handoff(**kwargs)


@pytest.fixture
def payload() -> dict:
    build = build_pricing_payload(
        client_id=CLIENT,
        pricing_case_id="pcs_fixed_1",
        strategy=build_strategy(),
        commercial=build_commercial(),
    )
    assert not build.rejections, build.rejections
    return build.payload


def _codes(items) -> set[str]:
    return {item.code for item in items}


# -- A: no model is involved ----------------------------------------------------

@pytest.mark.parametrize("path", sorted(BRIDGE.rglob("*.py")), ids=lambda p: p.name)
def test_phase_seven_has_no_llm(path: Path) -> None:
    """A model that maps a price is a model in a position to change one."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("core.transmission") or node.module.startswith(
                "core.interfaces.llm"
            ):
                offenders.append(f"line {node.lineno}: imports {node.module}")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("core.transmission"):
                    offenders.append(f"line {node.lineno}: imports {alias.name}")
        if isinstance(node, ast.Attribute) and node.attr in {
            "generate",
            "generate_structured",
            "analyze",
            "summarize",
        }:
            offenders.append(f"line {node.lineno}: calls .{node.attr}")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            names = [a.arg for a in (*args.args, *args.posonlyargs, *args.kwonlyargs)]
            for banned in ("llm", "prompt", "prompts", "provider"):
                if banned in names:
                    offenders.append(f"line {node.lineno}: {node.name}({banned}=...)")

    assert not offenders, f"{path.name} reaches for a model: {offenders}"


def test_the_pipeline_signature_takes_no_provider() -> None:
    import inspect

    parameters = set(inspect.signature(run_pricing_handoff).parameters)
    assert parameters == {
        "analysis",
        "strategy",
        "commercial",
        "acknowledged_gap_refs",
        "pricing_case_id",
        "policy",
    }


def test_the_outcome_records_no_transmission() -> None:
    """Every other phase's outcome has a transmissions list. This one has nothing to record."""
    outcome = _run()
    assert not hasattr(outcome, "transmissions")


# -- I: nothing is computed ------------------------------------------------------

@pytest.mark.parametrize("path", sorted(BRIDGE.rglob("*.py")), ids=lambda p: p.name)
def test_the_bridge_contains_no_multiplication_or_division(path: Path) -> None:
    """The five operators a pricing calculation cannot be written without.

    ``+`` and ``-`` are not checked: set difference and a gap counter use them and neither
    touches a contract value. Multiplication, division, modulo and exponentiation have no
    honest use in a bridge, and every pricing formula in the other harness needs one of them.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    banned = (ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow, ast.MatMult)
    offenders = [
        f"line {node.lineno}: {type(node.op).__name__}"
        for node in ast.walk(tree)
        if isinstance(node, (ast.BinOp, ast.AugAssign)) and isinstance(node.op, banned)
    ]
    assert not offenders, f"{path.name} performs arithmetic: {offenders}"


def test_no_number_appears_that_the_caller_did_not_supply(payload) -> None:
    produced = set(numeric_leaves(payload).values())
    assert produced <= SUPPLIED_NUMBERS, {
        path: value
        for path, value in numeric_leaves(payload).items()
        if value not in SUPPLIED_NUMBERS
    }


# -- H: field by field ------------------------------------------------------------

def test_every_number_lands_on_the_field_it_came_from(payload) -> None:
    """Exact mapping, not "a number that happens to match". The fixture values are unique."""
    assert payload["tax"]["vat_rate"] == VAT_RATE
    assert payload["fx"]["rate_base_per_reporting"] == FX_RATE
    assert payload["targets"]["target_contribution_margin_rate"] == TARGET_MARGIN

    components = {c["component_id"]: c for c in payload["product"]["price_components"]}
    assert components["sensor"]["actual_price"] == SENSOR_PRICE
    assert components["sensor"]["discount_rate"] == SENSOR_DISCOUNT
    assert components["sensor"]["target_market_price"] == SENSOR_MARKET_PRICE
    assert components["service"]["actual_price"] == SERVICE_PRICE

    items = {i["item_id"]: i for i in payload["costs"]["items"]}
    assert items["bom"]["amount"] == BOM_AMOUNT
    assert items["bom"]["rate"] is None
    assert items["channel_fee"]["rate"] == FEE_RATE
    assert items["channel_fee"]["amount"] is None
    assert items["shipping"]["amount"] == SHIPPING_AMOUNT
    assert items["sga"]["amount"] == SGA_AMOUNT
    assert items["sga"]["frequency_per_year"] == SGA_FREQUENCY


def test_non_numeric_fields_are_copied_verbatim(payload) -> None:
    assert payload["product"]["name"] == "Multi-parameter water sensor"
    assert payload["fx"]["base_currency"] == "KRW"
    assert payload["fx"]["reporting_currency"] == "USD"
    items = {i["item_id"]: i for i in payload["costs"]["items"]}
    assert items["sga"]["allocation_rule"] == "blended_only"
    assert items["bom"]["label"] == "자재원가"


def test_expected_quantity_is_context_not_payload(payload) -> None:
    """There is no quantity field in the external contract, and one is not improvised."""
    assert EXPECTED_QUANTITY not in set(numeric_leaves(payload).values())
    result = _run().results[0]
    assert result.commercial_context["expected_quantity"] == EXPECTED_QUANTITY


# -- F / G: UNKNOWN is null, never zero --------------------------------------------

def test_unknown_values_reach_the_contract_as_null() -> None:
    build = build_pricing_payload(
        client_id=CLIENT,
        pricing_case_id="pcs_unknown",
        strategy=build_strategy(),
        commercial=build_commercial(
            vat_rate=None,
            rate_base_per_reporting=None,
            target_contribution_margin_rate=None,
            price_components=[
                PriceComponentInput(
                    solution_element_ref="S1",
                    component_id="sensor",
                    component_type="one_time",
                    currency="KRW",
                )
            ],
            cost_items=[
                CostItemInput(
                    item_id="bom",
                    label="자재원가",
                    cost_category="product_service_direct_cost",
                    basis="per_unit",
                    applies_to_component="sensor",
                )
            ],
            pricing_model="one_time",
        ),
    )
    payload = build.payload
    component = payload["product"]["price_components"][0]
    item = payload["costs"]["items"][0]

    assert payload["tax"]["vat_rate"] is None
    assert payload["fx"]["rate_base_per_reporting"] is None
    assert payload["targets"]["target_contribution_margin_rate"] is None
    assert component["actual_price"] is None
    assert component["price_includes_vat"] is None
    assert item["amount"] is None and item["rate"] is None and item["currency"] is None


def test_an_unknown_never_becomes_a_zero() -> None:
    """``0`` means a confirmed zero over there. Substituting one answers a question nobody did."""
    build = build_pricing_payload(
        client_id=CLIENT,
        pricing_case_id="pcs_unknown",
        strategy=build_strategy(),
        commercial=build_commercial(
            vat_rate=None,
            rate_base_per_reporting=None,
            target_contribution_margin_rate=None,
            pricing_model="one_time",
            price_components=[
                PriceComponentInput(
                    solution_element_ref="S1",
                    component_id="sensor",
                    component_type="one_time",
                    currency="KRW",
                )
            ],
            cost_items=[],
        ),
    )
    assert numeric_leaves(build.payload) == {}, "not one number was produced from nothing"


def test_a_confirmed_zero_survives_as_zero() -> None:
    """The other half of the same rule: ``0`` is a value, and is not turned into UNKNOWN."""
    build = build_pricing_payload(
        client_id=CLIENT,
        pricing_case_id="pcs_zero",
        strategy=build_strategy(),
        commercial=build_commercial(
            vat_rate=0,
            pricing_model="one_time",
            price_components=[
                PriceComponentInput(
                    solution_element_ref="S1",
                    component_id="sensor",
                    component_type="one_time",
                    currency="KRW",
                    actual_price=0,
                )
            ],
            cost_items=[],
        ),
    )
    assert build.payload["tax"]["vat_rate"] == 0
    assert build.payload["product"]["price_components"][0]["actual_price"] == 0


# -- R: a claim never becomes a number ----------------------------------------------

def test_an_mn06_claim_never_becomes_a_pricing_number() -> None:
    """The claims are full of figures. The payload is empty of them, because nobody typed one."""
    from core.models import AnalysisDimension as Dim

    analysis = build_analysis(
        market_scope=MarketScope.INTERNATIONAL,
        statements={
            Dim.BUDGET_EVIDENCE: "연간 계측 예산이 8억 4000만원 규모로 공시되어 있다",
            Dim.PRICE_SENSITIVITY: "경쟁 입찰에서 15% 이상 차이를 민감하게 본다",
            Dim.VALUE_DRIVER: "인력 2명분 연 9600만원을 대체한다",
            Dim.PROCUREMENT_CONTEXT: "환율은 1450원 기준으로 예산을 편성한다",
        },
    )
    commercial = build_commercial(
        vat_rate=None,
        rate_base_per_reporting=None,
        target_contribution_margin_rate=None,
        pricing_model="one_time",
        price_components=[
            PriceComponentInput(
                solution_element_ref="S1",
                component_id="sensor",
                component_type="one_time",
                currency="KRW",
            )
        ],
        cost_items=[],
    )
    outcome = run_pricing_handoff(
        analysis=analysis,
        strategy=build_strategy(),
        commercial=commercial,
        acknowledged_gap_refs=[budget_gap_ref()],
        # Pinned: the default case id is a random hex string, and a scan for short digit
        # runs like "15" would hit one roughly once in ten runs. The point of this test is
        # the claims, so the one identifier in the payload is held still.
        pricing_case_id="pcs_mn06_no_numbers",
    )
    result = outcome.results[0]

    assert numeric_leaves(result.pricing_payload) == {}
    serialised = json.dumps(result.pricing_payload, ensure_ascii=False)
    for figure in ("8억", "4000", "15", "9600", "1450"):
        assert figure not in serialised, f"{figure} reached the payload from a claim"

    # The claims are still available — with their provenance — on our side of the boundary.
    assert result.commercial_context["claims"]["BUDGET_EVIDENCE"]["established"] is True
    assert "1450" in result.commercial_context["claims"]["PROCUREMENT_CONTEXT"]["statement"]


def test_an_fx_claim_does_not_populate_the_fx_rate() -> None:
    analysis = build_analysis(market_scope=MarketScope.INTERNATIONAL)
    outcome = run_pricing_handoff(
        analysis=analysis,
        strategy=build_strategy(),
        commercial=build_commercial(rate_base_per_reporting=None),
        acknowledged_gap_refs=[budget_gap_ref()],
    )
    result = outcome.results[0]
    assert result.pricing_payload["fx"]["rate_base_per_reporting"] is None
    assert result.commercial_context["international_claims"]["CURRENCY_FX"]["established"]


# -- J / K: only what was offered is priced --------------------------------------

def test_a_price_for_something_nobody_offered_is_refused() -> None:
    commercial = build_commercial(
        pricing_model="one_time",
        price_components=[
            PriceComponentInput(
                solution_element_ref="S9",
                component_id="training",
                component_type="one_time",
                currency="KRW",
                actual_price=SENSOR_PRICE,
            )
        ],
        cost_items=[],
    )
    outcome = _run(commercial=commercial)
    assert not outcome.results
    assert PricingRejectionCode.UNKNOWN_SOLUTION_ELEMENT in _codes(outcome.rejections)


def test_an_unselected_component_is_refused_whole_not_dropped() -> None:
    """A payload one component short prices less than the proposal offers, and does not say so."""
    commercial = build_commercial(
        price_components=[
            *build_commercial().price_components,
            PriceComponentInput(
                solution_element_ref="S9",
                component_id="training",
                component_type="one_time",
                currency="KRW",
                actual_price=99,
            ),
        ]
    )
    outcome = _run(commercial=commercial)
    assert not outcome.results, "nothing partial is emitted"


def test_an_offered_element_with_no_price_is_flagged_not_refused() -> None:
    """Quoting part of what is offered is a legitimate decision. It is recorded, not blocked."""
    commercial = build_commercial(
        pricing_model="one_time",
        price_components=[
            PriceComponentInput(
                solution_element_ref="S1",
                component_id="sensor",
                component_type="one_time",
                currency="KRW",
                actual_price=SENSOR_PRICE,
            )
        ],
        cost_items=[],
    )
    outcome = _run(commercial=commercial)
    assert outcome.results
    flags = [f for f in outcome.review_flags if f.code == PricingFlagCode.ELEMENT_NOT_PRICED]
    assert [f.reference for f in flags] == ["S2"]


def test_the_binding_survives_where_the_payload_cannot_carry_it() -> None:
    result = _run().results[0]
    offered = {entry["ref"]: entry["component_id"] for entry in result.commercial_context["offered"]}
    assert offered == {"S1": "sensor", "S2": "service"}


# -- B / C: a case is not a strategy -------------------------------------------------

def test_the_case_id_is_not_the_strategy_id() -> None:
    result = _run().results[0]
    assert result.pricing_case_id != result.strategy_id
    assert result.pricing_payload["case_id"] == result.pricing_case_id
    assert result.pricing_payload["case_id"] != result.strategy_id
    assert result.pricing_payload["meta"]["strategy_id"] == result.strategy_id


def test_one_strategy_can_produce_several_pricing_cases() -> None:
    """A different scope or a corrected cost sheet is a new case, not an overwrite."""
    strategy = build_strategy()
    analysis = build_analysis()
    first = run_pricing_handoff(
        analysis=analysis, strategy=strategy, commercial=build_commercial()
    ).results[0]
    second = run_pricing_handoff(
        analysis=analysis,
        strategy=strategy,
        commercial=build_commercial(target_contribution_margin_rate=None),
    ).results[0]

    assert first.strategy_id == second.strategy_id
    assert first.pricing_case_id != second.pricing_case_id
    assert first.pricing_payload["case_id"] != second.pricing_payload["case_id"]


def test_a_case_can_be_rebuilt_in_place_when_that_is_what_is_meant() -> None:
    strategy, analysis = build_strategy(), build_analysis()
    kwargs = dict(analysis=analysis, strategy=strategy, pricing_case_id="pcs_same_case")
    first = run_pricing_handoff(commercial=build_commercial(), **kwargs).results[0]
    second = run_pricing_handoff(commercial=build_commercial(vat_rate=0.13), **kwargs).results[0]
    assert first.pricing_case_id == second.pricing_case_id == "pcs_same_case"


# -- S / T / U: the gate ---------------------------------------------------------------

def test_an_open_before_pricing_gap_blocks_the_handoff() -> None:
    outcome = _run()
    result = outcome.results[0]
    assert result.status is PricingStatus.HANDOFF_BLOCKED
    assert PricingFlagCode.BEFORE_PRICING_GAP_OPEN in _codes(outcome.review_flags)
    assert result.pricing_payload, "the payload is still built, so a person can read it"


def test_acknowledgement_permits_the_handoff_and_is_recorded() -> None:
    outcome = _run(acknowledged_gap_refs=[budget_gap_ref()])
    assert outcome.results[0].status is PricingStatus.PAYLOAD_READY
    assert PricingFlagCode.GAPS_ACKNOWLEDGED in _codes(outcome.review_flags)


def test_acknowledging_one_gap_does_not_cover_a_second() -> None:
    strategy = build_strategy(
        gaps=[
            EvidenceNeed(need=BUDGET_GAP, timing=EvidenceTiming.BEFORE_PRICING),
            EvidenceNeed(need="구매 승인 한도", timing=EvidenceTiming.BEFORE_PRICING),
        ]
    )
    first, second = all_blocking_refs(strategy)
    assert first != second

    outcome = _run(strategy=strategy, acknowledged_gap_refs=[first])
    assert outcome.results[0].status is PricingStatus.HANDOFF_BLOCKED

    outcome = _run(strategy=strategy, acknowledged_gap_refs=[first, second])
    assert outcome.results[0].status is PricingStatus.PAYLOAD_READY


# -- gap_ref: prose is not an identifier ----------------------------------------

def test_the_gate_does_not_accept_the_wording_of_a_gap() -> None:
    """The text is display. Acknowledging by retyping the analysis's prose is not a decision."""
    outcome = _run(acknowledged_gap_refs=[BUDGET_GAP])
    assert not outcome.results
    assert PricingRejectionCode.UNKNOWN_GAP_REF in _codes(outcome.rejections)


def test_every_blocking_gap_has_a_reference() -> None:
    strategy = build_strategy()
    blocking = open_before_pricing(strategy)
    assert blocking
    for gap in blocking:
        assert gap.gap_ref.startswith("gap_")
        assert gap.need and gap.timing is EvidenceTiming.BEFORE_PRICING
        assert safe_identifier(gap.gap_ref), "a ref is an opaque token, like every other here"


def test_a_reference_does_not_carry_the_wording_it_refers_to() -> None:
    gap = open_before_pricing(build_strategy())[0]
    assert BUDGET_GAP not in gap.gap_ref
    for word in BUDGET_GAP.split():
        assert word not in gap.gap_ref


def test_the_same_gap_state_produces_the_same_reference() -> None:
    """Deterministic across calls and across processes - no counter, no clock, no uuid."""
    first = [gap.gap_ref for gap in gaps_for(build_strategy())]
    second = [gap.gap_ref for gap in gaps_for(build_strategy())]
    assert first == second
    assert len(set(first)) == len(first), "distinct gaps get distinct refs"


@pytest.mark.parametrize(
    "changed",
    [
        EvidenceNeed(need="연간 계측 예산 상한", timing=EvidenceTiming.BEFORE_PRICING,
                     dimension=D.BUDGET_EVIDENCE),
        EvidenceNeed(need=BUDGET_GAP, timing=EvidenceTiming.BEFORE_CONTRACT,
                     dimension=D.BUDGET_EVIDENCE),
        EvidenceNeed(need=BUDGET_GAP, timing=EvidenceTiming.BEFORE_PRICING,
                     dimension=D.PROCUREMENT_CONTEXT),
    ],
    ids=["reworded", "retimed", "re-attributed"],
)
def test_a_changed_gap_is_not_covered_by_the_old_acknowledgement(changed) -> None:
    """An approval is for a specific gap as it was worded when somebody read it."""
    stale = budget_gap_ref()
    strategy = build_strategy(gaps=[changed])

    outcome = _run(strategy=strategy, acknowledged_gap_refs=[stale])
    assert not outcome.results
    assert PricingRejectionCode.UNKNOWN_GAP_REF in _codes(outcome.rejections)


def test_whitespace_alone_does_not_change_a_reference() -> None:
    """Only whitespace is normalised. Case and wording are left exactly as written."""
    spaced = build_strategy(
        gaps=[
            EvidenceNeed(
                need="  " + BUDGET_GAP + "\n ",
                timing=EvidenceTiming.BEFORE_PRICING,
                dimension=D.BUDGET_EVIDENCE,
            )
        ]
    )
    assert all_blocking_refs(spaced) == [budget_gap_ref()]


def test_a_reference_does_not_carry_across_strategies() -> None:
    """Two clients can easily have a gap that reads identically. One approval is not both."""
    import dataclasses

    other = dataclasses.replace(build_strategy(), strategy_id="prp_other")
    assert all_blocking_refs(other) != all_blocking_refs(build_strategy())


def test_an_unknown_reference_is_refused_not_ignored() -> None:
    """A stale view means the approval the caller believes they gave is not the recorded one."""
    outcome = _run(acknowledged_gap_refs=[budget_gap_ref(), "gap_deadbeefdeadbeef"])
    assert not outcome.results
    rejections = [r for r in outcome.rejections if r.code == PricingRejectionCode.UNKNOWN_GAP_REF]
    assert rejections and rejections[0].reference == "1", "a count, not the ref"


def test_acknowledging_a_gap_that_was_never_blocking_is_flagged_not_refused() -> None:
    """Nothing was unlocked by it. The flag stops a reader thinking the gate honoured it."""
    strategy = build_strategy()
    optional = next(
        gap for gap in gaps_for(strategy) if gap.timing is EvidenceTiming.UNCLASSIFIED
    )
    outcome = _run(
        strategy=strategy, acknowledged_gap_refs=[budget_gap_ref(), optional.gap_ref]
    )
    assert outcome.results[0].status is PricingStatus.PAYLOAD_READY
    assert PricingFlagCode.NON_BLOCKING_GAP_ACKNOWLEDGED in _codes(outcome.review_flags)


def test_acknowledging_only_a_non_blocking_gap_does_not_open_the_gate() -> None:
    strategy = build_strategy()
    optional = next(
        gap for gap in gaps_for(strategy) if gap.timing is EvidenceTiming.OPTIONAL
    )
    outcome = _run(strategy=strategy, acknowledged_gap_refs=[optional.gap_ref])
    assert outcome.results[0].status is PricingStatus.HANDOFF_BLOCKED


def test_identical_gaps_recorded_twice_are_one_gap() -> None:
    need = EvidenceNeed(need=BUDGET_GAP, timing=EvidenceTiming.BEFORE_PRICING,
                        dimension=D.BUDGET_EVIDENCE)
    strategy = build_strategy(gaps=[need, need])
    assert len(all_blocking_refs(strategy)) == 1

    outcome = _run(strategy=strategy, acknowledged_gap_refs=all_blocking_refs(strategy))
    assert outcome.results[0].status is PricingStatus.PAYLOAD_READY


def test_the_display_text_survives_alongside_the_reference() -> None:
    gap = open_before_pricing(build_strategy())[0]
    assert gap.need == BUDGET_GAP, "the sentence a person reads is not replaced by the ref"
    assert gap.as_context() == {
        "gap_ref": gap.gap_ref,
        "need": BUDGET_GAP,
        "timing": "BEFORE_PRICING",
        "dimension": "BUDGET_EVIDENCE",
    }


def test_unclassified_and_optional_gaps_do_not_block() -> None:
    """A gap nobody timed is not an urgency, and one judged optional has been judged."""
    strategy = build_strategy(
        gaps=[
            EvidenceNeed(need="인증 요건", timing=EvidenceTiming.UNCLASSIFIED),
            EvidenceNeed(need="유지보수 조건", timing=EvidenceTiming.OPTIONAL),
            EvidenceNeed(need="접근 경로", timing=EvidenceTiming.BEFORE_PROPOSAL),
            EvidenceNeed(need="계약서 양식", timing=EvidenceTiming.BEFORE_CONTRACT),
        ]
    )
    outcome = _run(strategy=strategy)
    assert open_before_pricing(strategy) == []
    assert outcome.results[0].status is PricingStatus.PAYLOAD_READY
    assert PricingFlagCode.GAPS_ACKNOWLEDGED not in _codes(outcome.review_flags)


def test_a_blocked_case_still_counts_every_gap() -> None:
    counts = _run().results[0].commercial_context["open_gap_counts"]
    assert counts["BEFORE_PRICING"] == 1
    assert counts["UNCLASSIFIED"] == 1
    assert counts["OPTIONAL"] == 1
    assert counts["BEFORE_PROPOSAL"] == 1


# -- V: their rules stay theirs ---------------------------------------------------

def test_a_shared_direct_cost_is_flagged_and_left_alone() -> None:
    """``dependency_rules.md`` calls this an error. Their engine says so, not this one."""
    commercial = build_commercial(
        cost_items=[
            CostItemInput(
                item_id="sga",
                label="판관비",
                cost_category="fixed_operating_cost",
                basis="per_month",
                applies_to_component="shared",
                amount=SGA_AMOUNT,
                currency="KRW",
                allocation_rule="direct",
            )
        ]
    )
    outcome = _run(commercial=commercial)
    assert outcome.results, "not refused — we are not the authority on their engine's rules"
    assert PricingFlagCode.DEPENDENCY_RULE_RISK in _codes(outcome.review_flags)

    item = outcome.results[0].pricing_payload["costs"]["items"][0]
    assert item["applies_to_component"] == "shared"
    assert item["allocation_rule"] == "direct", "not corrected"
    assert item["amount"] == SGA_AMOUNT, "not dropped"


def test_an_amount_and_a_rate_on_one_item_is_flagged_not_corrected() -> None:
    commercial = build_commercial(
        cost_items=[
            CostItemInput(
                item_id="channel_fee",
                label="채널수수료",
                cost_category="variable_selling_delivery",
                basis="rate_of_gross_payment",
                applies_to_component="sensor",
                amount=SHIPPING_AMOUNT,
                rate=FEE_RATE,
                currency="KRW",
            )
        ]
    )
    outcome = _run(commercial=commercial)
    item = outcome.results[0].pricing_payload["costs"]["items"][0]
    assert item["amount"] == SHIPPING_AMOUNT and item["rate"] == FEE_RATE
    assert PricingFlagCode.DEPENDENCY_RULE_RISK in _codes(outcome.review_flags)


def test_a_pricing_model_that_disagrees_with_its_components_is_flagged() -> None:
    commercial = build_commercial(pricing_model="recurring")
    outcome = _run(commercial=commercial)
    assert outcome.results
    assert outcome.results[0].pricing_payload["product"]["pricing_model"] == "recurring"
    assert PricingFlagCode.DEPENDENCY_RULE_RISK in _codes(outcome.review_flags)


# -- W: provenance carries identifiers, never documents ---------------------------

@pytest.mark.parametrize(
    "unsafe",
    [
        "2026 가격표.xlsx",
        "clients/alpha/costs.json",
        "C:\\Users\\someone\\Desktop\\quote.pdf",
        "https://intranet.example/costs?token=abc123",
        "quote from 김민수",
    ],
)
def test_a_source_reference_that_is_not_an_identifier_is_refused(unsafe: str) -> None:
    """A filename carries the client, the project and often a person — privacy section 3."""
    commercial = build_commercial(
        pricing_model="one_time",
        price_components=[
            PriceComponentInput(
                solution_element_ref="S1",
                component_id="sensor",
                component_type="one_time",
                currency="KRW",
                actual_price=SENSOR_PRICE,
                source=CommercialSourceRef(source_ref=unsafe),
            )
        ],
        cost_items=[],
    )
    outcome = _run(commercial=commercial)
    assert not outcome.results
    assert PricingRejectionCode.UNSAFE_SOURCE_REF in _codes(outcome.rejections)


def test_the_same_rule_applies_to_source_type() -> None:
    commercial = build_commercial(
        cost_items=[
            CostItemInput(
                item_id="bom",
                label="자재원가",
                cost_category="product_service_direct_cost",
                basis="per_unit",
                applies_to_component="sensor",
                amount=BOM_AMOUNT,
                currency="KRW",
                source=CommercialSourceRef(source_type="from 원가표.xlsx"),
            )
        ]
    )
    outcome = _run(commercial=commercial)
    assert PricingRejectionCode.UNSAFE_SOURCE_REF in _codes(outcome.rejections)


def test_verification_status_is_derived_not_authored(payload) -> None:
    """The same judgement this harness already made, mapped — not a second copy of it."""
    components = {c["component_id"]: c for c in payload["product"]["price_components"]}
    assert components["sensor"]["evidence"]["verification_status"] == "confirmed"
    items = {i["item_id"]: i for i in payload["costs"]["items"]}
    assert items["bom"]["evidence"]["verification_status"] == "estimated"


def test_an_unsourced_figure_is_unverified() -> None:
    from core.pricing_bridge.contract import VERIFICATION_FOR_EVIDENCE_TYPE

    assert VERIFICATION_FOR_EVIDENCE_TYPE[EvidenceType.ASSUMPTION] == "unverified"
    assert VERIFICATION_FOR_EVIDENCE_TYPE[EvidenceType.MISSING_EVIDENCE] == "unverified"
    assert set(VERIFICATION_FOR_EVIDENCE_TYPE) == set(EvidenceType), "total mapping"


# -- X / Y: the answer has to be answering this case --------------------------------

def _engine_result(case_id: str, client_id: str) -> dict:
    return {
        "schema_version": "1.0",
        "source": {
            "client_id": client_id,
            "case_id": case_id,
            "client_input_ref": "handed-over.json",
            "engine_version": "0.4.2",
            "calculated_at": "2026-09-20T00:00:00+00:00",
        },
        "currency": {"reporting": "USD"},
        "mode_a": {"status": "OK"},
    }


def test_a_matching_engine_result_is_stored_verbatim() -> None:
    result = _run(acknowledged_gap_refs=[budget_gap_ref()]).results[0]
    document = _engine_result(result.pricing_case_id, result.client_id)

    attached, rejections = attach_engine_result(result, document)
    assert not rejections
    assert attached.status is PricingStatus.COMPLETED
    assert attached.engine_result == document, "not reshaped, not summarised"
    assert attached.engine_version == "0.4.2"


def test_an_engine_result_for_another_case_is_refused() -> None:
    result = _run(acknowledged_gap_refs=[budget_gap_ref()]).results[0]
    attached, rejections = attach_engine_result(
        result, _engine_result("pcs_someone_elses_case", result.client_id)
    )
    assert PricingRejectionCode.ENGINE_RESULT_MISMATCH in _codes(rejections)
    assert attached.status is PricingStatus.FAILED
    assert attached.engine_result is None, "a wrong answer is not filed under this case"


def test_an_engine_result_for_another_client_is_refused() -> None:
    result = _run(acknowledged_gap_refs=[budget_gap_ref()]).results[0]
    attached, rejections = attach_engine_result(
        result, _engine_result(result.pricing_case_id, "cli_someone_else")
    )
    assert PricingRejectionCode.ENGINE_RESULT_MISMATCH in _codes(rejections)
    assert attached.status is PricingStatus.FAILED


def test_an_engine_result_with_no_source_block_is_refused() -> None:
    result = _run(acknowledged_gap_refs=[budget_gap_ref()]).results[0]
    attached, rejections = attach_engine_result(result, {"mode_a": {"status": "OK"}})
    assert PricingRejectionCode.ENGINE_RESULT_MALFORMED in _codes(rejections)
    assert attached.status is PricingStatus.FAILED


def test_module_statuses_are_not_reinterpreted() -> None:
    """``INCOMPLETE`` is their word about their computation. It does not become our status."""
    result = _run(acknowledged_gap_refs=[budget_gap_ref()]).results[0]
    document = _engine_result(result.pricing_case_id, result.client_id)
    document["mode_a"] = {"status": "INCOMPLETE"}
    document["bep"] = {"status": "ERROR"}

    attached, _ = attach_engine_result(result, document)
    assert attached.status is PricingStatus.COMPLETED
    assert attached.engine_result["mode_a"]["status"] == "INCOMPLETE"


# -- identity between the phases -----------------------------------------------------

def test_a_strategy_that_does_not_read_this_analysis_is_refused() -> None:
    import dataclasses

    strategy = dataclasses.replace(build_strategy(), analysis_id="cla_other")
    outcome = _run(strategy=strategy)
    assert PricingRejectionCode.UNKNOWN_ANALYSIS in _codes(outcome.rejections)


def test_a_strategy_for_another_client_is_refused() -> None:
    import dataclasses

    analysis = dataclasses.replace(build_analysis(), client_id="cli_other")
    outcome = _run(analysis=analysis)
    assert PricingRejectionCode.CLIENT_MISMATCH in _codes(outcome.rejections)


def test_phase_seven_does_not_advance_the_strategy() -> None:
    """A later phase editing an earlier record makes the earlier record stop meaning what it says."""
    from core.models import ProposalStatus

    strategy = build_strategy()
    _run(strategy=strategy, acknowledged_gap_refs=[budget_gap_ref()])
    assert strategy.status is ProposalStatus.STRATEGY_DRAFTED
