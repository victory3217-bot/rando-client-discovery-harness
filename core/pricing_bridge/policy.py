# -*- coding: utf-8 -*-
"""Limits for one pricing hand-off. Pure configuration, injected by the caller.

Caps only. There is deliberately no default VAT rate, no default currency, no default margin
target and no default exchange rate — every one of those is a number, and a number this
harness supplies is a number nobody entered. The external contract already has a value for
"not entered": ``null``.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PricingBridgePolicy:
    """Guards against a runaway cost sheet, not a shape.

    A proposal with forty price components is a data-entry accident rather than a product, and
    the failure is better caught before a payload is written than after another repository has
    tried to price it.
    """

    max_price_components: int = 20
    max_cost_items: int = 100


DEFAULT_PRICING_POLICY = PricingBridgePolicy()
