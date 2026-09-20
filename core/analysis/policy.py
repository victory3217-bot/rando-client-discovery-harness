# -*- coding: utf-8 -*-
"""Analysis policy and prompt text. Pure configuration, injected by the caller."""
from __future__ import annotations

from dataclasses import dataclass

from core.research.policy import DEFAULT_RESEARCH_POLICY, SNIPPET_LOCATOR, ResearchPolicy


@dataclass(frozen=True)
class AnalysisPolicy:
    """Limits for one deep-analysis run.

    Batching and snippet handling come from the research policy rather than being restated:
    the same passages are being sent, so the same character budget applies.
    """

    research_policy: ResearchPolicy = DEFAULT_RESEARCH_POLICY

    snippet_locator: str = SNIPPET_LOCATOR

    #: How many clients one call may analyse. A **cost** limit, not a selection rule.
    #:
    #: Exceeding it refuses the whole request rather than analysing the first few. Silently
    #: taking a prefix would be the pipeline choosing which clients matter, which is the one
    #: decision this phase exists to leave with a person — and it would do it invisibly,
    #: looking exactly like a successful run.
    max_clients_per_run: int = 10

    #: Findings offered as context for one framework group.
    max_findings_per_group: int = 24

    #: Search queries the criteria stage may produce for one client. Zero disables the
    #: client-specific research stage entirely.
    max_queries_per_client: int = 6

    #: Results taken from each query.
    max_results_per_query: int = 5

    def __post_init__(self) -> None:
        if self.max_clients_per_run < 1:
            raise ValueError("max_clients_per_run must be at least 1")


DEFAULT_ANALYSIS_POLICY = AnalysisPolicy()


@dataclass
class AnalysisPromptSet:
    """Prompt text for each analysis stage, supplied by the caller.

    Two prompts, not one per dimension. The core does not read ``prompts/*.md``;
    ``adapters/prompts/loader.py`` does and passes the text in, exactly as for research and
    discovery.
    """

    research_criteria: str
    synthesize_claims: str
