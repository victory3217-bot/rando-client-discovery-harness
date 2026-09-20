# -*- coding: utf-8 -*-
"""The bridge to the separate pricing harness — and the place this harness stops.

``core/proposal`` decides what to propose. This package turns that decision, plus the cost and
price figures a person supplies, into the JSON document ``pricing-harness-public`` expects,
and records what that harness answers. **There is no pricing engine here and there will not
be one** (HARNESS.md section 8): no margin, no break-even, no target price, no willingness to
pay, no exchange rate, no forecast, no choice of which pricing mode to run.

Four properties define the package, and each is enforced rather than described.

* **No model.** Nothing in here imports :mod:`core.transmission`, takes an ``LLMProvider`` or
  reads a prompt. Every value is either a Phase 5/6 record or a number the caller typed, so a
  model is never in a position to change a price.
* **No arithmetic.** Each number is one caller field copied to one contract field. Anything
  computed would be a second pricing engine, unversioned and unvalidated.
* **``None`` is ``null``, not ``0``.** The external contract already distinguishes "not
  entered" from "a confirmed zero" and propagates the first as UNKNOWN. This harness's rule
  about not inventing numbers and that contract's rule about nulls are the same rule.
* **Only the payload crosses.** ``commercial_context`` is ours and stays in
  :class:`~core.models.PricingResult`. The external contract has no field for it, and
  extending somebody else's contract to carry our data model is how two repositories stop
  being able to version independently.

The two harnesses exchange JSON files rather than Python objects because both use a top-level
package named ``core``; nothing here imports the other repository (ARCHITECTURE.md section 6).
File I/O belongs to ``adapters/pricing/file.py`` — the core builds documents and never writes
one.
"""
from core.pricing_bridge.codes import (
    PRICING_FLAG_CODES,
    PRICING_REJECTION_CODES,
    STAGE,
    PricingFlagCode,
    PricingRejectionCode,
)
from core.pricing_bridge.context import (
    COMMERCIAL_TIMINGS,
    INTERNATIONAL_PRICING_DIMENSIONS,
    PRICING_DIMENSIONS,
    SUPPORTING_DIMENSIONS,
    build_commercial_context,
)
from core.pricing_bridge.gaps import (
    BLOCKING_TIMING,
    GateDecision,
    PricingGap,
    gap_ref_for,
    gaps_for,
    open_before_pricing,
    resolve_gate,
    unacknowledged,
)
from core.pricing_bridge.models import (
    CommercialInput,
    CommercialSourceRef,
    CostItemInput,
    PriceComponentInput,
    PricingOutcome,
)
from core.pricing_bridge.payload import (
    PayloadBuild,
    build_pricing_payload,
    safe_identifier,
    validate_payload_shape,
)
from core.pricing_bridge.pipeline import (
    attach_engine_result,
    persist,
    run_pricing_handoff,
)
from core.pricing_bridge.policy import DEFAULT_PRICING_POLICY, PricingBridgePolicy

__all__ = [
    "BLOCKING_TIMING",
    "COMMERCIAL_TIMINGS",
    "DEFAULT_PRICING_POLICY",
    "INTERNATIONAL_PRICING_DIMENSIONS",
    "PRICING_DIMENSIONS",
    "PRICING_FLAG_CODES",
    "PRICING_REJECTION_CODES",
    "STAGE",
    "SUPPORTING_DIMENSIONS",
    "CommercialInput",
    "CommercialSourceRef",
    "CostItemInput",
    "GateDecision",
    "PayloadBuild",
    "PriceComponentInput",
    "PricingBridgePolicy",
    "PricingFlagCode",
    "PricingGap",
    "PricingOutcome",
    "PricingRejectionCode",
    "attach_engine_result",
    "build_commercial_context",
    "build_pricing_payload",
    "gap_ref_for",
    "gaps_for",
    "open_before_pricing",
    "persist",
    "resolve_gate",
    "run_pricing_handoff",
    "safe_identifier",
    "unacknowledged",
    "validate_payload_shape",
]
