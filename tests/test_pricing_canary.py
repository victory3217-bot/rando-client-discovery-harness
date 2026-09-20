# -*- coding: utf-8 -*-
"""Nothing about a client's cost structure escapes through a diagnostic — or out of the payload.

Phase 7 handles the most commercially dangerous data in the harness. A cost sheet is what a
competitor would pay for and what a customer must never see, and unlike every earlier phase
this one writes a file that deliberately leaves the process.

Two kinds of check.

Six surfaces, as in the intake, analysis and proposal canaries: ``repr``, exception,
rejection record, traceback, storage and the operator-visible summary.

And the export surface, which is new here. The payload travels, so it is scanned directly:
no filename, no path, no URL, no claim prose, and no place to put a person.
"""
from __future__ import annotations

import json
import re
import traceback
from pathlib import Path

import pytest

from adapters.pricing.file import FilePricingBridge
from adapters.storage.memory import MemoryStorage
from core.models import AnalysisDimension, PricingResult, as_dict
from core.pricing_bridge import (
    CommercialInput,
    CommercialSourceRef,
    CostItemInput,
    PriceComponentInput,
    PricingOutcome,
    persist,
    run_pricing_handoff,
)
from pricing_fixtures import (
    SENSOR_PRICE,
    budget_gap_ref,
    build_analysis,
    build_commercial,
    build_strategy,
)

CANARY = "ZZCANARYZZ"
D = AnalysisDimension

#: Anything that looks like a document rather than an identifier.
_DOCUMENT_SHAPED = re.compile(
    r"\.(pdf|docx?|pptx?|xlsx?|csv|html?|txt|json|zip)\b|[/\\]|https?://", re.IGNORECASE
)


def _case(**overrides):
    kwargs = dict(
        analysis=build_analysis(),
        strategy=build_strategy(),
        commercial=build_commercial(),
        acknowledged_gap_refs=[budget_gap_ref()],
    )
    kwargs.update(overrides)
    return run_pricing_handoff(**kwargs)


# -- the export surface ----------------------------------------------------------

def test_the_payload_contains_nothing_document_shaped() -> None:
    """The one artefact that leaves the process, scanned for what must not be in it."""
    payload = _case().results[0].pricing_payload
    serialised = json.dumps(payload, ensure_ascii=False)
    found = _DOCUMENT_SHAPED.findall(serialised)
    assert not found, f"the outgoing payload looks like it names a document: {found}"


def test_the_payload_carries_no_claim_prose() -> None:
    """Phase 5 statements explain the case. They do not travel with the numbers."""
    analysis = build_analysis(
        statements={D.BUDGET_EVIDENCE: f"조달 담당자 {CANARY} 가 예산을 승인한다"}
    )
    result = _case(analysis=analysis).results[0]

    assert CANARY not in json.dumps(result.pricing_payload, ensure_ascii=False)
    assert CANARY in json.dumps(result.commercial_context, ensure_ascii=False), (
        "it is kept on our side, where it explains the case"
    )


def test_there_is_no_field_for_a_person_anywhere_in_the_phase() -> None:
    import dataclasses

    banned = ("contact", "email", "phone", "person", "name_of", "buyer_name")
    for cls in (CommercialInput, PriceComponentInput, CostItemInput, CommercialSourceRef,
                PricingResult):
        names = {f.name for f in dataclasses.fields(cls)}
        for field_name in names:
            assert not any(b in field_name for b in banned), f"{cls.__name__}.{field_name}"


def test_the_written_file_is_the_payload_and_only_the_payload(tmp_path: Path) -> None:
    result = _case().results[0]
    path = FilePricingBridge().write_payload(result, tmp_path)
    written = json.loads(path.read_text(encoding="utf-8"))

    assert written == result.pricing_payload
    assert "commercial_context" not in written
    assert not _DOCUMENT_SHAPED.search(json.dumps(written, ensure_ascii=False))


# -- surface 1: repr ---------------------------------------------------------------

def test_an_outcome_repr_shows_no_figures() -> None:
    outcome = _case()
    text = repr(outcome.rejections) + repr(outcome.review_flags)
    assert str(SENSOR_PRICE) not in text


def test_a_validation_verdict_repr_carries_counts_only() -> None:
    from adapters.pricing.file import ExternalValidation

    verdict = ExternalValidation(checked=True, errors=["price: 1230007 is wrong"])
    assert "1230007" not in repr(verdict)
    assert "errors=1" in repr(verdict)


# -- surface 2/3: exceptions and rejection records -----------------------------------

