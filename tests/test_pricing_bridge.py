# -*- coding: utf-8 -*-
"""The pricing case end to end: assemble, store, hand over, take the answer back.

The loop this file exercises is the whole of Phase 7 —

    strategy + cost sheet  →  PricingResult  →  a JSON file on disk
                           →  (another process, another repository)
                           →  analysis_result  →  attach_engine_result

— and the two places it must not close are the ones the tests press on: the file does not get
written while a prerequisite is open, and the two repositories never meet in one interpreter.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

from adapters.pricing.file import FilePricingBridge
from adapters.storage.memory import MemoryStorage
from adapters.storage.null import NullStorage
from core.errors import PricingHandoffBlocked
from core.evidence import check_pricing_result
from core.models import PricingResult, PricingStatus, as_dict, from_dict
from core.pricing_bridge import (
    PricingFlagCode,
    attach_engine_result,
    persist,
    run_pricing_handoff,
)
from pricing_fixtures import (
    BUDGET_GAP,
    budget_gap_ref,
    build_analysis,
    build_commercial,
    build_strategy,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
PRICING_HARNESS = REPO_ROOT.parent / "pricing-harness-public"
ANALYSIS_RESULT_SCHEMA = PRICING_HARNESS / "core" / "schemas" / "analysis_result.schema.json"
GENERATED_RESULTS = PRICING_HARNESS / "core" / "schemas" / "examples" / "analysis_results"


def _ready() -> PricingResult:
    outcome = run_pricing_handoff(
        analysis=build_analysis(),
        strategy=build_strategy(),
        commercial=build_commercial(),
        acknowledged_gap_refs=[budget_gap_ref()],
    )
    assert not outcome.rejections, outcome.rejections
    return outcome.results[0]


def _blocked() -> PricingResult:
    outcome = run_pricing_handoff(
        analysis=build_analysis(),
        strategy=build_strategy(),
        commercial=build_commercial(),
    )
    return outcome.results[0]


# -- Z: the record survives a round trip -------------------------------------------

def test_a_pricing_result_survives_serialisation() -> None:
    result = _ready()
    rebuilt = from_dict(PricingResult, json.loads(json.dumps(as_dict(result))))

    assert rebuilt == result
    assert rebuilt.status is PricingStatus.PAYLOAD_READY
    assert rebuilt.pricing_payload == result.pricing_payload
    assert rebuilt.commercial_context == result.commercial_context


def test_an_attached_result_survives_serialisation() -> None:
    result = _ready()
    document = {
        "schema_version": "1.1",
        "source": {
            "client_id": result.client_id,
            "case_id": result.pricing_case_id,
            "client_input_ref": "x.json",
            "engine_version": "0.4.0",
            "calculated_at": "2026-09-20T00:00:00+00:00",
        },
        "currency": {"reporting": "USD"},
    }
    attached, _ = attach_engine_result(result, document)
    rebuilt = from_dict(PricingResult, json.loads(json.dumps(as_dict(attached))))
    assert rebuilt.engine_result == document
    assert rebuilt.status is PricingStatus.COMPLETED


# -- the Evidence invariant ----------------------------------------------------------

def test_a_well_formed_case_satisfies_its_invariants() -> None:
    assert check_pricing_result(_ready()) == []
    assert check_pricing_result(_blocked()) == []


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda r: setattr(r, "strategy_id", ""), "strategy_id"),
        (lambda r: setattr(r, "analysis_id", ""), "analysis_id"),
        (lambda r: setattr(r, "pricing_case_id", ""), "pricing_case_id"),
        (lambda r: r.pricing_payload.__setitem__("case_id", "pcs_other"), "case_id"),
        (lambda r: r.pricing_payload.__setitem__("client_id", "cli_other"), "client"),
        (lambda r: r.pricing_payload.__setitem__("commercial_context", {}), "commercial_context"),
        (lambda r: setattr(r, "status", PricingStatus.COMPLETED), "engine_result"),
        (lambda r: setattr(r, "error_code", "BOOM"), "error_code"),
    ],
)
def test_a_broken_case_is_caught(mutate, expected: str) -> None:
    result = _ready()
    mutate(result)
    violations = check_pricing_result(result)
    assert any(expected in v for v in violations), violations


def test_a_payload_under_not_requested_is_caught() -> None:
    result = _ready()
    result.status = PricingStatus.NOT_REQUESTED
    assert any("nobody asked" in v for v in check_pricing_result(result))


# -- storage -------------------------------------------------------------------------

def test_the_case_reaches_storage_and_comes_back() -> None:
    storage = MemoryStorage()
    outcome = run_pricing_handoff(
        analysis=build_analysis(),
        strategy=build_strategy(),
        commercial=build_commercial(),
        acknowledged_gap_refs=[budget_gap_ref()],
    )
    persist(outcome, storage)

    stored = storage.get_pricing_results(outcome.results[0].project_id)
    assert [r.pricing_case_id for r in stored] == [outcome.results[0].pricing_case_id]


def test_the_ephemeral_default_keeps_nothing() -> None:
    storage = NullStorage()
    outcome = run_pricing_handoff(
        analysis=build_analysis(),
        strategy=build_strategy(),
        commercial=build_commercial(),
        acknowledged_gap_refs=[budget_gap_ref()],
    )
    persist(outcome, storage)
    assert storage.get_pricing_results(outcome.results[0].project_id) == []


def test_a_refused_case_is_never_offered_to_storage() -> None:
    storage = MemoryStorage()
    outcome = run_pricing_handoff(
        analysis=build_analysis(),
        strategy=build_strategy(),
        commercial=build_commercial(contract_version=""),
    )
    persist(outcome, storage)
    assert outcome.rejections and storage.get_pricing_results("prj_pricing") == []


# -- the file contract -----------------------------------------------------------------

def test_a_blocked_case_cannot_be_written_out(tmp_path: Path) -> None:
    """Writing the file *is* the hand-off, so the gate has to bite here or it is only advice."""
    bridge = FilePricingBridge()
    with pytest.raises(PricingHandoffBlocked):
        bridge.write_payload(_blocked(), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_a_ready_case_is_written_as_the_payload_and_nothing_else(tmp_path: Path) -> None:
    result = _ready()
    path = FilePricingBridge().write_payload(result, tmp_path)

    assert path.name == f"{result.pricing_case_id}.client_input.json"
    with path.open(encoding="utf-8") as fh:
        assert json.load(fh) == result.pricing_payload


def test_the_file_name_names_nothing_about_the_client(tmp_path: Path) -> None:
    """An opaque case id. A directory listing is a surface too (docs/privacy.md section 3)."""
    result = _ready()
    path = FilePricingBridge().write_payload(result, tmp_path)
    lowered = path.name.lower()
    for leak in ("alpha", "water", "sensor", "fictional", "vn"):
        assert leak not in lowered


def test_the_directory_is_required() -> None:
    import inspect

    signature = inspect.signature(FilePricingBridge.write_payload)
    assert signature.parameters["directory"].default is inspect.Parameter.empty


def test_the_full_loop_closes(tmp_path: Path) -> None:
    """Assemble, write, let another process answer, read it back, attach."""
    bridge = FilePricingBridge()
    result = _ready()
    written = bridge.write_payload(result, tmp_path)

    # Standing in for the pricing harness, which runs in its own process.
    sent = json.loads(written.read_text(encoding="utf-8"))
    answer = {
        "schema_version": "1.1",
        "source": {
            "client_id": sent["client_id"],
            "case_id": sent["case_id"],
            "client_input_ref": written.name,
            "engine_version": "0.4.0",
            "calculated_at": "2026-09-20T00:00:00+00:00",
        },
        "currency": {"reporting": sent["fx"]["reporting_currency"]},
        "mode_a": {"status": "OK"},
    }
    answer_path = tmp_path / "answer.json"
    answer_path.write_text(json.dumps(answer, ensure_ascii=False), encoding="utf-8")

    loaded = bridge.read_engine_result(answer_path)
    attached, rejections = attach_engine_result(result, loaded)

    assert not rejections
    assert attached.status is PricingStatus.COMPLETED
    assert check_pricing_result(attached) == []
    assert attached.engine_result == answer


@pytest.mark.skipif(
    not GENERATED_RESULTS.is_dir() or not ANALYSIS_RESULT_SCHEMA.is_file(),
    reason="pricing-harness-public is not checked out next to this repository",
)
def test_a_real_engine_result_validates_and_attaches() -> None:
    """Against a document that harness actually generated, not one this test invented."""
    bridge = FilePricingBridge.from_repository(PRICING_HARNESS)
    sample = sorted(GENERATED_RESULTS.glob("*.json"))[0]
    document = bridge.read_engine_result(sample)

    verdict = bridge.validate_external_engine_result(document)
    assert verdict.checked and verdict.ok, verdict.errors[:3]

    result = _ready()
    document["source"]["case_id"] = result.pricing_case_id
    document["source"]["client_id"] = result.client_id
    attached, rejections = attach_engine_result(result, document)

    assert not rejections
    assert attached.status is PricingStatus.COMPLETED
    assert attached.engine_result["mode_a"] == document["mode_a"], "verbatim"


# -- AC: the two repositories never meet in one interpreter -------------------------

def test_the_pricing_harness_is_not_imported() -> None:
    """Both repositories use a top-level ``core``. In one process, one of them loses."""
    import core

    assert Path(core.__file__).resolve().parent == REPO_ROOT / "core"
    assert "core.engine" not in sys.modules
    assert not any(name.startswith("core.engine") for name in sys.modules)


@pytest.mark.parametrize(
    "path",
    sorted((REPO_ROOT / "core" / "pricing_bridge").rglob("*.py"))
    + sorted((REPO_ROOT / "adapters" / "pricing").rglob("*.py")),
    ids=lambda p: p.name,
)
def test_no_module_reaches_into_the_pricing_harness(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    banned = ("core.engine", "core.schemas")
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith(banned):
                offenders.append(f"line {node.lineno}: from {node.module}")
        if isinstance(node, ast.Import):
            offenders.extend(
                f"line {node.lineno}: import {a.name}"
                for a in node.names
                if a.name.startswith(banned)
            )
    assert not offenders, f"{path.name} imports the other harness: {offenders}"


# -- AE: Phase 9 can still render this -----------------------------------------------

def test_a_renderer_can_build_a_pricing_brief_without_reopening_anything() -> None:
    """The context is a structure to place, not a paragraph to parse."""
    context = _ready().commercial_context

    assert context["objective"] == "POC"
    assert [entry["ref"] for entry in context["offered"]] == ["S1", "S2"]

    for dimension in ("VALUE_DRIVER", "PRICE_SENSITIVITY", "BUDGET_EVIDENCE", "PROCUREMENT_CONTEXT"):
        claim = context["claims"][dimension]
        assert claim["established"] is True
        assert claim["statement"] and claim["finding_ids"]
        # Provenance travels with the sentence: a LOW-confidence reading has to read as one.
        assert claim["evidence_type"] and claim["confidence"]

    assert [need["timing"] for need in context["evidence_needs"]] == ["BEFORE_PRICING"]


def test_an_unestablished_commercial_claim_says_so_rather_than_disappearing() -> None:
    from core.models import AnalysisDimension as Dim

    settled = tuple(d for d in Dim if d is not Dim.PRICE_SENSITIVITY)
    outcome = run_pricing_handoff(
        analysis=build_analysis(settled=settled),
        strategy=build_strategy(),
        commercial=build_commercial(),
        acknowledged_gap_refs=[budget_gap_ref()],
    )
    claim = outcome.results[0].commercial_context["claims"]["PRICE_SENSITIVITY"]
    assert claim["established"] is False
    assert claim["missing_evidence"], "the gap is named, not silently omitted"
    assert "statement" not in claim


# -- the gap round trip a Phase 8 UI has to make ------------------------------------

def test_the_context_carries_both_halves_of_every_commercial_gap() -> None:
    """Display the sentence, round-trip the reference. A UI needs exactly these two."""
    blocked = _blocked()
    gaps = blocked.commercial_context["evidence_needs"]
    assert gaps

    for gap in gaps:
        assert set(gap) == {"gap_ref", "need", "timing", "dimension"}
        assert gap["gap_ref"].startswith("gap_")
        assert gap["need"], "the sentence is still there to show somebody"

    blocking = [g for g in gaps if g["timing"] == "BEFORE_PRICING"]
    assert len(blocking) == 1
    assert blocking[0]["need"] == BUDGET_GAP
    assert blocking[0]["dimension"] == "BUDGET_EVIDENCE"


def test_a_ui_can_go_from_blocked_to_handed_over_using_only_the_record(tmp_path: Path) -> None:
    """The whole Phase 8 loop, with nothing but what the record already carries.

    Read the gaps out of the stored case, show a person the ``need``, send back the
    ``gap_ref``. At no point does the caller need the analysis, the strategy object, or the
    wording of a gap as a key.
    """
    storage = MemoryStorage()
    first = run_pricing_handoff(
        analysis=build_analysis(), strategy=build_strategy(), commercial=build_commercial()
    )
    persist(first, storage)

    stored = storage.get_pricing_results(first.results[0].project_id)[0]
    assert stored.status is PricingStatus.HANDOFF_BLOCKED
    with pytest.raises(PricingHandoffBlocked):
        FilePricingBridge().write_payload(stored, tmp_path)

    # What the screen shows, and what it sends back.
    shown = [
        gap
        for gap in stored.commercial_context["evidence_needs"]
        if gap["timing"] == "BEFORE_PRICING"
    ]
    assert [gap["need"] for gap in shown] == [BUDGET_GAP]
    approved = [gap["gap_ref"] for gap in shown]

    second = run_pricing_handoff(
        analysis=build_analysis(),
        strategy=build_strategy(),
        commercial=build_commercial(),
        acknowledged_gap_refs=approved,
        pricing_case_id=stored.pricing_case_id,
    )
    released = second.results[0]

    assert released.status is PricingStatus.PAYLOAD_READY
    assert released.pricing_case_id == stored.pricing_case_id, "the same case, released"
    assert PricingFlagCode.GAPS_ACKNOWLEDGED in {f.code for f in second.review_flags}
    assert FilePricingBridge().write_payload(released, tmp_path).is_file()


def test_the_reference_survives_storage_and_serialisation() -> None:
    """A ref read back out of a stored record still opens the gate it was issued for."""
    stored = from_dict(PricingResult, json.loads(json.dumps(as_dict(_blocked()))))
    approved = [
        gap["gap_ref"]
        for gap in stored.commercial_context["evidence_needs"]
        if gap["timing"] == "BEFORE_PRICING"
    ]
    outcome = run_pricing_handoff(
        analysis=build_analysis(),
        strategy=build_strategy(),
        commercial=build_commercial(),
        acknowledged_gap_refs=approved,
    )
    assert outcome.results[0].status is PricingStatus.PAYLOAD_READY
