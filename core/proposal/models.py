# -*- coding: utf-8 -*-
"""Transient objects for one proposal-strategy run.

Nothing here is persisted. The one entity this phase produces is
:class:`~core.models.ProposalStrategy`; everything below exists for the duration of a run.

:class:`SolutionElement` is the piece that matters. What we are able to sell is supplied by the
caller and given a short reference key; the model may return those keys and nothing else. There
is no free-text field anywhere in this phase's output schemas for describing our product, which
is what stops a proposal quietly acquiring a local service network we do not have.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.models import AnalysisDimension, ProposalObjective


@dataclass
class SolutionElement:
    """One thing we can actually offer, as the caller stated it.

    ``ref`` is a short key (``S1``, ``S2``) the model cites, the same device the evidence
    blocks use. ``text`` is the caller's wording and is never rewritten: a model that may
    rephrase what we sell may also extend it.
    """

    ref: str
    text: str


@dataclass(repr=False)
class StatementDraft:
    """A sentence the model proposes, before the rules run.

    ``solution_element_refs`` are the model's keys (``S1``), resolved against the caller's list
    before anything is stored.
    """

    text: Optional[str] = None
    dimensions: list[AnalysisDimension] = field(default_factory=list)
    solution_element_refs: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        return (
            f"<StatementDraft chars={len(self.text or '')} "
            f"dimensions={len(self.dimensions)} offers={len(self.solution_element_refs)}>"
        )


@dataclass(repr=False)
class ObjectionDraft:
    """An objection as the model returned it."""

    objection: Optional[str] = None
    basis: Optional[str] = None
    dimensions: list[AnalysisDimension] = field(default_factory=list)
    response: Optional[str] = None
    response_dimensions: list[AnalysisDimension] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        return (
            f"<ObjectionDraft basis={self.basis} chars={len(self.objection or '')} "
            f"answered={self.response is not None}>"
        )


@dataclass
class ProposalOutcome:
    """Everything one strategy run produced, including what it refused."""

    strategies: list = field(default_factory=list)
    #: Objectives the model suggested that the evidence did not carry. Kept for the report,
    #: never promoted into the strategy.
    withdrawn_objectives: list[ProposalObjective] = field(default_factory=list)
    rejections: list = field(default_factory=list)
    review_flags: list = field(default_factory=list)
    transmissions: list = field(default_factory=list)

    def summary(self) -> dict:
        """Counts only — safe to log, and names nobody."""
        strategies = self.strategies
        return {
            "strategies": len(strategies),
            "with_objective": sum(1 for s in strategies if s.objective is not None),
            "storyline_steps": sum(len(s.storyline) for s in strategies),
            "objections": sum(len(s.objections) for s in strategies),
            "evidence_needs": sum(len(s.evidence_needs) for s in strategies),
            "withdrawn_objectives": len(self.withdrawn_objectives),
            "rejections": len(self.rejections),
            "review_flags": len(self.review_flags),
            "transmissions": len(self.transmissions),
        }
