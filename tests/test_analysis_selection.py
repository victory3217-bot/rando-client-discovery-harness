# -*- coding: utf-8 -*-
"""A person chooses which clients get analysed, and the priority they were given survives it.

Two failures this guards against, both of which would look like a successful run.

The first is the pipeline picking clients itself — "top 3 deep analysis" is a natural thing to
implement and it takes the decision away silently. The second is a deep analysis rewriting the
band it was launched from, so the ordering a person reviewed is no longer the ordering they see.
"""
from __future__ import annotations

import ast
import copy
from pathlib import Path

import pytest

from adapters.llm.echo import EchoLLM
from adapters.prompts import load_analysis_prompt_set
from core.analysis import AnalysisPolicy, AnalysisRejectionCode, run_client_analysis
from core.models import (
    ClientCandidate,
    FitAssessment,
    FitCriterion,
    FitLevel,
    MarketScope,
    PriorityDecision,
    Project,
    SalesPriority,
)

ANALYSIS_DIR = Path(__file__).resolve().parent.parent / "core" / "analysis"


@pytest.fixture
def prompts(repo_root):
    return load_analysis_prompt_set(repo_root / "prompts")


def _candidate(client_id: str, band: SalesPriority = SalesPriority.P2) -> ClientCandidate:
    return ClientCandidate(
        project_id="prj_analysis",
        client_name=f"Fictional {client_id.upper()} Water Systems",
        country="VN",
        industry="water utilities",
        discovery_rationale="their problem matches our capability",
        source_ids=["src_1"],
        finding_ids=[],
        fit=[FitAssessment(criterion=c, level=FitLevel.UNKNOWN) for c in FitCriterion],
        priority=PriorityDecision(band=band),
        client_id=client_id,
    )


def _project() -> Project:
    return Project(
        project_id="prj_analysis",
        company_name="Fictional Sensing",
        market_scope=[MarketScope.DOMESTIC],
    )


def _run(client_ids, candidates, prompts, **kwargs):
    return run_client_analysis(
        project=_project(),
        client_ids=client_ids,
        candidates=candidates,
        findings=[],
        sources=[],
        our_solution="a single-module multi-parameter sensor",
        capability="multi-parameter measurement",
        llm=EchoLLM(),
        prompts=prompts,
        **kwargs,
    )


# -- the selection is the caller's ------------------------------------------

def test_client_ids_is_required() -> None:
    """No default, so there is no call that analyses whatever the pipeline felt like."""
    with pytest.raises(TypeError):
        run_client_analysis(  # type: ignore[call-arg]
            project=_project(),
            candidates=[],
            findings=[],
            sources=[],
            our_solution="s",
            capability="c",
            llm=EchoLLM(),
            prompts=None,
        )


def test_only_the_selected_clients_are_analysed(prompts) -> None:
    candidates = [_candidate("cli_a"), _candidate("cli_b"), _candidate("cli_c")]
    outcome = _run(["cli_b"], candidates, prompts)
    assert [a.client_id for a in outcome.analyses] == ["cli_b"]


def test_an_empty_selection_analyses_nobody(prompts) -> None:
    outcome = _run([], [_candidate("cli_a")], prompts)
    assert outcome.analyses == []
    assert outcome.transmissions == [], "and costs nothing"


def test_an_unknown_client_id_is_refused_not_skipped(prompts) -> None:
    outcome = _run(["cli_a", "cli_ghost"], [_candidate("cli_a")], prompts)
    assert [a.client_id for a in outcome.analyses] == ["cli_a"]
    assert any(r.code == AnalysisRejectionCode.UNKNOWN_CLIENT_ID for r in outcome.rejections)


def test_too_many_clients_refuses_the_whole_request(prompts) -> None:
    """Not the first N.

    Silently taking a prefix would be the pipeline choosing which clients matter, and it would
    do it invisibly — the run would look like it succeeded.
    """
    candidates = [_candidate(f"cli_{i}") for i in range(4)]
    outcome = _run(
        [c.client_id for c in candidates], candidates, prompts,
        policy=AnalysisPolicy(max_clients_per_run=2),
    )
    assert outcome.analyses == []
    assert any(r.code == AnalysisRejectionCode.TOO_MANY_CLIENTS for r in outcome.rejections)


def test_selection_order_is_the_caller_s_not_the_band_s(prompts) -> None:
    candidates = [
        _candidate("cli_low", SalesPriority.P3),
        _candidate("cli_high", SalesPriority.P1),
    ]
    outcome = _run(["cli_low", "cli_high"], candidates, prompts)
    assert [a.client_id for a in outcome.analyses] == ["cli_low", "cli_high"]


# -- nothing here ranks -----------------------------------------------------

def _analysis_sources() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(ANALYSIS_DIR.rglob("*.py"))}


def test_no_module_decides_a_priority() -> None:
    """Checked against the code, because a rule in a document is not a rule."""
    for name, source in _analysis_sources().items():
        tree = ast.parse(source)
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        } | {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert "decide_priority" not in called, f"{name} decides a priority"
        assert "PriorityDecision" not in called, f"{name} builds a priority"


def test_no_module_sorts_or_ranks_candidates() -> None:
    banned = ("priority", "band", "rank", "top_n", "best_candidate", "highest")
    for name, source in _analysis_sources().items():
        lowered = source.lower()
        for token in ("sorted(", "max(", "min("):
            index = lowered.find(token)
            while index >= 0:
                window = lowered[index : index + 120]
                assert not any(b in window for b in banned), (
                    f"{name} appears to order clients by {token}: {window[:80]}"
                )
                index = lowered.find(token, index + 1)


def test_no_module_imports_the_priority_rule_table() -> None:
    for name, source in _analysis_sources().items():
        assert "core.client.priority" not in source, f"{name} imports the priority table"


# -- the band that was reviewed is the band that remains --------------------

def test_the_candidate_priority_is_untouched(prompts) -> None:
    candidate = _candidate("cli_a", SalesPriority.P1)
    before = copy.deepcopy(candidate.priority)

    outcome = _run(["cli_a"], [candidate], prompts)

    assert candidate.priority == before
    assert candidate.priority.band is SalesPriority.P1
    assert outcome.analyses, "and the analysis still happened"


def test_the_analysis_carries_no_priority_of_its_own() -> None:
    """A second band would give one client two answers with nothing to say which is current."""
    import dataclasses

    from core.models import ClientAnalysis

    names = {f.name for f in dataclasses.fields(ClientAnalysis)}
    assert "sales_priority" not in names
    assert not any("priority" in name or "band" in name or "rank" in name for name in names)
