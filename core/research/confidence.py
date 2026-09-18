# -*- coding: utf-8 -*-
"""What a finding's confidence is allowed to be.

The validator's job is to bring an over-confident answer down, never to push a cautious one up.
A model that says MEDIUM has said MEDIUM; a model that says HIGH has to earn it.

**Nothing here grants HIGH on the strength of a single property.** Not the source category, not
the presence of a publisher. A company's own deck is not authoritative about its market, and a
named publisher is not the same as a checked claim. HIGH requires several things at once, which
in practice means it is rare — and that is the intended behaviour, not a defect.

The factors considered:

directness      how close the evidence is to the document. A FACT resolves to exactly one
                passage or it is rejected outright — but a search snippet is an engine's
                extract, not the page, and cannot be treated as if someone had read it.
authority       is the source identified well enough to be weighed at all?
corroboration   do independent sources say the same thing?
recency         is the source recent enough for the claim it supports?
quality         what the retrieval adapter recorded, defaulting to UNKNOWN.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from core.models import Confidence, EvidenceType, SourceCategory, SourceMetadata, SourceOrigin
from core.research.policy import DEFAULT_RESEARCH_POLICY, SNIPPET_LOCATOR, ResearchPolicy

#: Weakest to strongest. Comparison and capping are done by position.
_ORDER: tuple[Confidence, ...] = (
    Confidence.UNKNOWN,
    Confidence.LOW,
    Confidence.MEDIUM,
    Confidence.HIGH,
)


def rank(level: Confidence) -> int:
    return _ORDER.index(level)


def weakest(levels: Sequence[Confidence]) -> Confidence:
    """The lowest level in a set. An inference is as strong as its weakest support."""
    if not levels:
        return Confidence.UNKNOWN
    return min(levels, key=rank)


def cap(proposed: Confidence, ceiling: Confidence) -> Confidence:
    """Lower ``proposed`` to ``ceiling`` when it exceeds it. Never raises it."""
    return proposed if rank(proposed) <= rank(ceiling) else ceiling


@dataclass(frozen=True)
class ConfidenceSignals:
    """What is known about the evidence behind one finding."""

    source: Optional[SourceMetadata] = None

    #: How many distinct sources independently support this claim.
    #:
    #: Defaults to 1, meaning "only this one". Automatic corroboration detection would need to
    #: decide that two differently-worded passages say the same thing, which is a semantic
    #: judgement this phase does not make. Until a human or a later stage supplies a real count,
    #: a single-source claim cannot reach HIGH — the conservative direction to be wrong in.
    corroborating_source_count: int = 1

    #: Today, as an ISO date, for the recency check. Supplied rather than read from the clock so
    #: that the core stays free of ambient state and the rule is testable.
    today: Optional[str] = None

    #: Where in the source the evidence sat. ``"snippet"`` means a search engine's extract
    #: rather than the document itself, which caps confidence on its own.
    locator: Optional[str] = None


def _year(value: Optional[str]) -> Optional[int]:
    if not value or len(value) < 4 or not value[:4].isdigit():
        return None
    return int(value[:4])


def _authority_known(source: Optional[SourceMetadata]) -> bool:
    """Whether the source is identified well enough to be weighed.

    Deliberately weak: this asks "can we tell who is speaking", not "are they right".
    """
    if source is None:
        return False
    if source.source_origin is SourceOrigin.SEARCH_RESULT:
        return bool((source.publisher or "").strip())
    if source.source_origin is SourceOrigin.UPLOADED_FILE:
        if source.source_category is SourceCategory.EXTERNAL_BUSINESS_DATA:
            return bool((source.publisher or "").strip())
        return source.source_category in (
            SourceCategory.CONSULTING_OUTPUT,
            SourceCategory.COMPANY_DATA,
        )
    return False


def _is_unverified_snippet(source: Optional[SourceMetadata], signals: ConfidenceSignals) -> bool:
    """Evidence taken from a search snippet rather than from the document itself."""
    return (
        source is not None
        and source.source_origin is SourceOrigin.SEARCH_RESULT
        and signals.locator == SNIPPET_LOCATOR
    )


def _is_recent(source: Optional[SourceMetadata], signals: ConfidenceSignals,
               policy: ResearchPolicy) -> bool:
    if source is None:
        return False
    source_year = _year(source.source_date)
    if source_year is None:
        return False
    now_year = _year(signals.today)
    if now_year is None:
        return True  # no reference point; do not penalise on a guess
    return (now_year - source_year) <= policy.stale_source_years


def ceiling_for(
    evidence_type: EvidenceType,
    signals: ConfidenceSignals = ConfidenceSignals(),
    *,
    supporting: Sequence[Confidence] = (),
    policy: ResearchPolicy = DEFAULT_RESEARCH_POLICY,
) -> Confidence:
    """The highest confidence this finding may carry, and why.

    Returns the ceiling; the caller applies it with :func:`cap`.
    """
    if evidence_type is EvidenceType.MISSING_EVIDENCE:
        return Confidence.UNKNOWN

    if evidence_type is EvidenceType.ASSUMPTION:
        return Confidence.LOW

    if evidence_type is EvidenceType.INFERENCE:
        # An inference cannot be firmer than the findings it stands on.
        return weakest(list(supporting))

    # FACT. Start from HIGH and take away what is not established.
    source = signals.source
    if source is None:
        return Confidence.UNKNOWN

    if _is_unverified_snippet(source, signals):
        # A search snippet is a few lines an engine chose to show. Nothing here has opened the
        # page, so however reputable the publisher and however many results agree, the claim has
        # not been checked against the document. A later phase that actually retrieves the page
        # would record a different origin and could reach HIGH.
        return Confidence.MEDIUM

    if not _authority_known(source):
        return Confidence.MEDIUM
    if signals.corroborating_source_count < policy.corroboration_for_high:
        return Confidence.MEDIUM
    if not _is_recent(source, signals, policy):
        return Confidence.MEDIUM

    return Confidence.HIGH


def reasons_for(
    evidence_type: EvidenceType,
    signals: ConfidenceSignals = ConfidenceSignals(),
    *,
    policy: ResearchPolicy = DEFAULT_RESEARCH_POLICY,
) -> list[str]:
    """Human-readable reasons the ceiling landed where it did.

    Useful in a report: "capped at MEDIUM because only one source supports it" tells a reader
    something that the bare word MEDIUM does not.
    """
    if evidence_type is EvidenceType.MISSING_EVIDENCE:
        return ["nothing was found, so no confidence applies"]
    if evidence_type is EvidenceType.ASSUMPTION:
        return ["stated as an assumption, so it cannot exceed LOW"]
    if evidence_type is EvidenceType.INFERENCE:
        return ["an inference is limited by its weakest supporting finding"]

    source = signals.source
    if source is None:
        return ["no source record"]

    if _is_unverified_snippet(source, signals):
        return ["the evidence is a search snippet; the page itself has not been read"]

    reasons: list[str] = []
    if not _authority_known(source):
        reasons.append("the source is not identified well enough to weigh")
    if signals.corroborating_source_count < policy.corroboration_for_high:
        reasons.append(
            f"only {signals.corroborating_source_count} source supports it "
            f"({policy.corroboration_for_high} needed for HIGH)"
        )
    if not _is_recent(source, signals, policy):
        reasons.append(
            "the source has no date, or is older than "
            f"{policy.stale_source_years} years"
        )
    return reasons or ["authority, corroboration and recency are all established"]
