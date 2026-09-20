# -*- coding: utf-8 -*-
"""What the model is allowed to return while a strategy is drafted.

The absences are the design, as in every other engine here.

There is **no field for describing our product**. ``solution_element_refs`` carries keys into
the list the caller supplied, so what is offered can be selected but not written. A proposal
cannot acquire a certification, a support desk or a local service network through this
interface, because there is nowhere to type one.

There is **no default objective**. ``suggested_objective`` may be null, and a suggestion that
the evidence does not carry is withdrawn rather than lowered to something safer — a quiet
fallback is the pipeline deciding what the proposal is for.

There is no competitive advantage, no priority, no price, and no confidence. The first is
Phase 5's to establish, the second Phase 4's, the third Phase 7's, and the last is not
something a model knows about its own output.
"""
from __future__ import annotations

from core.models import (
    MAX_CLAIM_STATEMENT_CHARS,
    AnalysisDimension,
    EvidenceTiming,
    ObjectionBasis,
    ProposalObjective,
    StoryStepType,
)

_DIMENSIONS = {
    "type": "array",
    "items": {"type": "string", "enum": [d.value for d in AnalysisDimension]},
    "description": (
        "Which analysis dimensions this rests on. Only dimensions the analysis actually "
        "settled count; the rest are dropped."
    ),
}

_TEXT = {"type": ["string", "null"], "maxLength": MAX_CLAIM_STATEMENT_CHARS}

_GAPS = {"type": "array", "items": {"type": "string"}}

_STATEMENT_REFS = {
    "type": "array",
    "items": {"type": "string", "minLength": 1},
    "description": (
        "Keys of the solution elements this sentence offers, such as S1. At least one, drawn "
        "from the supplied list - a sentence proposing nothing in particular is an observation."
    ),
}


PROPOSAL_STRATEGY: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Proposal strategy",
    "type": "object",
    "additionalProperties": False,
    "required": ["storyline"],
    "properties": {
        "suggested_objective": {
            "type": ["string", "null"],
            "enum": [o.value for o in ProposalObjective] + [None],
            "description": (
                "The next thing that could realistically happen. Null when the evidence does "
                "not support any of them. Rarely a formal proposal: most candidates are at the "
                "stage of arranging a conversation."
            ),
        },
        "objective_detail": _TEXT,
        "solution_element_refs": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "description": (
                "Keys of the supplied solution elements that apply here, such as S1. You may "
                "select from that list and nothing else - do not describe a capability that is "
                "not in it."
            ),
        },
        "value_proposition": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "properties": {
                "text": _TEXT,
                "dimensions": _DIMENSIONS,
                "solution_element_refs": _STATEMENT_REFS,
                "missing_evidence": _GAPS,
            },
        },
        "key_message": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "properties": {
                "text": _TEXT,
                "dimensions": _DIMENSIONS,
                "solution_element_refs": _STATEMENT_REFS,
                "missing_evidence": _GAPS,
            },
            "description": (
                "The central claim. Any figure in it must appear in one of the cited claims - "
                "do not produce a percentage, a multiple or a payback period that no document "
                "states."
            ),
        },
        "storyline": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["step_type"],
                "properties": {
                    "step_type": {
                        "type": "string",
                        "enum": [s.value for s in StoryStepType],
                    },
                    "message": _TEXT,
                    "dimensions": _DIMENSIONS,
                    "missing_evidence": _GAPS,
                },
            },
            "description": (
                "The order of the argument, not a table of contents. Include DIFFERENTIATION "
                "only where the analysis established a competitive advantage."
            ),
        },
        "evidence_timing": {
            "type": "array",
            "description": (
                "When each recorded gap has to be closed. A gap you leave out is kept and "
                "marked UNCLASSIFIED - it is neither dropped nor treated as urgent, so say "
                "nothing rather than guessing."
            ),
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["need", "timing"],
                "properties": {
                    "need": {"type": "string", "minLength": 1},
                    "timing": {
                        "type": "string",
                        "enum": [t.value for t in EvidenceTiming],
                    },
                },
            },
        },
    },
}


PROPOSAL_OBJECTIONS: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Proposal objections",
    "type": "object",
    "additionalProperties": False,
    "required": ["objections"],
    "properties": {
        "objections": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["objection", "basis"],
                "properties": {
                    "objection": {"type": "string", "minLength": 1, "maxLength": MAX_CLAIM_STATEMENT_CHARS},
                    "basis": {
                        "type": "string",
                        "enum": [b.value for b in ObjectionBasis],
                        "description": (
                            "EVIDENCE_BACKED only where a cited claim shows the customer holds "
                            "this concern. Everything you merely expect is ANTICIPATED."
                        ),
                    },
                    "dimensions": _DIMENSIONS,
                    "response": _TEXT,
                    "response_dimensions": _DIMENSIONS,
                    "missing_evidence": _GAPS,
                },
            },
        },
    },
}


ALL_OUTPUT_SCHEMAS = {
    "PROPOSAL_STRATEGY": PROPOSAL_STRATEGY,
    "PROPOSAL_OBJECTIONS": PROPOSAL_OBJECTIONS,
}
