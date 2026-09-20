# -*- coding: utf-8 -*-
"""Assembling the external ``client_input`` document. Copying, never computing.

Three properties hold here and each one is tested directly.

**No arithmetic.** Every number in the payload is one field of :class:`CommercialInput` placed
at one field of the contract. There is no addition, no rate applied to an amount, no currency
conversion, no VAT backed out — every one of those is the pricing harness's job, and a bridge
that did any of them would be a second, unversioned pricing engine that nobody validates.

**``None`` becomes ``null``, never ``0``.** The other contract reads ``null`` as "not entered"
and ``0`` as "a confirmed zero", and propagates the first as UNKNOWN through every dependent
metric. Substituting a zero turns a question this harness is supposed to keep visible into a
computed answer.

**Nothing of ours is added to their objects.** Their ``price_component`` and top level are
closed, so ``solution_element_ref`` stays out of the payload and lives in the commercial
context instead. The one open object, ``meta``, gets two identifiers and nothing more.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from core.models import ProposalStrategy
from core.pricing_bridge import contract
from core.pricing_bridge.codes import STAGE, PricingFlagCode, PricingRejectionCode
from core.pricing_bridge.models import (
    CommercialInput,
    CommercialSourceRef,
    CostItemInput,
    PriceComponentInput,
)
from core.research.models import Rejection, ReviewFlag

#: What a provenance reference may look like. Our identifiers (``fnd_3f2a…``) pass; a
#: filename, a path, a URL and anything with a space or a dot in it do not. Deliberately an
#: allowlist: a denylist of dangerous shapes is a list somebody eventually gets wrong.
_OPAQUE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

#: ISO calendar date. A date is not an identifier and carries nothing about a document.
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class PayloadBuild:
    """The assembled payload, what was refused, and what a reader should look at."""

    payload: Optional[dict] = None
    rejections: list = field(default_factory=list)
    review_flags: list = field(default_factory=list)
    #: ``component_id`` → ``solution_element_ref``. Kept out of the payload, used by the
    #: commercial context, which is where the binding belongs.
    bindings: dict = field(default_factory=dict)

    @property
    def refused(self) -> bool:
        return self.payload is None


def safe_identifier(value: object) -> bool:
    """Whether a value may be written into a provenance field of the outgoing payload."""
    return isinstance(value, str) and bool(_OPAQUE_IDENTIFIER.match(value))


def _is_number(value: object) -> bool:
    """A real number. ``bool`` is excluded: ``True`` is an ``int`` and would serialise as one."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def build_pricing_payload(
    *,
    client_id: str,
    pricing_case_id: str,
    strategy: ProposalStrategy,
    commercial: CommercialInput,
) -> PayloadBuild:
    """Turn one strategy plus one caller cost sheet into an external ``client_input``.

    Refusal is whole rather than partial. A payload with one component quietly dropped prices
    less than the proposal offers, and it looks exactly like a payload that was always meant
    to price that much.
    """
    build = PayloadBuild()

    def reject(code: str, reference: str = "") -> None:
        build.rejections.append(Rejection(STAGE, code, reference))

    def flag(code: str, reference: str = "") -> None:
        build.review_flags.append(ReviewFlag(STAGE, code, reference))

    # -- identity and version ----------------------------------------------
    if not commercial.contract_version.strip():
        reject(PricingRejectionCode.MISSING_CONTRACT_VERSION)
    for label, value in (
        ("client_id", client_id),
        ("case_id", pricing_case_id),
        ("product.name", commercial.product_name),
        ("fx.base_currency", commercial.base_currency),
        ("fx.reporting_currency", commercial.reporting_currency),
    ):
        if not str(value).strip():
            reject(PricingRejectionCode.MISSING_CONTRACT_FIELD, label)

    if commercial.pricing_model not in contract.PRICING_MODELS:
        reject(PricingRejectionCode.UNKNOWN_CONTRACT_VALUE, "pricing_model")

    # -- the offer this case is allowed to price ---------------------------
    selected = {element.ref for element in strategy.selected_solution_elements}
    components = list(commercial.price_components)
    if not components:
        reject(PricingRejectionCode.NO_PRICE_COMPONENT)

    seen_ids: set[str] = set()
    for component in components:
        if component.solution_element_ref not in selected:
            reject(PricingRejectionCode.UNKNOWN_SOLUTION_ELEMENT, component.component_id)
        if component.component_id in seen_ids:
            reject(PricingRejectionCode.DUPLICATE_COMPONENT_ID, component.component_id)
        seen_ids.add(component.component_id)
        build.rejections.extend(_check_component(component))

    priced_refs = {c.solution_element_ref for c in components}
    for element in strategy.selected_solution_elements:
        if element.ref not in priced_refs:
            flag(PricingFlagCode.ELEMENT_NOT_PRICED, element.ref)

    # -- costs --------------------------------------------------------------
    seen_items: set[str] = set()
    for item in commercial.cost_items:
        if item.item_id in seen_items:
            reject(PricingRejectionCode.DUPLICATE_COST_ITEM_ID, item.item_id)
        seen_items.add(item.item_id)
        build.rejections.extend(_check_cost_item(item, seen_ids))
        build.review_flags.extend(_dependency_risks(item))

    # -- the caller's own scalars -------------------------------------------
    for label, value in (
        ("tax.vat_rate", commercial.vat_rate),
        ("fx.rate_base_per_reporting", commercial.rate_base_per_reporting),
        (
            "targets.target_contribution_margin_rate",
            commercial.target_contribution_margin_rate,
        ),
    ):
        if value is not None and not _is_number(value):
            reject(PricingRejectionCode.UNKNOWN_CONTRACT_VALUE, label)

    if build.rejections:
        return build

    types_present = tuple(c.component_type for c in components)
    if not contract.pricing_model_matches(commercial.pricing_model, types_present):
        flag(PricingFlagCode.DEPENDENCY_RULE_RISK, "pricing_model")

    # -- assembly. Field to field, in contract order ------------------------
    build.payload = {
        "schema_version": commercial.contract_version,
        "client_id": client_id,
        "case_id": pricing_case_id,
        "product": {
            "name": commercial.product_name,
            "pricing_model": commercial.pricing_model,
            "price_components": [_component(c) for c in components],
        },
        "tax": {"vat_rate": commercial.vat_rate},
        "fx": {
            "base_currency": commercial.base_currency,
            "reporting_currency": commercial.reporting_currency,
            "rate_base_per_reporting": commercial.rate_base_per_reporting,
        },
        "costs": {"items": [_cost_item(i) for i in commercial.cost_items]},
        "targets": {
            "target_contribution_margin_rate": commercial.target_contribution_margin_rate
        },
        "meta": {
            "strategy_id": strategy.strategy_id,
            "analysis_id": strategy.analysis_id,
        },
    }
    build.bindings = {c.component_id: c.solution_element_ref for c in components}

    shape_violations = validate_payload_shape(build.payload)
    if shape_violations:
        build.payload = None
        build.bindings = {}
        reject(PricingRejectionCode.PAYLOAD_INVALID, str(len(shape_violations)))

    return build


