# -*- coding: utf-8 -*-
"""The priority rule table.

No model is involved and no number is computed, so every band here is reachable by an argument
a person can follow — which is the whole reason for doing it this way.
"""
from __future__ import annotations

import json

import pytest

from core.client import CORE_CRITERIA, decide_priority
from core.models import (
    ClientCandidate,
    FitAssessment,
    FitCriterion,
    FitLevel,
    PriorityReasonCode,
    SalesPriority,
)

PROJECT = "prj_priority"
DIRECT = {"src_direct"}
SNIPPET = {"src_snippet"}

L = FitLevel
C = FitCriterion


def _candidate(levels: dict, *, refs: dict | None = None) -> ClientCandidate:
    """A candidate with the given levels; every non-UNKNOWN level gets direct evidence."""
    refs = refs or {}
    fit = []
    for criterion in FitCriterion:
        level = levels.get(criterion, L.UNKNOWN)
        source_ids, finding_ids = refs.get(criterion, (["src_direct"], ["fnd_1"]))
        if level in (L.UNKNOWN,):
            source_ids, finding_ids = [], []
        missing = ["what would settle it"] if level is L.EVIDENCE_NEEDED else []
        fit.append(
            FitAssessment(
                criterion=criterion,
                level=level,
                source_ids=[] if level is L.EVIDENCE_NEEDED else list(source_ids),
                finding_ids=[] if level is L.EVIDENCE_NEEDED else list(finding_ids),
                missing_evidence=missing,
            )
        )
    return ClientCandidate(
        project_id=PROJECT,
        client_name="Fictional Alpha Water Systems",
        country="VN",
        industry="water utilities",
        discovery_rationale="their problem matches our capability",
        source_ids=["src_direct"],
        finding_ids=["fnd_1"],
        fit=fit,
    )


_ALL_POSITIVE = {
    C.PROBLEM_FIT: L.STRONG,
    C.SOLUTION_FIT: L.MODERATE,
    C.CAPABILITY_FIT: L.MODERATE,
    C.MARKET_ATTRACTIVENESS: L.MODERATE,
    C.PURCHASING_POTENTIAL: L.STRONG,
    C.ACCESSIBILITY: L.MODERATE,
    C.COMPETITIVE_SITUATION: L.MODERATE,
    C.EVIDENCE_QUALITY: L.MODERATE,
}


# -- no numbers anywhere ----------------------------------------------------

def test_no_score_field_exists() -> None:
    """A total conceals which criterion drove the answer and invites tuning the weights."""
    import dataclasses

    from core.models import PriorityDecision

    names = {f.name for f in dataclasses.fields(PriorityDecision)}
    assert names == {"band", "reason_codes", "missing_evidence"}
    assert not any("score" in n or "weight" in n or "total" in n for n in names)


def test_reasons_are_codes_not_sentences() -> None:
    """The core returns values; locales/*.json renders the prose."""
    decision = decide_priority(_candidate(_ALL_POSITIVE), direct_source_ids=DIRECT)
    assert decision.reason_codes
    for code in decision.reason_codes:
        assert isinstance(code, PriorityReasonCode)
        assert code.value == code.value.upper()


def test_every_reason_code_has_a_label_in_both_languages(repo_root) -> None:
    for lang in ("ko", "en"):
        with (repo_root / "locales" / f"{lang}.json").open(encoding="utf-8") as fh:
            labels = json.load(fh)["enums"]["PriorityReasonCode"]
        for code in PriorityReasonCode:
            assert code.value in labels, f"{lang}.json is missing {code.value}"


# -- the bands --------------------------------------------------------------

def test_p1_needs_core_fits_and_a_direct_commercial_signal() -> None:
    decision = decide_priority(_candidate(_ALL_POSITIVE), direct_source_ids=DIRECT)
    assert decision.band is SalesPriority.P1
    assert PriorityReasonCode.CORE_FIT_POSITIVE in decision.reason_codes
    assert PriorityReasonCode.COMMERCIAL_SIGNAL_CONFIRMED in decision.reason_codes


def test_p2_when_the_commercial_half_is_unsettled() -> None:
    levels = dict(_ALL_POSITIVE)
    levels[C.PURCHASING_POTENTIAL] = L.EVIDENCE_NEEDED
    levels[C.ACCESSIBILITY] = L.UNKNOWN

    decision = decide_priority(_candidate(levels), direct_source_ids=DIRECT)
    assert decision.band is SalesPriority.P2
    assert PriorityReasonCode.CORE_FIT_POSITIVE in decision.reason_codes
    assert PriorityReasonCode.PURCHASE_EVIDENCE_NEEDED in decision.reason_codes
    assert PriorityReasonCode.ACCESS_EVIDENCE_NEEDED in decision.reason_codes


def test_p3_when_several_criteria_are_unsettled() -> None:
    levels = {
        C.PROBLEM_FIT: L.MODERATE,
        C.SOLUTION_FIT: L.UNKNOWN,
        C.CAPABILITY_FIT: L.MODERATE,
    }
    decision = decide_priority(_candidate(levels), direct_source_ids=DIRECT)
    assert decision.band is SalesPriority.P3
    assert PriorityReasonCode.INSUFFICIENT_EVIDENCE in decision.reason_codes


