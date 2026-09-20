# -*- coding: utf-8 -*-
"""The only place the proof touches the harness. Minimal on purpose.

What this proves is not that the pipelines work — 995 tests already do that. It proves the
three things Phase 8's architecture rests on and that no test could check from inside the
harness:

1. the harness imports and assembles from **outside** it, through ``create_harness``;
2. uploaded bytes reach ``IntakeSession`` and become evidence candidates **without touching
   a disk**, inside a web request;
3. the core runs a real pipeline with no idea that a web framework exists.

Everything offline: ``EchoLLM``, ``MemoryStorage``, ``ManualSearch``, ``StaticKnowledge``.
No credential, no network, no real provider. The discovery leg is deliberately not run —
``run_research`` alone is enough to prove the integration, and the runtime spike already
measured what a full Bootstrap costs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from proof_app.config import HARNESS_ROOT
from proof_app.runs import BootstrapStatus, RunOutcome


@dataclass(frozen=True)
class UploadedPart:
    """One uploaded file, as bytes. **No filename field, by construction.**

    The harness's own parsers have no ``filename`` parameter so an original filename cannot
    structurally reach them (``docs/privacy.md`` section 3). The proof keeps that property on
    its side of the boundary: what crosses into ``run_bootstrap`` is bytes and a declared
    type, and the browser's filename is dropped at the route.
    """

    data: bytes
    file_type: str


class CountingEcho:
    """``EchoLLM`` with a call counter, so the proof can report provider calls like the spike."""

    def __init__(self) -> None:
        from adapters.llm.echo import EchoLLM

        self._inner = EchoLLM()
        self.name = self._inner.name
        self.calls = 0

    def _count(self, fn, *a, **k):
        self.calls += 1
        return fn(*a, **k)

    def generate(self, *a, **k):
        return self._count(self._inner.generate, *a, **k)

    def generate_structured(self, *a, **k):
        return self._count(self._inner.generate_structured, *a, **k)

    def analyze(self, *a, **k):
        return self._count(self._inner.analyze, *a, **k)

    def summarize(self, *a, **k):
        return self._count(self._inner.summarize, *a, **k)


def build_harness():
    """Assemble the harness the way an application layer does: four providers, injected."""
    from adapters.knowledge.static import StaticKnowledge
    from adapters.search.manual import ManualSearch
    from adapters.storage.memory import MemoryStorage
    from core.harness import create_harness

    return create_harness(
        storage=MemoryStorage(),
        knowledge=StaticKnowledge.from_directory(HARNESS_ROOT / "knowledge" / "master-notes"),
        llm=CountingEcho(),
        search=ManualSearch(),
    )


def run_bootstrap(
    parts: list[UploadedPart],
    report: Callable[[BootstrapStatus], None],
    *,
    fail_discovery: bool = False,
) -> RunOutcome:
    """Intake → research, then a discovery leg the proof can be told to fail.

    ``fail_discovery`` exists so the partial-failure path is exercised for real rather than
    asserted in prose: research completes and its results are kept, discovery does not, and
    the run ends in ``DISCOVERY_FAILED_REUPLOAD_REQUIRED``.

    Runs on a worker thread. It returns counts and nothing else — no text leaves this
    function, so nothing downstream can log or render any.
    """
    from adapters.intake import IntakeSession
    from core.intake import IntakePolicy
    from core.models import FileType, MarketScope, SourceCategory
    from core.research import persist as persist_research
    from core.research import run_research

    harness = build_harness()
    project = harness.create_project(
        "Fictional Sensor Works",
        market_scope=[MarketScope.INTERNATIONAL],
        target_countries=["VN"],
        target_industries=["water utilities"],
    )

    # -- the only moment document bytes exist, and they never reach a disk --
    candidates: list = []
    with IntakeSession(project.project_id, policy=IntakePolicy()) as intake:
        for part in parts:
            result = intake.ingest(
                bytearray(part.data),
                file_type=FileType(part.file_type),
                source_category=SourceCategory.EXTERNAL_BUSINESS_DATA,
                # No display_label: the browser's filename is dropped at the route and there
                # is nothing else to put here.
            )
            harness.storage.save_source_metadata(result.source)
            candidates.extend(result.candidates)

    candidate_count = len(candidates)

    from adapters.prompts import load_prompt_set

    try:
        outcome = run_research(
            project=project,
            candidates=candidates,
            sources=harness.storage.get_source_metadata(project.project_id),
            knowledge=harness.knowledge,
            llm=harness.llm,
            prompts=load_prompt_set(HARNESS_ROOT / "prompts"),
            today="2026-09-20",
        )
        persist_research(outcome, harness.storage)
    except Exception:  # noqa: BLE001 — a code, never the message
        candidates.clear()
        return RunOutcome(
            status=BootstrapStatus.RESEARCH_FAILED,
            error_code="RESEARCH_FAILED",
            candidate_count=candidate_count,
            llm_calls=harness.llm.calls,
        )

    report(BootstrapStatus.RESEARCH_COMPLETED)
    finding_count = len(harness.storage.get_findings(project.project_id))

    # -- discovery leg -----------------------------------------------------
    report(BootstrapStatus.RUNNING_DISCOVERY)
    if fail_discovery:
        # The candidates die here exactly as they would on success. That is why discovery
        # cannot simply be retried: what it reads no longer exists anywhere.
        candidates.clear()
        harness.storage.clear()
        return RunOutcome(
            status=BootstrapStatus.DISCOVERY_FAILED_REUPLOAD_REQUIRED,
            error_code="DISCOVERY_FAILED",
            candidate_count=candidate_count,
            finding_count=finding_count,
            llm_calls=harness.llm.calls,
        )

    calls = harness.llm.calls
    candidates.clear()
    harness.storage.clear()
    return RunOutcome(
        status=BootstrapStatus.COMPLETED,
        candidate_count=candidate_count,
        finding_count=finding_count,
        llm_calls=calls,
    )


def harness_facts() -> dict:
    """Counts the home page shows to prove the import worked. No text from any document."""
    from core.harness import CLIENT_ANALYSIS_FRAMEWORKS, RESEARCH_FRAMEWORKS
    from core.models import ENTITIES

    harness = build_harness()
    return {
        "entities": len(ENTITIES),
        "research_frameworks": len(RESEARCH_FRAMEWORKS),
        "analysis_frameworks": len(CLIENT_ANALYSIS_FRAMEWORKS),
        "storage_adapter": harness.storage.name,
        "llm_adapter": harness.llm.name,
        "search_adapter": harness.search.name,
        "knowledge_adapter": harness.knowledge.name,
    }