# ---------------------------------------------------------------------------
# per-object checks and mapping
# ---------------------------------------------------------------------------

def _check_component(component: PriceComponentInput) -> list[Rejection]:
    out: list[Rejection] = []
    cid = component.component_id
    if not cid.strip():
        out.append(
            Rejection(STAGE, PricingRejectionCode.MISSING_CONTRACT_FIELD, "component_id")
        )
    if component.component_type not in contract.COMPONENT_TYPES:
        out.append(Rejection(STAGE, PricingRejectionCode.UNKNOWN_CONTRACT_VALUE, cid))
    if not component.currency.strip():
        out.append(Rejection(STAGE, PricingRejectionCode.MISSING_CONTRACT_FIELD, cid))
    for value in (component.actual_price, component.discount_rate, component.target_market_price):
        if value is not None and not _is_number(value):
            out.append(Rejection(STAGE, PricingRejectionCode.UNKNOWN_CONTRACT_VALUE, cid))
    if component.price_includes_vat is not None and not isinstance(
        component.price_includes_vat, bool
    ):
        out.append(Rejection(STAGE, PricingRejectionCode.UNKNOWN_CONTRACT_VALUE, cid))
    out.extend(_check_source(component.source, cid))
    return out


def _check_cost_item(item: CostItemInput, component_ids: set[str]) -> list[Rejection]:
    out: list[Rejection] = []
    iid = item.item_id
    for label, value in (("item_id", iid), ("label", item.label)):
        if not str(value).strip():
            out.append(
                Rejection(STAGE, PricingRejectionCode.MISSING_CONTRACT_FIELD, label)
            )
    if item.cost_category not in contract.COST_CATEGORIES:
        out.append(Rejection(STAGE, PricingRejectionCode.UNKNOWN_CONTRACT_VALUE, iid))
    if item.basis not in contract.COST_BASES:
        out.append(Rejection(STAGE, PricingRejectionCode.UNKNOWN_CONTRACT_VALUE, iid))
    if item.allocation_rule is not None and item.allocation_rule not in contract.ALLOCATION_RULES:
        out.append(Rejection(STAGE, PricingRejectionCode.UNKNOWN_CONTRACT_VALUE, iid))
    if item.applies_to_component != contract.SHARED_COMPONENT and (
        item.applies_to_component not in component_ids
    ):
        out.append(
            Rejection(STAGE, PricingRejectionCode.COST_TARGETS_UNKNOWN_COMPONENT, iid)
        )
    for value in (item.amount, item.rate, item.frequency_per_year):
        if value is not None and not _is_number(value):
            out.append(Rejection(STAGE, PricingRejectionCode.UNKNOWN_CONTRACT_VALUE, iid))
    out.extend(_check_source(item.source, iid))
    return out