def test_deferred_when_a_core_fit_is_unfavourable() -> None:
    """Nothing downstream rescues a core mismatch."""
    levels = dict(_ALL_POSITIVE)
    levels[C.SOLUTION_FIT] = L.WEAK

    decision = decide_priority(_candidate(levels), direct_source_ids=DIRECT)
    assert decision.band is SalesPriority.DEFERRED
    assert decision.reason_codes == [PriorityReasonCode.CORE_FIT_WEAK]


def test_deferred_when_the_competitive_situation_is_unfavourable() -> None:
    levels = dict(_ALL_POSITIVE)
    levels[C.COMPETITIVE_SITUATION] = L.WEAK

    decision = decide_priority(_candidate(levels), direct_source_ids=DIRECT)
    assert decision.band is SalesPriority.DEFERRED
    assert decision.reason_codes == [PriorityReasonCode.COMPETITIVE_BARRIER]


def test_unknown_when_the_core_is_mostly_unjudged() -> None:
    levels = {C.PROBLEM_FIT: L.UNKNOWN, C.SOLUTION_FIT: L.UNKNOWN, C.CAPABILITY_FIT: L.MODERATE}
    decision = decide_priority(_candidate(levels), direct_source_ids=DIRECT)
    assert decision.band is SalesPriority.UNKNOWN
    assert PriorityReasonCode.INSUFFICIENT_EVIDENCE in decision.reason_codes


# -- the P1 direct-evidence gate -------------------------------------------

def test_snippet_only_problem_fit_cannot_reach_p1() -> None:
    """Search summaries are not enough to place a candidate first."""
    refs = {C.PROBLEM_FIT: (["src_snippet"], [])}
    decision = decide_priority(
        _candidate(_ALL_POSITIVE, refs=refs), direct_source_ids=DIRECT
    )
    assert decision.band is SalesPriority.P2
    assert PriorityReasonCode.SNIPPET_ONLY_LIMITATION in decision.reason_codes


def test_snippet_only_commercial_signal_cannot_reach_p1() -> None:
    refs = {
        C.PURCHASING_POTENTIAL: (["src_snippet"], []),
        C.ACCESSIBILITY: (["src_snippet"], []),
    }
    decision = decide_priority(
        _candidate(_ALL_POSITIVE, refs=refs), direct_source_ids=DIRECT
    )
    assert decision.band is not SalesPriority.P1
    assert PriorityReasonCode.SNIPPET_ONLY_LIMITATION in decision.reason_codes


def test_a_candidate_known_only_from_search_can_still_be_p2() -> None:
    """Snippet evidence is worth keeping; it is only P1 that it cannot buy."""
    refs = {criterion: (["src_snippet"], []) for criterion in FitCriterion}
    decision = decide_priority(
        _candidate(_ALL_POSITIVE, refs=refs), direct_source_ids=DIRECT
    )
    assert decision.band is SalesPriority.P2
    assert PriorityReasonCode.SNIPPET_ONLY_LIMITATION in decision.reason_codes


def test_no_evidence_is_reported_as_missing_not_as_snippet_limited() -> None:
    """Two different problems needing two different pieces of work.

    A criterion with no evidence needs research; one whose evidence is a search summary needs
    somebody to open the page. Reporting both as SNIPPET_ONLY_LIMITATION would send the reader
    after the wrong task.
    """
    levels = dict(_ALL_POSITIVE)
    levels[C.PURCHASING_POTENTIAL] = L.EVIDENCE_NEEDED
    levels[C.ACCESSIBILITY] = L.EVIDENCE_NEEDED

    decision = decide_priority(_candidate(levels), direct_source_ids=DIRECT)
    assert PriorityReasonCode.SNIPPET_ONLY_LIMITATION not in decision.reason_codes
    assert PriorityReasonCode.PURCHASE_EVIDENCE_NEEDED in decision.reason_codes


def test_identity_doubt_is_recorded_without_costing_the_band() -> None:
    decision = decide_priority(
        _candidate(_ALL_POSITIVE), direct_source_ids=DIRECT, identity_verified=False
    )
    assert decision.band is SalesPriority.P1
    assert PriorityReasonCode.IDENTITY_VERIFICATION_NEEDED in decision.reason_codes


# -- gaps and determinism ---------------------------------------------------

def test_missing_evidence_is_gathered_from_every_criterion() -> None:
    levels = dict(_ALL_POSITIVE)
    levels[C.PURCHASING_POTENTIAL] = L.EVIDENCE_NEEDED
    levels[C.ACCESSIBILITY] = L.EVIDENCE_NEEDED

    decision = decide_priority(_candidate(levels), direct_source_ids=DIRECT)
    assert decision.missing_evidence == ["what would settle it"], "deduplicated, in order"


def test_the_same_candidate_always_gets_the_same_band() -> None:
    candidate = _candidate(_ALL_POSITIVE)
    first = decide_priority(candidate, direct_source_ids=DIRECT)
    second = decide_priority(candidate, direct_source_ids=DIRECT)
    assert (first.band, first.reason_codes) == (second.band, second.reason_codes)


def test_a_band_is_a_review_order_not_an_instruction() -> None:
    """Documented here because it is the thing most easily lost in a dashboard."""
    from core.models import SalesPriority as Band

    assert "not an instruction" in (Band.__doc__ or "").lower()
    assert CORE_CRITERIA == (C.PROBLEM_FIT, C.SOLUTION_FIT, C.CAPABILITY_FIT)
