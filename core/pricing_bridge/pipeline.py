# -*- coding: utf-8 -*-
"""One analysis, one strategy and one cost sheet in; one pricing case out.

Look at the signature of :func:`run_pricing_handoff`: no ``llm``, no ``prompts``, no
``project`` (which the other pipelines take only to know what language to ask a model in).
There is nothing to send, so there is nothing to send it with. Phase 7 is a deterministic
bridge — run it twice on the same inputs and the two payloads are byte-identical.

The phase also does not run pricing. The core builds the document and stops; an adapter writes
it out, the pricing harness computes in its own process, and :func:`attach_engine_result`
records what came back. That is why there is no fifth provider on ``create_harness()``: a
provider is something the core calls, and the core never calls this one.

Nothing here writes to a Phase 6 record. A pricing case does not advance
``ProposalStrategy.status`` to ``PRICING_REQUESTED``, for the same reason a deep analysis does
not rewrite a Phase 4 priority band — a later phase editing an earlier phase's judgement makes
the earlier record stop meaning what it says.
"""
from __future__ import annotations

import dataclasses
from typing import Optional, Sequence

from core.evidence import check_pricing_result
from core.models import (
    ClientAnalysis,
    PricingResult,
    PricingStatus,
    ProposalStrategy,
    new_id,
)
from core.pricing_bridge.codes import STAGE, PricingRejectionCode
from core.pricing_bridge.context import build_commercial_context
from core.pricing_bridge.gaps import resolve_gate
from core.pricing_bridge.models import CommercialInput, PricingOutcome
from core.pricing_bridge.payload import build_pricing_payload
from core.pricing_bridge.policy import DEFAULT_PRICING_POLICY, PricingBridgePolicy
from core.research.models import Rejection


def run_pricing_handoff(
    *,
    analysis: ClientAnalysis,
    strategy: ProposalStrategy,
    commercial: CommercialInput,
    acknowledged_gap_refs: Sequence[str] = (),
    pricing_case_id: Optional[str] = None,
    policy: PricingBridgePolicy = DEFAULT_PRICING_POLICY,
) -> PricingOutcome:
    """Build one pricing case.

    ``acknowledged_gap_refs`` are ``PricingGap.gap_ref`` values, never the wording of a gap.
    A caller reads the gaps out of ``commercial_context`` (or from
    :func:`~core.pricing_bridge.gaps.gaps_for`), shows a person the ``need``, and sends back
    the ``gap_ref``. A ref this strategy does not have refuses the run rather than being
    skipped — see :func:`~core.pricing_bridge.gaps.resolve_gate`.

    ``pricing_case_id`` defaults to a fresh identifier, which is what makes a second call on
    the same strategy a second case rather than an overwrite. Pass one to rebuild a case in
    place — for instance after a cost correction, where the point is that it *is* the same
    case.
    """
    outcome = PricingOutcome()
    case_id = pricing_case_id or new_id("pcs")

    if not strategy.analysis_id or strategy.analysis_id != analysis.analysis_id:
        outcome.rejections.append(Rejection(STAGE, PricingRejectionCode.UNKNOWN_ANALYSIS))
        return outcome
    if strategy.client_id != analysis.client_id:
        outcome.rejections.append(Rejection(STAGE, PricingRejectionCode.CLIENT_MISMATCH))
        return outcome

    if len(commercial.price_components) > policy.max_price_components:
        outcome.rejections.append(
            Rejection(STAGE, PricingRejectionCode.TOO_MANY_ITEMS, "price_components")
        )
        return outcome
    if len(commercial.cost_items) > policy.max_cost_items:
        outcome.rejections.append(
            Rejection(STAGE, PricingRejectionCode.TOO_MANY_ITEMS, "cost_items")
        )
        return outcome

    build = build_pricing_payload(
        client_id=strategy.client_id,
        pricing_case_id=case_id,
        strategy=strategy,
        commercial=commercial,
    )
    outcome.rejections.extend(build.rejections)
    outcome.review_flags.extend(build.review_flags)
    if build.refused:
        return outcome

    gate = resolve_gate(strategy, acknowledged_gap_refs)
    outcome.review_flags.extend(gate.review_flags)
    if gate.unknown_refs:
        outcome.rejections.append(
            Rejection(
                STAGE, PricingRejectionCode.UNKNOWN_GAP_REF, str(len(gate.unknown_refs))
            )
        )
        return outcome

    result = PricingResult(
        project_id=strategy.project_id,
        client_id=strategy.client_id,
        strategy_id=strategy.strategy_id,
        analysis_id=strategy.analysis_id,
        pricing_case_id=case_id,
        pricing_payload=build.payload,
        commercial_context=build_commercial_context(
            pricing_case_id=case_id,
            strategy=strategy,
            analysis=analysis,
            commercial=commercial,
            bindings=build.bindings,
        ),
        status=gate.status,
    )

    violations = check_pricing_result(result)
    if violations:
        outcome.rejections.append(
            Rejection(STAGE, PricingRejectionCode.RESULT_INVALID, str(len(violations)))
        )
        return outcome

    outcome.results.append(result)
    return outcome


def attach_engine_result(
    result: PricingResult, engine_result: dict
) -> tuple[PricingResult, list[Rejection]]:
    """Record what the pricing harness answered, after checking it is answering *this* case.

    A file contract means the wrong file can be handed back: a stale run, another client's
    case, a result regenerated from a payload that has since changed. An answer with the right
    shape and the wrong subject is the failure mode worth spending an identity check on.

    On a match the document is stored **verbatim**. The module statuses inside it — ``OK``,
    ``INCOMPLETE``, ``UNKNOWN``, ``ERROR`` — are that harness's vocabulary, reported against
    its own dependency rules, and are not re-read, summarised or promoted into a field here.
    No number from it is copied into any entity of ours.
    """
    rejections: list[Rejection] = []
    source = engine_result.get("source") if isinstance(engine_result, dict) else None

    if not isinstance(source, dict) or not all(
        isinstance(source.get(key), str) and source.get(key)
        for key in ("client_id", "case_id", "engine_version")
    ):
        rejections.append(Rejection(STAGE, PricingRejectionCode.ENGINE_RESULT_MALFORMED))
        return (
            dataclasses.replace(
                result,
                status=PricingStatus.FAILED,
                error_code=PricingRejectionCode.ENGINE_RESULT_MALFORMED,
            ),
            rejections,
        )

    if source["case_id"] != result.pricing_case_id or source["client_id"] != result.client_id:
        rejections.append(Rejection(STAGE, PricingRejectionCode.ENGINE_RESULT_MISMATCH))
        return (
            dataclasses.replace(
                result,
                status=PricingStatus.FAILED,
                error_code=PricingRejectionCode.ENGINE_RESULT_MISMATCH,
                # Not stored. A result belonging to another case, filed under this one, is a
                # wrong answer that reads as a right one.
                engine_result=None,
            ),
            rejections,
        )

    return (
        dataclasses.replace(
            result,
            engine_result=engine_result,
            engine_version=source["engine_version"],
            status=PricingStatus.COMPLETED,
            error_code=None,
        ),
        rejections,
    )


def persist(outcome: PricingOutcome, storage) -> None:
    """Hand the pricing cases to storage. A refused case has no record to offer."""
    for result in outcome.results:
        storage.save_pricing_result(result)