def _check_source(source: Optional[CommercialSourceRef], reference: str) -> list[Rejection]:
    """Provenance fields take opaque identifiers only — see ``docs/privacy.md`` section 3."""
    if source is None:
        return []
    out: list[Rejection] = []
    for value in (source.source_type, source.source_ref):
        if value is not None and not safe_identifier(value):
            out.append(Rejection(STAGE, PricingRejectionCode.UNSAFE_SOURCE_REF, reference))
    if source.as_of_date is not None and not _ISO_DATE.match(source.as_of_date):
        out.append(Rejection(STAGE, PricingRejectionCode.UNSAFE_SOURCE_REF, reference))
    return out


def _dependency_risks(item: CostItemInput) -> list[ReviewFlag]:
    """Conditions the other harness's ``dependency_rules.md`` calls errors.

    Reported and passed through. Correcting them here would mean this repository deciding what
    the pricing engine meant, and the two would then disagree about what was asked.
    """
    risks: list[ReviewFlag] = []
    if (
        item.applies_to_component == contract.SHARED_COMPONENT
        and item.allocation_rule == "direct"
    ):
        risks.append(ReviewFlag(STAGE, PricingFlagCode.DEPENDENCY_RULE_RISK, item.item_id))
    if item.amount is not None and item.rate is not None:
        risks.append(ReviewFlag(STAGE, PricingFlagCode.DEPENDENCY_RULE_RISK, item.item_id))
    return risks


def _component(component: PriceComponentInput) -> dict:
    """One ``price_component``. Required keys always, optional keys only when supplied."""
    out: dict[str, Any] = {
        "component_id": component.component_id,
        "type": component.component_type,
        "actual_price": component.actual_price,
        "currency": component.currency,
        "price_includes_vat": component.price_includes_vat,
    }
    if component.discount_rate is not None:
        out["discount_rate"] = component.discount_rate
    if component.target_market_price is not None:
        out["target_market_price"] = component.target_market_price
    evidence = _evidence(component.source)
    if evidence is not None:
        out["evidence"] = evidence
    return out


