# -*- coding: utf-8 -*-
"""What the model is allowed to return during client discovery.

Same principle as ``core/research/output_schemas.py``: the model is asked only for what it can
know from the evidence in front of it, and never for a field the pipeline already has.

Two absences are the point of this file.

``ORGANIZATION_MENTIONS`` asks for a name **and the reference it came from**, and nothing else.
There is no field for a company the model merely knows about, and the pipeline then checks the
name against that passage — so a plausible-sounding firm that no document mentions has no route
into the candidate pool.

``FIT_ASSESSMENT`` has no priority field at all. The band is computed from the levels by an
explicit rule, so there is nothing for a model to talk itself into.
"""
from __future__ import annotations

_REF = {"type": "string", "minLength": 1}

_CRITERIA = [
    "PROBLEM_FIT", "SOLUTION_FIT", "CAPABILITY_FIT", "MARKET_ATTRACTIVENESS",
    "PURCHASING_POTENTIAL", "ACCESSIBILITY", "COMPETITIVE_SITUATION", "EVIDENCE_QUALITY",
]
_LEVELS = ["STRONG", "MODERATE", "WEAK", "UNKNOWN", "EVIDENCE_NEEDED"]
_SIGNALS = [
    "PROCUREMENT_ACTIVITY", "BUDGET_EVIDENCE", "PROJECT_ANNOUNCEMENT", "PURCHASE_HISTORY",
    "RFP", "INVESTMENT_PLAN", "EXPANSION_PLAN",
]
_ROUTES = [
    "KNOWN_CHANNEL", "PARTNER", "PROCUREMENT_PORTAL", "BUYER_CONTACT_ROUTE",
    "INDUSTRY_EVENT", "PUBLIC_TENDER",
]


DISCOVERY_CRITERIA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Client discovery criteria",
    "type": "object",
    "additionalProperties": False,
    "required": ["relevant_problem", "our_capability"],
    "properties": {
        "target_country": {"type": ["string", "null"]},
        "target_region": {"type": ["string", "null"]},
        "target_industry": {"type": ["string", "null"]},
        "relevant_problem": {"type": "string", "minLength": 1},
        "problem_severity_signal": {"type": ["string", "null"]},
        "required_buyer_type": {"type": ["string", "null"]},
        "possible_decision_maker": {"type": ["string", "null"]},
        "our_capability": {"type": "string", "minLength": 1},
        "our_solution": {"type": ["string", "null"]},
        "required_solution_fit": {"type": ["string", "null"]},
        "purchase_signal": {"type": "array", "items": {"type": "string", "enum": _SIGNALS}},
        "budget_signal": {"type": ["string", "null"]},
        "procurement_signal": {"type": ["string", "null"]},
        "access_signal": {"type": "array", "items": {"type": "string", "enum": _ROUTES}},
        "channel_signal": {"type": ["string", "null"]},
        "partner_signal": {"type": ["string", "null"]},
        "competitive_condition": {"type": ["string", "null"]},
        "exclusion_condition": {"type": "array", "items": {"type": "string"}},
        "required_evidence": {"type": "array", "items": {"type": "string"}},
    },
}


ORGANIZATION_MENTIONS: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Organization mentions",
    "type": "object",
    "additionalProperties": False,
    "required": ["mentions"],
    "properties": {
        "mentions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "evidence_ref"],
                "properties": {
                    "name": {
                        "type": "string",
                        "minLength": 2,
                        "description": "Exactly as it is written in the cited passage. The name is checked against that passage and discarded if it is not there.",
                    },
                    "evidence_ref": {**_REF, "description": "The passage the name appears in, e.g. E2."},
                },
            },
        },
        "hypotheses": {
            "type": "array",
            "description": "Types of organization worth looking for. Never a particular company - there is no field for a name, because a named client must come from evidence.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["organization_profile"],
                "properties": {
                    "organization_profile": {"type": "string", "minLength": 1},
                    "rationale": {"type": ["string", "null"]},
                    "required_evidence": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}


FIT_ASSESSMENT: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Client fit assessment",
    "type": "object",
    "additionalProperties": False,
    "required": ["assessments"],
    "properties": {
        "discovery_rationale": {
            "type": ["string", "null"],
            "maxLength": 500,
            "description": "What of ours can be sold to which problem of theirs.",
        },
        "assessments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["criterion", "level"],
                "properties": {
                    "criterion": {"type": "string", "enum": _CRITERIA},
                    "level": {
                        "type": "string",
                        "enum": _LEVELS,
                        "description": "STRONG always means favourable for business development. Strong competition is WEAK.",
                    },
                    "reason": {"type": ["string", "null"], "maxLength": 500},
                    "evidence_refs": {"type": "array", "items": _REF},
                    "missing_evidence": {"type": "array", "items": {"type": "string"}},
                    "signal_type": {
                        "type": ["string", "null"],
                        "enum": _SIGNALS + [None],
                        "description": "PURCHASING_POTENTIAL only. Company size, fame and sector are not signals.",
                    },
                    "access_route": {
                        "type": ["string", "null"],
                        "enum": _ROUTES + [None],
                        "description": "ACCESSIBILITY only. Having a website is not a route.",
                    },
                },
            },
        },
    },
}


ALL_OUTPUT_SCHEMAS = {
    "DISCOVERY_CRITERIA": DISCOVERY_CRITERIA,
    "ORGANIZATION_MENTIONS": ORGANIZATION_MENTIONS,
    "FIT_ASSESSMENT": FIT_ASSESSMENT,
}
