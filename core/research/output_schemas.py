# -*- coding: utf-8 -*-
"""What the model is allowed to return.

These are *not* the entity schemas. ``schemas/`` is the contract for what gets stored; these
are the much smaller contracts for what a model may produce, and they live in code because
publishing them alongside the persisted entities would blur that line.

The point of keeping them small is control of provenance. Every field the pipeline already
knows — identifiers, ``mn_basis``, source fields, timestamps, ``market_scope`` — is absent, so
the model has no opportunity to invent one. Checked against a real provider: ``EchoLLM``
synthesising the full finding schema happily produces ``mn_basis: ["[echo] mn_basis[0]"]``, a
framework id that does not exist. A model asked for a field will fill it.
"""
from __future__ import annotations

_REF = {"type": "string", "minLength": 1}


#: Pass 1 — direct reading of evidence.
#:
#: ``INFERENCE`` is absent from the enum on purpose: an inference needs other findings to reason
#: from, and in pass 1 there are none yet. Leaving it out makes the wrong answer unrepresentable
#: rather than merely discouraged.
FINDING_BATCH: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Finding extraction result",
    "type": "object",
    "additionalProperties": False,
    "required": ["findings"],
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["finding", "evidence_type", "confidence"],
                "properties": {
                    "evidence_ref": {
                        "type": ["string", "null"],
                        "description": "Exactly one evidence key, e.g. E2, for a FACT. Null for ASSUMPTION and MISSING_EVIDENCE.",
                    },
                    "finding": {"type": "string", "minLength": 1},
                    "evidence_type": {
                        "type": "string",
                        "enum": ["FACT", "ASSUMPTION", "MISSING_EVIDENCE"],
                    },
                    "confidence": {
                        "type": "string",
                        "enum": ["HIGH", "MEDIUM", "LOW", "UNKNOWN"],
                    },
                    "evidence_summary": {"type": ["string", "null"]},
                    "dimension": {
                        "type": ["string", "null"],
                        "description": "Which framework dimension this answers, by key.",
                    },
                },
            },
        }
    },
}


#: Pass 2 — reasoning over pass 1's findings. ``evidence_type`` is not asked for: everything
#: this call produces is an INFERENCE by construction.
INFERENCE_BATCH: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Inference result",
    "type": "object",
    "additionalProperties": False,
    "required": ["inferences"],
    "properties": {
        "inferences": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["finding", "finding_refs", "confidence"],
                "properties": {
                    "finding": {"type": "string", "minLength": 1},
                    "finding_refs": {
                        "type": "array",
                        "minItems": 1,
                        "items": _REF,
                        "description": "Keys of the findings reasoned from, e.g. F1, F3.",
                    },
                    "confidence": {
                        "type": "string",
                        "enum": ["HIGH", "MEDIUM", "LOW", "UNKNOWN"],
                    },
                    "evidence_summary": {"type": ["string", "null"]},
                },
            },
        }
    },
}


SWOT_BATCH: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "SWOT classification result",
    "type": "object",
    "additionalProperties": False,
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["category", "statement", "finding_refs"],
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["STRENGTH", "WEAKNESS", "OPPORTUNITY", "THREAT"],
                    },
                    "statement": {"type": "string", "minLength": 1},
                    "finding_refs": {"type": "array", "minItems": 1, "items": _REF},
                },
            },
        }
    },
}


KEY_ISSUE_BATCH: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Key issue result",
    "type": "object",
    "additionalProperties": False,
    "required": ["issues"],
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["statement", "decision_area", "swot_refs"],
                "properties": {
                    "statement": {"type": "string", "minLength": 1},
                    "decision_area": {"type": "string", "minLength": 1},
                    "swot_refs": {"type": "array", "minItems": 1, "items": _REF},
                    "finding_refs": {"type": "array", "items": _REF},
                    "strategic_implication": {"type": ["string", "null"]},
                    "missing_evidence": {"type": "array", "items": {"type": "string"}},
                    "confidence": {
                        "type": "string",
                        "enum": ["HIGH", "MEDIUM", "LOW", "UNKNOWN"],
                    },
                },
            },
        }
    },
}


ALL_OUTPUT_SCHEMAS = {
    "FINDING_BATCH": FINDING_BATCH,
    "INFERENCE_BATCH": INFERENCE_BATCH,
    "SWOT_BATCH": SWOT_BATCH,
    "KEY_ISSUE_BATCH": KEY_ISSUE_BATCH,
}