def _cost_item(item: CostItemInput) -> dict:
    out: dict[str, Any] = {
        "item_id": item.item_id,
        "label": item.label,
        "cost_category": item.cost_category,
        "amount": item.amount,
        "rate": item.rate,
        "currency": item.currency,
        "basis": item.basis,
        "applies_to_component": item.applies_to_component,
    }
    if item.allocation_rule is not None:
        out["allocation_rule"] = item.allocation_rule
    if item.frequency_per_year is not None:
        out["frequency_per_year"] = item.frequency_per_year
    evidence = _evidence(item.source)
    if evidence is not None:
        out["evidence"] = evidence
    return out


def _evidence(source: Optional[CommercialSourceRef]) -> Optional[dict]:
    if source is None:
        return None
    out: dict[str, Any] = {}
    if source.source_type is not None:
        out["source_type"] = source.source_type
    if source.source_ref is not None:
        out["source_ref"] = source.source_ref
    if source.as_of_date is not None:
        out["as_of_date"] = source.as_of_date
    out["verification_status"] = contract.VERIFICATION_FOR_EVIDENCE_TYPE[source.evidence_type]
    return out


# ---------------------------------------------------------------------------
# local strict validation
# ---------------------------------------------------------------------------

def validate_payload_shape(payload: dict) -> list[str]:
    """This repository's own check on what it built, before anything leaves.

    It is not a substitute for the real schema and does not claim to be — see
    :data:`~core.pricing_bridge.codes.PricingFlagCode.EXTERNAL_CONTRACT_NOT_CHECKED`. What it
    guarantees is that a change on this side cannot quietly start emitting an extra key, a
    missing required field, or a value outside a closed set, in an environment where the other
    repository is not checked out.
    """
    violations: list[str] = []

    violations.extend(
        _keys("payload", payload, contract.CLIENT_INPUT_REQUIRED, contract.CLIENT_INPUT_OPTIONAL)
    )
    if violations:
        return violations

    if not isinstance(payload["schema_version"], str) or not payload["schema_version"]:
        violations.append("payload.schema_version: must be a non-empty string")
    for key in ("client_id", "case_id"):
        if not isinstance(payload[key], str) or not payload[key]:
            violations.append(f"payload.{key}: must be a non-empty string")

    product = payload["product"]
    violations.extend(_keys("product", product, contract.PRODUCT_REQUIRED, ()))
    if not violations:
        if product["pricing_model"] not in contract.PRICING_MODELS:
            violations.append(
                f"product.pricing_model: {product['pricing_model']!r} is not one of "
                f"{list(contract.PRICING_MODELS)}"
            )
        components = product["price_components"]
        if not isinstance(components, list) or not components:
            violations.append("product.price_components: at least one component is required")
        else:
            for index, component in enumerate(components):
                violations.extend(_component_shape(index, component))

    violations.extend(_keys("tax", payload["tax"], contract.TAX_REQUIRED, ()))
    violations.extend(_number_or_null("tax.vat_rate", payload["tax"].get("vat_rate")))

    fx = payload["fx"]
    violations.extend(_keys("fx", fx, contract.FX_REQUIRED, ()))
    violations.extend(
        _number_or_null("fx.rate_base_per_reporting", fx.get("rate_base_per_reporting"))
    )

    costs = payload["costs"]
    violations.extend(_keys("costs", costs, contract.COSTS_REQUIRED, ()))
    if not violations and not isinstance(costs["items"], list):
        violations.append("costs.items: must be a list")
    elif not violations:
        for index, item in enumerate(costs["items"]):
            violations.extend(_cost_item_shape(index, item))

    if "targets" in payload:
        violations.extend(_keys("targets", payload["targets"], (), contract.TARGETS_OPTIONAL))
    if "meta" in payload:
        unknown = sorted(set(payload["meta"]) - set(contract.META_KEYS))
        if unknown:
            violations.append(f"meta: this bridge writes only {list(contract.META_KEYS)}: {unknown}")

    return violations


