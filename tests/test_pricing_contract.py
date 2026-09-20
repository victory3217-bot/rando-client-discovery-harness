# -*- coding: utf-8 -*-
"""The payload has to be a document the other repository accepts — and we have to say so honestly.

Two layers, and the difference between them is the point of this file.

The **local** layer is this repository's own strict check on what it builds: required fields,
closed value sets, and above all no extra keys, because the external contract's top level and
its ``price_component`` are closed and one stray key of ours fails the whole document.

The **external** layer is the real ``client_input.schema.json``, read from a checkout of
``pricing-harness-public`` when one is available. Reading a schema *file* is not importing
that repository's Python, so the ``core`` package-name collision that rules out an in-process
integration does not arise here (ARCHITECTURE.md section 6).

When the sibling repository is absent the external layer does not run, and the last test in
this file exists to make sure that fact is never dressed up as a pass.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.models import SCHEMA_VERSION
from core.pricing_bridge import (
    PricingFlagCode,
    PricingRejectionCode,
    build_pricing_payload,
    contract,
    run_pricing_handoff,
    validate_payload_shape,
)
from pricing_fixtures import (
    CLIENT,
    STRATEGY,
    build_analysis,
    build_commercial,
    build_strategy,
)

PRICING_HARNESS = Path(__file__).resolve().parent.parent.parent / "pricing-harness-public"
CLIENT_INPUT_SCHEMA = PRICING_HARNESS / "core" / "schemas" / "client_input.schema.json"


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


# -- M: the local contract -----------------------------------------------------

def test_payload_matches_the_local_strict_contract(payload) -> None:
    assert validate_payload_shape(payload) == []


def test_top_level_is_exactly_the_contract(payload) -> None:
    """Their top level is closed, so an extra key of ours fails the whole document."""
    assert set(contract.CLIENT_INPUT_REQUIRED) <= set(payload)
    allowed = set(contract.CLIENT_INPUT_REQUIRED) | set(contract.CLIENT_INPUT_OPTIONAL)
    assert set(payload) <= allowed


def test_an_unknown_key_is_caught_locally(payload) -> None:
    payload["our_own_annotation"] = "x"
    violations = validate_payload_shape(payload)
    assert any("unknown key" in v for v in violations)


def test_a_value_outside_a_closed_set_is_caught_locally(payload) -> None:
    payload["product"]["price_components"][0]["type"] = "quarterly"
    assert any("type" in v for v in validate_payload_shape(payload))


def test_a_missing_required_field_is_caught_locally(payload) -> None:
    del payload["product"]["price_components"][0]["price_includes_vat"]
    assert any("price_includes_vat" in v for v in validate_payload_shape(payload))


# -- L / P: what does not go into the payload ----------------------------------

def test_the_payload_carries_no_solution_element_ref(payload) -> None:
    """Their ``price_component`` is closed. Extending it is not ours to do."""
    serialised = json.dumps(payload, ensure_ascii=False)
    assert "solution_element_ref" not in serialised
    for component in payload["product"]["price_components"]:
        assert set(component) <= (
            set(contract.PRICE_COMPONENT_REQUIRED) | set(contract.PRICE_COMPONENT_OPTIONAL)
        )


def test_the_commercial_context_is_not_in_the_payload() -> None:
    """It is ours. The pricing engine has no field for it and is not given one."""
    outcome = run_pricing_handoff(
        analysis=build_analysis(),
        strategy=build_strategy(),
        commercial=build_commercial(),
        acknowledged_gap_refs=[],
    )
    result = outcome.results[0]
    assert result.commercial_context, "the context exists"
    assert "commercial_context" not in json.dumps(result.pricing_payload, ensure_ascii=False)
    assert set(result.pricing_payload["meta"]) == set(contract.META_KEYS)


def test_meta_carries_only_the_two_identifiers(payload) -> None:
    """Enough to rejoin a payload found on its own. Not a place to park a data model."""
    assert payload["meta"] == {"strategy_id": STRATEGY, "analysis_id": "cla_pricing_1"}


# -- D / E: whose version is it ------------------------------------------------

def test_contract_version_is_required() -> None:
    build = build_pricing_payload(
        client_id=CLIENT,
        pricing_case_id="pcs_1",
        strategy=build_strategy(),
        commercial=build_commercial(contract_version=""),
    )
    assert build.refused
    assert any(
        r.code == PricingRejectionCode.MISSING_CONTRACT_VERSION for r in build.rejections
    )


def test_our_schema_version_is_never_substituted(payload) -> None:
    """``schema_version`` belongs to the other contract. Ours describes our entities."""
    assert payload["schema_version"] == "1.1"
    assert payload["schema_version"] != SCHEMA_VERSION


def test_the_contract_version_travels_verbatim() -> None:
    build = build_pricing_payload(
        client_id=CLIENT,
        pricing_case_id="pcs_1",
        strategy=build_strategy(),
        commercial=build_commercial(contract_version="2.0-rc1"),
    )
    assert build.payload["schema_version"] == "2.0-rc1"


# -- determinism ----------------------------------------------------------------

def test_the_same_inputs_produce_the_same_bytes() -> None:
    """No model, no clock, no ordering by set iteration."""
    args = dict(
        client_id=CLIENT, pricing_case_id="pcs_same", strategy=build_strategy()
    )
    first = build_pricing_payload(commercial=build_commercial(), **args).payload
    second = build_pricing_payload(commercial=build_commercial(), **args).payload
    assert json.dumps(first, sort_keys=False) == json.dumps(second, sort_keys=False)


# -- N / O: the real contract ---------------------------------------------------

@pytest.mark.skipif(
    not CLIENT_INPUT_SCHEMA.is_file(),
    reason="pricing-harness-public is not checked out next to this repository",
)
def test_payload_validates_against_the_real_pricing_harness_schema(payload) -> None:
    """The Phase 7 completion criterion, run against the schema that actually owns it."""
    from jsonschema import Draft7Validator

    with CLIENT_INPUT_SCHEMA.open(encoding="utf-8") as fh:
        schema = json.load(fh)

    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda e: list(e.path))
    assert not errors, [f"{list(e.path)}: {e.message}" for e in errors]


@pytest.mark.skipif(
    not CLIENT_INPUT_SCHEMA.is_file(),
    reason="pricing-harness-public is not checked out next to this repository",
)
def test_the_adapter_reports_a_real_check_as_checked(payload) -> None:
    from adapters.pricing.file import FilePricingBridge

    bridge = FilePricingBridge.from_repository(PRICING_HARNESS)
    assert bridge.external_schema_available
    verdict = bridge.validate_external_payload(payload)
    assert verdict.checked and verdict.ok and verdict.code == ""


def test_an_unchecked_payload_is_not_reported_as_a_valid_one(payload) -> None:
    """"We did not look" and "we looked and it was fine" are different facts.

    This is the test that has to hold in every environment, including one where the sibling
    repository is absent — which is exactly where the mistake would otherwise be invisible.
    """
    from adapters.pricing.file import FilePricingBridge

    bridge = FilePricingBridge()
    assert not bridge.external_schema_available

    verdict = bridge.validate_external_payload(payload)
    assert verdict.checked is False
    assert verdict.ok is False, "an unchecked document must not read as an accepted one"
    assert verdict.code == PricingFlagCode.EXTERNAL_CONTRACT_NOT_CHECKED
    assert verdict.errors == [], "no errors were found because nothing was looked at"


def test_a_missing_repository_path_does_not_disable_the_local_check(payload) -> None:
    from adapters.pricing.file import FilePricingBridge

    bridge = FilePricingBridge(schema_root="/nonexistent/pricing-harness")
    assert not bridge.external_schema_available
    assert validate_payload_shape(payload) == [], "the local contract still applies"


# -- the published example ------------------------------------------------------

def test_the_published_example_payload_matches_the_local_contract(repo_root) -> None:
    """An example that teaches the wrong shape is worse than no example."""
    path = repo_root / "examples" / "sample_project" / "pricing_result.json"
    with path.open(encoding="utf-8") as fh:
        record = json.load(fh)
    assert validate_payload_shape(record["pricing_payload"]) == []
    assert "commercial_context" not in record["pricing_payload"]
    assert record["pricing_payload"]["case_id"] == record["pricing_case_id"]
    assert record["pricing_payload"]["case_id"] != record["strategy_id"]


@pytest.mark.skipif(
    not CLIENT_INPUT_SCHEMA.is_file(),
    reason="pricing-harness-public is not checked out next to this repository",
)
def test_the_published_example_payload_validates_against_the_real_schema(repo_root) -> None:
    from jsonschema import Draft7Validator

    with (repo_root / "examples" / "sample_project" / "pricing_result.json").open(
        encoding="utf-8"
    ) as fh:
        record = json.load(fh)
    with CLIENT_INPUT_SCHEMA.open(encoding="utf-8") as fh:
        schema = json.load(fh)

    errors = sorted(
        Draft7Validator(schema).iter_errors(record["pricing_payload"]),
        key=lambda e: list(e.path),
    )
    assert not errors, [f"{list(e.path)}: {e.message}" for e in errors]
