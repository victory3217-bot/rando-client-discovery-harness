# -*- coding: utf-8 -*-
"""Proposal policy and prompt text. Pure configuration, injected by the caller."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProposalPolicy:
    """Limits for one strategy run."""

    #: Storyline steps kept. Six types exist and a step may not repeat, so this is a guard
    #: against a runaway response rather than a shape.
    max_storyline_steps: int = 6

    #: Objections kept. A cap, not a target — there is deliberately no minimum, because a
    #: minimum would be met by inventing one.
    max_objections: int = 8


DEFAULT_PROPOSAL_POLICY = ProposalPolicy()


@dataclass
class ProposalPromptSet:
    """Prompt text for each proposal stage, supplied by the caller.

    Two prompts. Making the case and anticipating pushback want different stances, and asking
    for both in one response produces objections that conveniently answer themselves.
    """

    synthesize_strategy: str
    anticipate_objections: str