def _keys(
    where: str, node: object, required: Sequence[str], optional: Sequence[str]
) -> list[str]:
    if not isinstance(node, dict):
        return [f"{where}: must be an object"]
    violations = [f"{where}.{key}: required" for key in required if key not in node]
    unknown = sorted(set(node) - set(required) - set(optional))
    if unknown:
        violations.append(
            f"{where}: unknown key(s) {unknown} — the external contract is closed here"
        )
    return violations


def _number_or_null(where: str, value: object) -> list[str]:
    if value is None or _is_number(value):
        return []
    return [f"{where}: must be a number or null (null means UNKNOWN, never 0)"]


def _component_shape(index: int, component: object) -> list[str]:
    where = f"product.price_components[{index}]"
    violations = _keys(
        where, component, contract.PRICE_COMPONENT_REQUIRED, contract.PRICE_COMPONENT_OPTIONAL
    )
    if violations or not isinstance(component, dict):
        return violations
    if component["type"] not in contract.COMPONENT_TYPES:
        violations.append(f"{where}.type: {component['type']!r} is not a contract value")
    if not isinstance(component["currency"], str) or not component["currency"]:
        violations.append(f"{where}.currency: must be a non-empty string")
    violations.extend(_number_or_null(f"{where}.actual_price", component["actual_price"]))
    if component["price_includes_vat"] is not None and not isinstance(
        component["price_includes_vat"], bool
    ):
        violations.append(f"{where}.price_includes_vat: must be a boolean or null")
    for key in ("discount_rate", "target_market_price"):
        if key in component:
            violations.extend(_number_or_null(f"{where}.{key}", component[key]))
    if "evidence" in component:
        violations.extend(_evidence_shape(f"{where}.evidence", component["evidence"]))
    return violations


def _cost_item_shape(index: int, item: object) -> list[str]:
    where = f"costs.items[{index}]"
    violations = _keys(where, item, contract.COST_ITEM_REQUIRED, contract.COST_ITEM_OPTIONAL)
    if violations or not isinstance(item, dict):
        return violations
    if item["cost_category"] not in contract.COST_CATEGORIES:
        violations.append(f"{where}.cost_category: not a contract value")
    if item["basis"] not in contract.COST_BASES:
        violations.append(f"{where}.basis: not a contract value")
    if item.get("allocation_rule") is not None and (
        item["allocation_rule"] not in contract.ALLOCATION_RULES
    ):
        violations.append(f"{where}.allocation_rule: not a contract value")
    violations.extend(_number_or_null(f"{where}.amount", item["amount"]))
    violations.extend(_number_or_null(f"{where}.rate", item["rate"]))
    if item["currency"] is not None and not isinstance(item["currency"], str):
        violations.append(f"{where}.currency: must be a string or null")
    if "frequency_per_year" in item:
        violations.extend(
            _number_or_null(f"{where}.frequency_per_year", item["frequency_per_year"])
        )
    if "evidence" in item:
        violations.extend(_evidence_shape(f"{where}.evidence", item["evidence"]))
    return violations


def _evidence_shape(where: str, evidence: object) -> list[str]:
    violations = _keys(where, evidence, (), contract.EVIDENCE_OPTIONAL)
    if violations or not isinstance(evidence, dict):
        return violations
    status = evidence.get("verification_status")
    if status is not None and status not in contract.VERIFICATION_STATUSES:
        violations.append(f"{where}.verification_status: not a contract value")
    for key in ("source_type", "source_ref"):
        if key in evidence and not safe_identifier(evidence[key]):
            violations.append(
                f"{where}.{key}: must be an opaque identifier — no filename, path or URL "
                "leaves this harness (docs/privacy.md section 3)"
            )
    if "as_of_date" in evidence and not _ISO_DATE.match(str(evidence["as_of_date"])):
        violations.append(f"{where}.as_of_date: must be YYYY-MM-DD")
    return violations
