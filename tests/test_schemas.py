# -*- coding: utf-8 -*-
"""The JSON Schemas and the dataclasses must not drift apart.

``core/models.py`` is what Python code uses; ``schemas/*.schema.json`` is what everything else
uses — another language's client, an organisation's own system, a validation step in a pipeline.
If the two disagree, one set of consumers is silently working against a contract that no longer
holds. These tests make that impossible to merge.
"""
from __future__ import annotations

import dataclasses
import enum
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from core import models
from core.models import ENTITIES, as_dict

#: Entity class name -> schema file stem.
SCHEMA_FOR_ENTITY = {
    "Project": "project",
    "SourceMetadata": "source_metadata",
    "ResearchFinding": "research_finding",
    "SWOTIssue": "swot_issue",
    "KeyIssue": "key_issue",
    "ClientCandidate": "client_candidate",
    "ClientAnalysis": "client_analysis",
    "ProposalStrategy": "proposal_strategy",
    "PricingResult": "pricing_result",
}


def _python_enum_classes() -> list[type[enum.Enum]]:
    return [
        obj
        for obj in vars(models).values()
        if isinstance(obj, type) and issubclass(obj, enum.Enum) and obj is not enum.Enum
    ]


def _walk_enum_lists(node) -> list[list]:
    """Every ``enum`` array anywhere in a schema."""
    found: list[list] = []
    if isinstance(node, dict):
        if isinstance(node.get("enum"), list):
            found.append(node["enum"])
        for value in node.values():
            found.extend(_walk_enum_lists(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_walk_enum_lists(value))
    return found


def test_every_entity_has_a_schema(schemas: dict) -> None:
    expected = {SCHEMA_FOR_ENTITY[e.__name__] for e in ENTITIES}
    assert expected == set(schemas), (
        f"schemas present: {sorted(schemas)}; entities expect: {sorted(expected)}"
    )


@pytest.mark.parametrize("entity", ENTITIES, ids=lambda e: e.__name__)
def test_schema_is_itself_valid(entity, schemas: dict) -> None:
    Draft202012Validator.check_schema(schemas[SCHEMA_FOR_ENTITY[entity.__name__]])


@pytest.mark.parametrize("entity", ENTITIES, ids=lambda e: e.__name__)
def test_schema_fields_match_dataclass_fields(entity, schemas: dict) -> None:
    schema = schemas[SCHEMA_FOR_ENTITY[entity.__name__]]
    in_code = {f.name for f in dataclasses.fields(entity)}
    in_schema = set(schema["properties"])

    assert in_code == in_schema, (
        f"{entity.__name__} has drifted from its schema. "
        f"Only in core/models.py: {sorted(in_code - in_schema)}. "
        f"Only in the schema: {sorted(in_schema - in_code)}. "
        "Update both, plus docs/data-model.md."
    )


@pytest.mark.parametrize("entity", ENTITIES, ids=lambda e: e.__name__)
def test_required_fields_exist_in_properties(entity, schemas: dict) -> None:
    schema = schemas[SCHEMA_FOR_ENTITY[entity.__name__]]
    unknown = [r for r in schema.get("required", []) if r not in schema["properties"]]
    assert not unknown, f"{entity.__name__} requires undeclared fields: {unknown}"


@pytest.mark.parametrize("name", sorted(SCHEMA_FOR_ENTITY.values()))
def test_schema_root_forbids_extra_fields(name: str, schemas: dict) -> None:
    """A closed root is a privacy control, not a style choice.

    ``additionalProperties: false`` is what stops a well-meaning adapter from attaching a
    filename or a block of document text to a record — see docs/privacy.md.
    """
    assert schemas[name].get("additionalProperties") is False, (
        f"{name}.schema.json must set additionalProperties to false"
    )


def test_schema_enums_match_python_enums(schemas: dict) -> None:
    """Every enum list in every schema must correspond exactly to a Python enum.

    A schema that has fallen one member behind still validates most data, which is precisely
    what makes the drift dangerous.
    """
    known = {frozenset(m.value for m in cls): cls.__name__ for cls in _python_enum_classes()}
    problems: list[str] = []

    for name, schema in schemas.items():
        for values in _walk_enum_lists(schema):
            concrete = frozenset(v for v in values if v is not None)
            if concrete not in known:
                problems.append(f"{name}: {sorted(concrete)}")

    assert not problems, (
        "these schema enum lists match no enum in core/models.py: "
        f"{problems}. Either a member was added on one side only, or a new enum needs "
        "defining in core/models.py."
    )


@pytest.mark.parametrize("entity", ENTITIES, ids=lambda e: e.__name__)
def test_default_instance_validates(entity, schemas: dict) -> None:
    """A minimally-constructed entity must satisfy its own schema."""
    minimal = {
        "Project": dict(company_name="Fictional Co"),
        "SourceMetadata": dict(
            project_id="prj_1",
            source_origin=models.SourceOrigin.UPLOADED_FILE,
            source_category=models.SourceCategory.COMPANY_DATA,
            file_type=models.FileType.PDF,
            file_size=1024,
        ),
        "ResearchFinding": dict(
            project_id="prj_1",
            finding="a statement",
            evidence_type=models.EvidenceType.ASSUMPTION,
            mn_basis=["MN02"],
        ),
        "SWOTIssue": dict(
            project_id="prj_1",
            category=models.SWOTCategory.STRENGTH,
            statement="a strength",
            finding_ids=["fnd_1"],
        ),
        "KeyIssue": dict(
            project_id="prj_1",
            statement="which market do we approach first",
            decision_area="market_priority",
            swot_issue_ids=["swt_1"],
            strategic_implication=(
                "the evidence points one way but purchasing authority is unverified, "
                "so it needs establishing first"
            ),
        ),
        "ClientCandidate": dict(
            project_id="prj_1",
            client_name="Fictional Buyer",
            country="KR",
            industry="manufacturing",
            discovery_rationale="their problem matches our capability",
            source_ids=["src_1"],
            finding_ids=["fnd_1"],
            fit=[
                models.FitAssessment(criterion=criterion)
                for criterion in models.FitCriterion
            ],
        ),
        "ClientAnalysis": dict(
            project_id="prj_1",
            client_id="cli_1",
            client_name="Fictional Buyer",
            country="KR",
            industry="manufacturing",
            missing_evidence=["budget cycle"],
        ),
        "ProposalStrategy": dict(
            project_id="prj_1",
            client_id="cli_1",
            client_name="Fictional Buyer",
            country="KR",
        ),
        "PricingResult": dict(project_id="prj_1", client_id="cli_1"),
    }[entity.__name__]

    instance = as_dict(entity(**minimal))
    Draft202012Validator(schemas[SCHEMA_FOR_ENTITY[entity.__name__]]).validate(instance)


def test_sample_project_files_validate(repo_root: Path, schemas: dict) -> None:
    """The published example must validate, or it teaches the wrong shape."""
    sample_dir = repo_root / "examples" / "sample_project"
    files = sorted(sample_dir.glob("*.json"))
    assert files, "examples/sample_project/ has no JSON files"

    # Each file is named after the schema it must satisfy, and may hold one record or a list.
    for path in files:
        assert path.stem in schemas, (
            f"{path.name}: example files are named after their schema; "
            f"known schemas are {sorted(schemas)}"
        )
        with path.open(encoding="utf-8") as fh:
            payload = json.load(fh)

        validator = Draft202012Validator(schemas[path.stem])
        records = payload if isinstance(payload, list) else [payload]
        for record in records:
            validator.validate(record)


# -- schemas the model is asked to fill ------------------------------------

def test_llm_output_schemas_are_valid() -> None:
    """The reduced schemas handed to a provider are schemas too, and can be wrong."""
    from core.research.output_schemas import ALL_OUTPUT_SCHEMAS

    for name, schema in ALL_OUTPUT_SCHEMAS.items():
        Draft202012Validator.check_schema(schema)
        assert schema.get("additionalProperties") is False, f"{name} root must be closed"


def test_llm_output_enums_are_subsets_of_the_real_enums() -> None:
    """A model's options must be drawn from the entity enums, never invented alongside them.

    Subset rather than equality on purpose: FINDING_BATCH deliberately omits INFERENCE, because
    pass 1 has no findings to reason from and the wrong answer should be unrepresentable.
    """
    from core.research.output_schemas import ALL_OUTPUT_SCHEMAS

    known = [frozenset(m.value for m in cls) for cls in _python_enum_classes()]
    problems: list[str] = []

    for name, schema in ALL_OUTPUT_SCHEMAS.items():
        for values in _walk_enum_lists(schema):
            concrete = frozenset(v for v in values if v is not None)
            if not any(concrete <= members for members in known):
                problems.append(f"{name}: {sorted(concrete)}")

    assert not problems, f"these output-schema enums match no entity enum: {problems}"


def test_the_model_is_never_asked_for_a_field_the_pipeline_owns() -> None:
    """Identifiers, framework ids, sources and timestamps are known already.

    Asking for them invites invention: EchoLLM filling the full finding schema produces
    mn_basis=["[echo] mn_basis[0]"], a framework id that does not exist.
    """
    from core.research.output_schemas import ALL_OUTPUT_SCHEMAS

    owned = {
        "finding_id", "issue_id", "key_issue_id", "project_id", "mn_basis", "source_id",
        "source_type", "source_date", "page_or_section", "created_at", "schema_version",
        "market_scope", "lang", "supporting_finding_ids", "finding_ids", "swot_issue_ids",
    }
    leaked: list[str] = []

    def walk(node, path=""):
        if isinstance(node, dict):
            for key, value in (node.get("properties") or {}).items():
                if key in owned:
                    leaked.append(f"{path}.{key}")
                walk(value, f"{path}.{key}")
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value, path)
        elif isinstance(node, list):
            for value in node:
                walk(value, path)

    for name, schema in ALL_OUTPUT_SCHEMAS.items():
        walk(schema, name)

    assert not leaked, f"the model is being asked for pipeline-owned fields: {sorted(set(leaked))}"
