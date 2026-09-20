# -*- coding: utf-8 -*-
"""The external pricing contract, named — and nothing else.

Every field name and closed value set this bridge has to satisfy lives in this one module, so
that the surface that can drift when ``pricing-harness-public`` changes its
``client_input.schema.json`` is a single file to review rather than four.

**This is not a copy of that schema.** Copying it would create a second, silently stale
authority: the same failure the ``PricingResult`` schema avoids by saying it "does not restate
a contract it does not own". What is here is the minimum needed to *build* a document in that
shape and to check our own output before it leaves — names, closed enums, which keys are
required. The authoritative check is the real schema, run by
``adapters/pricing/file.py`` when a path to it has been supplied.

Nothing in this module is imported from the other repository. Both repositories use a
top-level package called ``core``, so importing their Python in this process would collide;
that is the whole reason the two exchange JSON files (ARCHITECTURE.md section 6).
"""
from __future__ import annotations

from core.models import EvidenceType

#: Their ``client_input`` top level. Closed there (``additionalProperties: false``), so an
#: extra key of ours is a hard validation failure, not a tolerated annotation.
CLIENT_INPUT_REQUIRED: tuple[str, ...] = (
    "schema_version",
    "client_id",
    "case_id",
    "product",
    "tax",
    "fx",
    "costs",
)
CLIENT_INPUT_OPTIONAL: tuple[str, ...] = ("targets", "meta")

PRODUCT_REQUIRED: tuple[str, ...] = ("name", "pricing_model", "price_components")

PRICE_COMPONENT_REQUIRED: tuple[str, ...] = (
    "component_id",
    "type",
    "actual_price",
    "currency",
    "price_includes_vat",
)
#: ``discount_schedule`` is theirs and we never write one: a schedule is a pricing policy, and
#: this harness does not hold one.
PRICE_COMPONENT_OPTIONAL: tuple[str, ...] = (
    "discount_rate",
    "target_market_price",
    "evidence",
)

TAX_REQUIRED: tuple[str, ...] = ("vat_rate",)

FX_REQUIRED: tuple[str, ...] = (
    "base_currency",
    "reporting_currency",
    "rate_base_per_reporting",
)

COSTS_REQUIRED: tuple[str, ...] = ("items",)

COST_ITEM_REQUIRED: tuple[str, ...] = (
    "item_id",
    "label",
    "cost_category",
    "amount",
    "rate",
    "currency",
    "basis",
    "applies_to_component",
)
COST_ITEM_OPTIONAL: tuple[str, ...] = ("allocation_rule", "frequency_per_year", "evidence")

TARGETS_OPTIONAL: tuple[str, ...] = ("target_contribution_margin_rate",)

EVIDENCE_OPTIONAL: tuple[str, ...] = (
    "source_type",
    "source_ref",
    "as_of_date",
    "verification_status",
)

#: Their ``meta`` is the one open object in the contract. We put two identifiers in it and
#: nothing else — enough to rejoin a payload found on its own to the record it came from.
#: The commercial context does **not** go here: see ``core/pricing_bridge/context.py``.
META_KEYS: tuple[str, ...] = ("strategy_id", "analysis_id")

# -- closed value sets ------------------------------------------------------

PRICING_MODELS: tuple[str, ...] = ("one_time", "recurring", "hybrid")

COMPONENT_TYPES: tuple[str, ...] = (
    "one_time",
    "recurring_monthly",
    "recurring_annual",
    "usage_based",
)

COST_CATEGORIES: tuple[str, ...] = (
    "product_service_direct_cost",
    "variable_selling_delivery",
    "fixed_operating_cost",
)

COST_BASES: tuple[str, ...] = (
    "per_unit",
    "per_order",
    "per_month",
    "per_unit_per_month",
    "per_visit",
    "rate_of_gross_payment",
    "rate_of_net_sales",
)

ALLOCATION_RULES: tuple[str, ...] = (
    "direct",
    "by_component_revenue",
    "fixed_share",
    "blended_only",
)

VERIFICATION_STATUSES: tuple[str, ...] = ("confirmed", "estimated", "unverified")

#: The literal their ``applies_to_component`` accepts instead of a component id.
SHARED_COMPONENT = "shared"

#: Which component types are one-time and which recur, used only to notice a ``pricing_model``
#: that disagrees with the components under it. Their schema states the consistency rule in
#: prose and cannot enforce it; we flag, we do not correct.
RECURRING_TYPES: frozenset[str] = frozenset(
    {"recurring_monthly", "recurring_annual", "usage_based"}
)

#: ``evidence_type`` to their ``verification_status``. Deterministic and total.
#:
#: An inference is ``estimated`` rather than ``confirmed`` because that is exactly what it is:
#: a reading of documents that were not written about this number. ``MISSING_EVIDENCE`` has no
#: statement behind it at all, so it lands in the same place as an assumption.
VERIFICATION_FOR_EVIDENCE_TYPE: dict[EvidenceType, str] = {
    EvidenceType.FACT: "confirmed",
    EvidenceType.INFERENCE: "estimated",
    EvidenceType.ASSUMPTION: "unverified",
    EvidenceType.MISSING_EVIDENCE: "unverified",
}


def pricing_model_matches(pricing_model: str, component_types: tuple[str, ...]) -> bool:
    """Whether the declared model agrees with the component types actually present.

    Their schema says these "must be consistent" and then cannot check it, because JSON Schema
    has no way to express the relationship. We read the rule the obvious way and report
    disagreement as a flag — the pricing harness remains the authority on its own rules.
    """
    if not component_types:
        return True
    recurring = any(t in RECURRING_TYPES for t in component_types)
    one_time = any(t == "one_time" for t in component_types)
    if pricing_model == "hybrid":
        return recurring and one_time
    if pricing_model == "recurring":
        return recurring and not one_time
    if pricing_model == "one_time":
        return one_time and not recurring
    return False
