# -*- coding: utf-8 -*-
"""The commercial context — ours, and it stays here.

**It is not sent to the pricing harness.** That contract has no field for it, its top level is
closed, and its ``meta`` is a traceability slot rather than a place to park another
repository's data model. Giving the pricing engine a commercial context would mean it has to
version one, and the two harnesses would stop being able to move independently — the thing
their separation exists to protect. When a commercial-context contract is genuinely wanted
over there, it gets designed and versioned as its own interface.

What it is for is the question a person asks in front of a price: *why this, for whom, on what
basis, and what does nobody know yet.* The UI reads it, Phase 9 renders it, an audit checks it.

Two rules shape what goes in.

**Minimised.** Not the whole analysis. The four MN06 claims are the commercial lens and are
always named; PROBLEM, KBF and COMPETITIVE_ADVANTAGE come along only when Phase 5 actually
settled them; everything else stays in :class:`~core.models.ClientAnalysis`, one
``analysis_id`` away. No source text is copied at any point — claims are already
interpretations, and the passages behind them are reachable through ``finding_ids``.

**Carrying its provenance.** Crossing out of the analysis means ``analysis_id`` can no longer
be resolved by whoever is reading. So a copied claim brings ``evidence_type``, ``confidence``,
``finding_ids`` and ``framework_basis`` with it. ``PRICE_SENSITIVITY`` and ``VALUE_DRIVER`` are
SYNTHESIS dimensions capped at LOW confidence (``core/analysis/dimensions.py``); somebody
setting a price is entitled to know that before they read the sentence.
"""
from __future__ import annotations

from typing import Optional

from core.models import (
    SCHEMA_VERSION,
    AnalysisDimension,
    ClientAnalysis,
    EvidenceTiming,
    InternationalDimension,
    MarketScope,
    ProposalStrategy,
)
from core.pricing_bridge.gaps import gaps_for
from core.pricing_bridge.models import CommercialInput

D = AnalysisDimension
I = InternationalDimension

#: The commercial lens itself. Always reported, settled or not — an absent MN06 answer is a
#: fact about this pricing case, and leaving it out would read as "not relevant".
PRICING_DIMENSIONS: tuple[AnalysisDimension, ...] = (
    D.VALUE_DRIVER,
    D.PRICE_SENSITIVITY,
    D.BUDGET_EVIDENCE,
    D.PROCUREMENT_CONTEXT,
)

#: Carried only when established. What is being solved, what the purchase is decided on, and
#: why us — the three that change a price rather than describe a client.
SUPPORTING_DIMENSIONS: tuple[AnalysisDimension, ...] = (
    D.PROBLEM,
    D.KBF,
    D.COMPETITIVE_ADVANTAGE,
)

#: Overseas questions that ``core/analysis/dimensions.py`` reads through MN06. Carried only
#: for an INTERNATIONAL analysis, and only when established. A tariff is a cost and an FX
#: exposure is a margin — but neither ever becomes a number here: see ``payload.py``.
INTERNATIONAL_PRICING_DIMENSIONS: tuple[InternationalDimension, ...] = (
    I.TARIFF,
    I.CURRENCY_FX,
)

#: Gaps that bear on a commercial decision. The rest are counted, not copied.
COMMERCIAL_TIMINGS: tuple[EvidenceTiming, ...] = (
    EvidenceTiming.BEFORE_PRICING,
    EvidenceTiming.BEFORE_CONTRACT,
)


def build_commercial_context(
    *,
    pricing_case_id: str,
    strategy: ProposalStrategy,
    analysis: ClientAnalysis,
    commercial: CommercialInput,
    bindings: Optional[dict] = None,
) -> dict:
    """Assemble the context that explains one pricing case.

    ``bindings`` maps ``component_id`` to the solution element ref it prices. It is the half of
    the binding that could not go into the payload, because the external ``price_component``
    object is closed — so this is the only place the two halves meet.
    """
    binding_for = {ref: cid for cid, ref in (bindings or {}).items()}

    return {
        #: Ours, not the pricing harness's. This block never crosses the boundary.
        "schema_version": SCHEMA_VERSION,
        "pricing_case_id": pricing_case_id,
        "strategy_id": strategy.strategy_id,
        "analysis_id": strategy.analysis_id,
        "client_id": strategy.client_id,
        "client_name": strategy.client_name,
        "country": strategy.country,
        "market_scope": analysis.market_scope.value,
        "objective": strategy.objective.value if strategy.objective else None,
        "objective_source": (
            strategy.objective_source.value if strategy.objective_source else None
        ),
        "offered": [
            {
                "ref": element.ref,
                "text": element.text,
                "component_id": binding_for.get(element.ref),
            }
            for element in strategy.selected_solution_elements
        ],
        "claims": _claims(analysis),
        "international_claims": _international_claims(analysis),
        "evidence_needs": _evidence_needs(strategy),
        "open_gap_counts": _gap_counts(strategy),
        "expected_quantity": commercial.expected_quantity,
        "commercial_conditions": list(commercial.commercial_conditions),
    }


def _established(claim) -> bool:
    """Phase 6's gate, read rather than re-derived: a statement with findings behind it."""
    return bool(claim is not None and claim.statement and claim.finding_ids)


def _claim_entry(claim) -> dict:
    return {
        "established": True,
        "statement": claim.statement,
        "evidence_type": claim.evidence_type.value,
        "confidence": claim.confidence.value,
        "finding_ids": list(claim.finding_ids),
        "framework_basis": list(claim.framework_basis),
    }


def _claims(analysis: ClientAnalysis) -> dict:
    out: dict[str, dict] = {}

    for dimension in PRICING_DIMENSIONS:
        claim = analysis.claim_for(dimension)
        if _established(claim):
            out[dimension.value] = _claim_entry(claim)
        else:
            out[dimension.value] = {
                "established": False,
                "missing_evidence": list(claim.missing_evidence) if claim else [],
            }

    for dimension in SUPPORTING_DIMENSIONS:
        claim = analysis.claim_for(dimension)
        if _established(claim):
            out[dimension.value] = _claim_entry(claim)

    return out


def _international_claims(analysis: ClientAnalysis) -> dict:
    if analysis.market_scope is not MarketScope.INTERNATIONAL:
        return {}
    by_dimension = {claim.dimension: claim for claim in analysis.international_claims}
    return {
        dimension.value: _claim_entry(by_dimension[dimension])
        for dimension in INTERNATIONAL_PRICING_DIMENSIONS
        if _established(by_dimension.get(dimension))
    }


def _evidence_needs(strategy: ProposalStrategy) -> list[dict]:
    """The commercial gaps, each carrying both halves.

    ``gap_ref`` is what a caller sends back to acknowledge one; ``need`` is what a person
    reads on the screen. Phase 8 needs both — display the sentence, round-trip the reference —
    and giving it only the sentence would make the UI acknowledge gaps by retyping the
    analysis's prose.
    """
    return [
        gap.as_context() for gap in gaps_for(strategy) if gap.timing in COMMERCIAL_TIMINGS
    ]


def _gap_counts(strategy: ProposalStrategy) -> dict:
    """Every timing, counted. Minimising what is copied must not hide that something exists."""
    counts = {timing.value: 0 for timing in EvidenceTiming}
    for need in strategy.evidence_needs:
        counts[need.timing.value] += 1
    return counts
