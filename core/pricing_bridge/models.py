# -*- coding: utf-8 -*-
"""Transient objects for one pricing hand-off.

Nothing here is persisted and nothing here gets a schema in ``schemas/``. The entity this
phase produces is :class:`~core.models.PricingResult`, and the numbers that were actually used
are preserved inside its ``pricing_payload``. Storing :class:`CommercialInput` as well would
put the same figures in two places with nothing to say which one a later reader should trust —
the drift ``ProposalStrategy.pricing_input`` was removed to avoid.

:class:`CommercialInput` is the whole of this phase's numeric surface, and it is the caller's.
It plays the part :class:`~core.proposal.models.SolutionElement` plays in Phase 6: there is no
field anywhere in this package for a number that was derived, estimated or read off a claim,
so a price cannot enter the payload except by having been typed by a person.

``None`` means UNKNOWN throughout, and reaches the payload as ``null``. The pricing harness
distinguishes ``null`` (not entered) from ``0`` (a confirmed zero) and propagates the first as
UNKNOWN through every metric that depends on it; filling a blank with ``0`` here would turn a
question into a computed answer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from core.models import EvidenceType


@dataclass(frozen=True)
class CommercialSourceRef:
    """Where one figure came from, in identifiers only.

    The external contract documents ``source_ref`` as "File name, URL, or citation". A
    filename is on this repository's permanent-storage prohibition list (``docs/privacy.md``
    section 3) because it carries the client's name, the project code and often a person's
    name; a URL can carry a token. So this type accepts opaque identifiers and nothing else,
    and :func:`core.pricing_bridge.payload.safe_identifier` refuses anything with a dot, a
    separator or a space in it.

    ``verification_status`` is not settable. It is derived from ``evidence_type`` through a
    total mapping, because it is the same judgement this harness has already made and a second
    copy of a judgement is a second thing that can disagree.
    """

    #: A short opaque category — ``finding``, ``quote``, ``invoice``. Never a filename.
    source_type: Optional[str] = None
    #: One of our own identifiers: a ``fnd_…`` finding id or a ``src_…`` source id.
    source_ref: Optional[str] = None
    #: ISO ``YYYY-MM-DD``.
    as_of_date: Optional[str] = None
    #: Drives ``verification_status``. Defaults to the honest answer for a number somebody
    #: typed without saying where it came from.
    evidence_type: EvidenceType = EvidenceType.ASSUMPTION


@dataclass(frozen=True)
class PriceComponentInput:
    """One priceable piece of what is being proposed, as the caller stated it.

    ``solution_element_ref`` is the join to Phase 6: it has to be one of the refs on
    ``ProposalStrategy.selected_solution_elements``, which is what stops a price appearing for
    something the strategy never offered. It is **not** carried into the payload — the external
    ``price_component`` object is closed, and extending another repository's contract with a
    field of ours is not ours to do. The binding is kept in ``commercial_context``.
    """

    solution_element_ref: str
    component_id: str
    component_type: str
    currency: str
    actual_price: Optional[float] = None
    price_includes_vat: Optional[bool] = None
    discount_rate: Optional[float] = None
    target_market_price: Optional[float] = None
    source: Optional[CommercialSourceRef] = None


@dataclass(frozen=True)
class CostItemInput:
    """One cost line, as the caller stated it.

    Costs are ours, not the client's: ``core/analysis/dimensions.py`` keeps cost, margin and
    channel cost out of the per-client analysis for exactly this reason. Nothing in Phase 5 or
    Phase 6 can supply a value here.
    """

    item_id: str
    label: str
    cost_category: str
    basis: str
    applies_to_component: str
    amount: Optional[float] = None
    rate: Optional[float] = None
    currency: Optional[str] = None
    allocation_rule: Optional[str] = None
    frequency_per_year: Optional[float] = None
    source: Optional[CommercialSourceRef] = None


@dataclass(frozen=True)
class CommercialInput:
    """Everything the caller supplies for one pricing case. The only numeric input there is.

    ``contract_version`` is the external contract's ``schema_version`` and has **no default**.
    This repository's own ``SCHEMA_VERSION`` describes our entities and means nothing on the
    other side of the boundary; a default here would let ours be sent by accident and be
    validated against the wrong version of a contract we do not own.
    """

    contract_version: str
    product_name: str
    pricing_model: str
    base_currency: str
    reporting_currency: str
    price_components: Sequence[PriceComponentInput] = ()
    cost_items: Sequence[CostItemInput] = ()
    vat_rate: Optional[float] = None
    rate_base_per_reporting: Optional[float] = None
    target_contribution_margin_rate: Optional[float] = None
    #: Sales context, not a payload field. There is no quantity in the external contract.
    expected_quantity: Optional[float] = None
    #: Payment terms, warranty, delivery — the caller's words, kept in commercial_context.
    commercial_conditions: Sequence[str] = ()


@dataclass
class PricingOutcome:
    """Everything one hand-off run produced, including what it refused.

    There is no ``transmissions`` list, and its absence is the point: Phase 7 makes no external
    model call. Every value in the result was either decided in Phase 5/6 or typed by the
    caller, and a model asked to map a price is a model given the chance to change one.
    """

    results: list = field(default_factory=list)
    rejections: list = field(default_factory=list)
    review_flags: list = field(default_factory=list)
