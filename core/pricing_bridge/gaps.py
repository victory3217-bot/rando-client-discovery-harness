# -*- coding: utf-8 -*-
"""The one gate this phase enforces, and the reference an acknowledgement is made against.

``EvidenceTiming.BEFORE_PRICING`` is not a note. It is Phase 6 saying that this thing has to
be known *before a price is set* — and the commonest example is the budget. Pricing against a
budget nobody checked produces a number that looks as finished as any other.

What is withheld is the hand-off, not the payload. The payload is built and can be read, so
that a person can see exactly what would be sent and decide. That distinction is why the
status is ``HANDOFF_BLOCKED`` rather than anything about a payload.

Only ``BEFORE_PRICING`` blocks. ``UNCLASSIFIED`` is the timing nobody assigned and blocking on
it would manufacture the urgency that ``EvidenceTiming`` exists to avoid inventing;
``OPTIONAL`` has already been judged not to matter; ``BEFORE_PROPOSAL`` and
``BEFORE_CONTRACT`` are gates for other moments, and enforcing them here would quietly move
them.

**A person lets a gap through by naming its ``gap_ref``, not its text.** This is the same rule
the rest of the harness follows about prose: ``HARNESS.md`` section 7 — *산문을 식별자로 쓰지
않는다*. A sentence used as a key merges two different gaps that happen to read alike, and
breaks every reference to a gap the moment somebody tidies its wording. It also means an
acknowledgement would be made by retyping the analysis's own prose back at it, which is not a
decision anyone can audit.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Optional, Sequence

from core.models import (
    AnalysisDimension,
    EvidenceNeed,
    EvidenceTiming,
    PricingStatus,
    ProposalStrategy,
)
from core.pricing_bridge.codes import STAGE, PricingFlagCode
from core.research.models import ReviewFlag

#: The only timing that holds a hand-off back.
BLOCKING_TIMING = EvidenceTiming.BEFORE_PRICING

_GAP_REF_PREFIX = "gap_"
#: 64 bits of digest. Enough that two gaps in one strategy do not collide; short enough to
#: read in a URL or a log line.
_GAP_REF_CHARS = 16
#: Unit separator: a character that cannot occur in a need, so the fields cannot run together
#: and make two different gaps hash alike.
_FIELD_SEPARATOR = "\x1f"
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class PricingGap:
    """One thing nobody has checked yet: a reference to act on and a sentence to show.

    The two halves are the point, and they are the same two halves
    :class:`~core.models.SelectedSolutionElement` keeps apart. ``gap_ref`` is what a caller
    sends back to acknowledge the gap; ``need`` is what a person reads. A UI displays ``need``
    and round-trips ``gap_ref``, so tidying the wording of a gap never silently transfers an
    approval, and two gaps that happen to read alike never merge into one.
    """

    gap_ref: str
    need: str
    timing: EvidenceTiming
    dimension: Optional[AnalysisDimension] = None

    @property
    def blocking(self) -> bool:
        return self.timing is BLOCKING_TIMING

    def as_context(self) -> dict:
        """The form the commercial context carries: both halves, so a UI can do both jobs."""
        return {
            "gap_ref": self.gap_ref,
            "need": self.need,
            "timing": self.timing.value,
            "dimension": self.dimension.value if self.dimension else None,
        }


@dataclass(frozen=True)
class GateDecision:
    """What the gate decided, and what the caller sent that the gate could not use."""

    status: PricingStatus
    review_flags: tuple = ()
    #: Refs naming no gap of this strategy. The caller is working from a stale view.
    unknown_refs: tuple = ()
    #: Refs for real gaps that were never blocking. Recorded so nobody reads the gate as
    #: having honoured them.
    non_blocking_refs: tuple = ()


def gap_ref_for(strategy_id: str, need: EvidenceNeed) -> str:
    """A deterministic, opaque reference for one gap of one strategy.

    The digest covers everything that makes this gap *this* gap: the strategy it belongs to,
    what has to be found out, by when, and which dimension it came from. Change any of those
    and the ref changes, which is deliberate — an acknowledgement is a person taking
    responsibility for a specific gap as it was worded when they read it, and it should not
    survive that gap becoming a different one. ``docs/product-spec.md`` records this.

    The strategy id is in the digest so that a ref cannot be carried from one proposal to
    another. Two clients can easily have a gap that reads identically; an approval given for
    one of them is not an approval for the other.

    Only whitespace is normalised. Case, punctuation and wording are left exactly as the
    analysis wrote them — folding any of those would be this module deciding that two
    differently worded gaps mean the same thing, which is precisely the semantic judgement
    this repository does not make (``docs/development-guide.md`` backlog).

    SHA-256 from the standard library: deterministic across processes and machines, no
    dependency, and it does not carry the need's text into the reference.
    """
    material = _FIELD_SEPARATOR.join(
        (
            strategy_id,
            _WHITESPACE.sub(" ", need.need).strip(),
            need.timing.value,
            need.dimension.value if need.dimension else "",
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"{_GAP_REF_PREFIX}{digest[:_GAP_REF_CHARS]}"


def gaps_for(strategy: ProposalStrategy) -> list[PricingGap]:
    """Every gap on the strategy, each with its reference, in the order it was recorded.

    Gaps identical in all four respects collapse into one, because they are one gap recorded
    twice — and a list where the same ref appears twice would make "every blocking gap was
    acknowledged" ambiguous.
    """
    seen: set[str] = set()
    out: list[PricingGap] = []
    for need in strategy.evidence_needs:
        ref = gap_ref_for(strategy.strategy_id, need)
        if ref in seen:
            continue
        seen.add(ref)
        out.append(
            PricingGap(
                gap_ref=ref,
                need=need.need,
                timing=need.timing,
                dimension=need.dimension,
            )
        )
    return out


def open_before_pricing(strategy: ProposalStrategy) -> list[PricingGap]:
    """Every gap Phase 6 said has to be closed before a price is set."""
    return [gap for gap in gaps_for(strategy) if gap.blocking]


def unacknowledged(
    strategy: ProposalStrategy, acknowledged_gap_refs: Sequence[str] = ()
) -> list[PricingGap]:
    """Blocking gaps nobody has named. Matching is on ``gap_ref``, never on the text."""
    named = set(acknowledged_gap_refs)
    return [gap for gap in open_before_pricing(strategy) if gap.gap_ref not in named]


def resolve_gate(
    strategy: ProposalStrategy, acknowledged_gap_refs: Sequence[str] = ()
) -> GateDecision:
    """Decide whether this case may be handed over, and say why.

    A ref that names no gap of this strategy is **not ignored**. It means the caller is acting
    on a view of the strategy that has since changed — the gap was reworded, retimed, closed,
    or belongs to another proposal — and in that state the acknowledgement the caller believes
    they gave is not the one that would be recorded. The run is refused rather than quietly
    proceeding on the subset that still resolves.

    A ref for a gap that was never blocking is harmless and is flagged, not refused: nothing
    was unlocked by it, and the flag stops a reader concluding the gate honoured it.

    The counts in the flags are deliberate. A gap's text is the analysis's prose and
    diagnostics in this harness carry codes and counts, not content.
    """
    by_ref = {gap.gap_ref: gap for gap in gaps_for(strategy)}
    named = list(dict.fromkeys(acknowledged_gap_refs))

    unknown = tuple(ref for ref in named if ref not in by_ref)
    non_blocking = tuple(ref for ref in named if ref in by_ref and not by_ref[ref].blocking)

    flags: list[ReviewFlag] = []
    if non_blocking:
        flags.append(
            ReviewFlag(
                STAGE,
                PricingFlagCode.NON_BLOCKING_GAP_ACKNOWLEDGED,
                str(len(non_blocking)),
            )
        )

    if unknown:
        # The status is not the answer here; the pipeline refuses the run. Reported so the
        # decision is readable on its own.
        return GateDecision(
            status=PricingStatus.HANDOFF_BLOCKED,
            review_flags=tuple(flags),
            unknown_refs=unknown,
            non_blocking_refs=non_blocking,
        )

    blocking = open_before_pricing(strategy)
    if not blocking:
        return GateDecision(
            status=PricingStatus.PAYLOAD_READY,
            review_flags=tuple(flags),
            non_blocking_refs=non_blocking,
        )

    still_open = unacknowledged(strategy, named)
    if still_open:
        flags.append(
            ReviewFlag(STAGE, PricingFlagCode.BEFORE_PRICING_GAP_OPEN, str(len(still_open)))
        )
        return GateDecision(
            status=PricingStatus.HANDOFF_BLOCKED,
            review_flags=tuple(flags),
            non_blocking_refs=non_blocking,
        )

    flags.append(ReviewFlag(STAGE, PricingFlagCode.GAPS_ACKNOWLEDGED, str(len(blocking))))
    return GateDecision(
        status=PricingStatus.PAYLOAD_READY,
        review_flags=tuple(flags),
        non_blocking_refs=non_blocking,
    )
