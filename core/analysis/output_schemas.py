# -*- coding: utf-8 -*-
"""What the model is allowed to return during deep analysis.

Same principle as the research and discovery schemas: the model is asked only for what it can
know from the evidence in front of it, and never for a field the pipeline already owns.

What is **absent** here is the design:

* no ``evidence_type`` and no ``confidence`` — both are derived. A model asked how sure it is
  answers fluently and without information;
* no ``source_ids`` — sources are reached through the findings that were cited;
* no ``our_solution`` — that is an input. Asking a model what we sell is asking it to invent
  a product, and it will;
* no ``priority`` of any kind — the band belongs to the candidate and to Phase 4.

``organization_name`` is separated from ``statement`` on purpose. A name in its own field can
be checked against the passage; a name buried in a sentence cannot be, without building the
entity recognition this harness has decided not to build.
"""
from __future__ import annotations

from core.analysis.dimensions import DIMENSION_FRAMEWORK, dimensions_for
from core.models import AccessRoute, AnalysisDimension, InternationalDimension, MAX_CLAIM_STATEMENT_CHARS

_REF = {"type": "string", "minLength": 1}

_ROUTES = [route.value for route in AccessRoute]


CLIENT_RESEARCH_CRITERIA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Client research criteria",
    "type": "object",
    "additionalProperties": False,
    "required": ["queries"],
    "properties": {
        "queries": {
            "type": "array",
            "description": (
                "What to look up about this organization. Search terms, not questions for "
                "yourself to answer - anything you already believe about this company without "
                "a document behind it is not usable here."
            ),
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "minLength": 1, "maxLength": 200},
                    "target_dimension": {
                        "type": ["string", "null"],
                        "enum": [d.value for d in AnalysisDimension] + [None],
                    },
                },
            },
        },
    },
}


def claim_batch_schema(framework_id: str) -> dict:
    """The output schema for one framework group.

    Built per group rather than as one nineteen-item schema, because a schema that lists every
    dimension invites answers for dimensions this group was not asked about — and the model is
    then guessing outside the evidence it was given.
    """
    dimensions = [d.value for d in dimensions_for(framework_id)]
    claim: dict = {
        "type": "object",
        "additionalProperties": False,
        "required": ["dimension"],
        "properties": {
            "dimension": {"type": "string", "enum": dimensions},
            "statement": {
                "type": ["string", "null"],
                "maxLength": MAX_CLAIM_STATEMENT_CHARS,
                "description": (
                    "An interpretation in your own words, not a copy of the passage. Leave it "
                    "null when the evidence does not settle this question."
                ),
            },
            "evidence_refs": {"type": "array", "items": _REF},
            "missing_evidence": {"type": "array", "items": {"type": "string"}},
        },
    }

    if framework_id == "MN04":
        claim["properties"]["organization_name"] = {
            "type": ["string", "null"],
            "description": (
                "Exactly as the cited passage writes it. Checked against that passage and "
                "discarded if it is not there. Do not put any other organization's name in "
                "the statement."
            ),
        }
    if framework_id == "MN05":
        claim["properties"]["organization_name"] = {
            "type": ["string", "null"],
            "description": "PARTNER only, exactly as the cited passage writes it.",
        }
        claim["properties"]["access_route"] = {
            "type": ["string", "null"],
            "enum": _ROUTES + [None],
            "description": (
                "SALES_ACCESS_ROUTE only. Having a website is not a route; being a public "
                "body is not a route."
            ),
        }

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"Client analysis claims ({framework_id})",
        "type": "object",
        "additionalProperties": False,
        "required": ["claims"],
        "properties": {"claims": {"type": "array", "items": claim}},
    }


INTERNATIONAL_CLAIMS: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "International client analysis claims",
    "type": "object",
    "additionalProperties": False,
    "required": ["claims"],
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["dimension"],
                "properties": {
                    "dimension": {
                        "type": "string",
                        "enum": [d.value for d in InternationalDimension],
                    },
                    "statement": {
                        "type": ["string", "null"],
                        "maxLength": MAX_CLAIM_STATEMENT_CHARS,
                    },
                    "evidence_refs": {"type": "array", "items": _REF},
                    "missing_evidence": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}


ALL_OUTPUT_SCHEMAS = {
    "CLIENT_RESEARCH_CRITERIA": CLIENT_RESEARCH_CRITERIA,
    "INTERNATIONAL_CLAIMS": INTERNATIONAL_CLAIMS,
    **{f"CLAIMS_{fid}": claim_batch_schema(fid) for fid in sorted(set(DIMENSION_FRAMEWORK.values()))},
}