def test_a_rejection_records_a_code_not_a_number() -> None:
    """A diagnostic names the thing that was wrong, never the value that was in it."""
    commercial = build_commercial(
        price_components=[
            PriceComponentInput(
                solution_element_ref="S9",
                component_id="training",
                component_type="one_time",
                currency="KRW",
                actual_price=SENSOR_PRICE,
            )
        ]
    )
    outcome = _case(commercial=commercial)
    identifiers = {"", "price_components", "cost_items"}
    identifiers |= {c.component_id for c in commercial.price_components}
    identifiers |= {i.item_id for i in commercial.cost_items}

    assert outcome.rejections
    for rejection in outcome.rejections:
        assert str(SENSOR_PRICE) not in repr(rejection)
        assert rejection.reference in identifiers, rejection


def test_an_unsafe_source_reference_is_not_echoed_back() -> None:
    """Refusing a filename must not put the filename in the refusal."""
    outcome = _case(
        commercial=build_commercial(
            cost_items=[
                CostItemInput(
                    item_id="bom",
                    label="자재원가",
                    cost_category="product_service_direct_cost",
                    basis="per_unit",
                    applies_to_component="sensor",
                    amount=1,
                    currency="KRW",
                    source=CommercialSourceRef(source_ref=f"{CANARY}_가격표.xlsx"),
                )
            ]
        )
    )
    text = repr(outcome.rejections)
    assert CANARY not in text and ".xlsx" not in text


def test_a_blocked_handoff_error_names_a_status_not_a_case(tmp_path: Path) -> None:
    from core.errors import PricingHandoffBlocked

    blocked = run_pricing_handoff(
        analysis=build_analysis(), strategy=build_strategy(), commercial=build_commercial()
    ).results[0]

    with pytest.raises(PricingHandoffBlocked) as raised:
        FilePricingBridge().write_payload(blocked, tmp_path)

    message = str(raised.value)
    assert "HANDOFF_BLOCKED" in message
    assert blocked.client_id not in message
    assert str(SENSOR_PRICE) not in message


# -- surface 4: traceback ------------------------------------------------------------

def test_a_traceback_through_the_bridge_carries_no_cost_data(tmp_path: Path) -> None:
    from core.errors import PricingHandoffBlocked

    blocked = run_pricing_handoff(
        analysis=build_analysis(), strategy=build_strategy(), commercial=build_commercial()
    ).results[0]
    try:
        FilePricingBridge().write_payload(blocked, tmp_path)
    except PricingHandoffBlocked:
        text = traceback.format_exc()
    for figure in (str(SENSOR_PRICE), "431009", "0.029"):
        assert figure not in text


# -- surface 5: storage ----------------------------------------------------------------

def test_storage_never_receives_the_caller_input_object() -> None:
    """``CommercialInput`` is transient. A second copy of the figures is a second SSOT."""
    storage = MemoryStorage()
    assert not any("commercial" in name.lower() for name in dir(storage) if name.startswith("save"))

    outcome = _case()
    persist(outcome, storage)
    stored = as_dict(storage.get_pricing_results(outcome.results[0].project_id)[0])
    assert set(stored) == {f.name for f in __import__("dataclasses").fields(PricingResult)}


def test_the_stored_record_holds_no_document_reference() -> None:
    outcome = _case()
    serialised = json.dumps(as_dict(outcome.results[0]), ensure_ascii=False)
    assert not _DOCUMENT_SHAPED.search(serialised)


# -- surface 6: the operator-visible summary ---------------------------------------------

def test_a_run_can_be_summarised_in_counts_alone() -> None:
    outcome = _case(
        commercial=build_commercial(
            price_components=[
                PriceComponentInput(
                    solution_element_ref="S1",
                    component_id="sensor",
                    component_type="one_time",
                    currency="KRW",
                    actual_price=SENSOR_PRICE,
                )
            ],
            pricing_model="one_time",
            cost_items=[],
        )
    )
    summary = {
        "results": len(outcome.results),
        "rejections": sorted({r.code for r in outcome.rejections}),
        "flags": sorted({f.code for f in outcome.review_flags}),
    }
    text = json.dumps(summary, ensure_ascii=False)
    assert str(SENSOR_PRICE) not in text
    assert summary["flags"] == ["ELEMENT_NOT_PRICED", "GAPS_ACKNOWLEDGED"]


def test_an_empty_outcome_is_still_a_valid_summary() -> None:
    outcome = PricingOutcome()
    assert outcome.results == [] and outcome.rejections == [] and outcome.review_flags == []
