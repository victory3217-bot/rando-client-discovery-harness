# -*- coding: utf-8 -*-
"""Research policy: how much evidence goes into one call, and which frameworks run.

A frozen dataclass, not configuration the core reads. The core never looks at an environment
variable; an application that wants different limits builds its own policy and injects it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

#: Frameworks used for company-level research and diagnosis, mirroring
#: :data:`core.harness.RESEARCH_FRAMEWORKS`. Repeated here so that a policy is self-contained.
DEFAULT_FRAMEWORKS: tuple[str, ...] = ("MN02", "MN03", "MN04", "MN05", "MN06", "MN07")

#: Locator used for evidence taken from a search result.
#:
#: A snippet is a search engine's extract, not the document. Nothing in this harness has
#: read the page it came from, so a finding resting on one cannot reach HIGH confidence —
#: see core/research/confidence.py.
SNIPPET_LOCATOR = "snippet"


@dataclass(frozen=True)
class ResearchPolicy:
    """Limits and switches for one research run.

    The batch limits are deliberately conservative and are expressed in **characters, not
    tokens**. Counting tokens would mean the core knowing a provider's tokenizer, which is the
    dependency this architecture exists to avoid. Characters are a crude proxy; the defaults
    leave enough headroom that the crudeness does not matter.

    ``max_evidence_chars_per_batch = 24000`` sits far below any current model's context window
    on purpose. The limit that bites first is not the window but attention: a model given sixty
    passages at once reliably produces shallower readings of each than one given twelve. The
    number is a starting point to be tuned against real output, not a measured optimum.
    """

    #: Evidence passages in one extraction call.
    max_candidates_per_batch: int = 12

    #: Total characters of evidence text in one extraction call.
    max_evidence_chars_per_batch: int = 24_000

    #: Longest single passage passed through. Longer ones are truncated, with a marker, rather
    #: than dropped: a long table still says something, and silently losing it is worse.
    max_chars_per_candidate: int = 4_000

    #: Findings passed into one SWOT or key-issue call.
    max_findings_per_batch: int = 40

    #: Frameworks to run, in order. The default runs all six against every batch.
    frameworks: tuple[str, ...] = DEFAULT_FRAMEWORKS

    #: Optional keyword shortlist, off by default.
    #:
    #: Off because narrowing the frameworks is a judgement about what the evidence is *about*,
    #: and making that judgement from keyword overlap is exactly the kind of quiet automation
    #: this harness avoids. Turning it on trades coverage for cost, and the pipeline records
    #: which frameworks were skipped and why.
    use_keyword_shortlist: bool = False

    #: A source older than this cannot support HIGH confidence. Five years is arbitrary but
    #: defensible for market and competitive material; regulatory material ages faster.
    stale_source_years: int = 5

    #: Independent sources needed before a FACT may be HIGH. See core/research/confidence.py.
    corroboration_for_high: int = 2

    #: Languages the pipeline may be asked to produce. Only used to reject typos early.
    allowed_output_langs: tuple[str, ...] = ("ko", "en")


DEFAULT_RESEARCH_POLICY = ResearchPolicy()


@dataclass
class PromptSet:
    """The prompt text for each stage, supplied by the caller.

    The core does not read ``prompts/*.md`` — it may not touch the filesystem. An application
    loads the files (``adapters/prompts/loader.py`` does it in three lines) and passes the text
    in. That keeps prompts out of the code without inventing a provider framework to fetch
    them.
    """

    extract_findings: str
    classify_swot: str
    derive_key_issues: str
    infer_findings: Optional[str] = None

    def for_stage(self, stage: str) -> str:
        if stage == "infer_findings" and self.infer_findings is None:
            # Inference reuses the extraction prompt's rules when no separate file is supplied.
            return self.extract_findings
        return getattr(self, stage)


def batch_candidates(
    candidates: Sequence,
    policy: ResearchPolicy = DEFAULT_RESEARCH_POLICY,
) -> list[list]:
    """Split candidates into batches that respect both the count and the character limit.

    Order is preserved, so a document's passages stay adjacent and a run is reproducible.
    """
    batches: list[list] = []
    current: list = []
    current_chars = 0

    for candidate in candidates:
        size = min(len(candidate.text), policy.max_chars_per_candidate)
        too_many = len(current) >= policy.max_candidates_per_batch
        too_long = current and current_chars + size > policy.max_evidence_chars_per_batch
        if too_many or too_long:
            batches.append(current)
            current, current_chars = [], 0
        current.append(candidate)
        current_chars += size

    if current:
        batches.append(current)
    return batches


def batch_items(items: Sequence, size: int) -> list[list]:
    """Fixed-size batching for findings and SWOT items."""
    if size <= 0:
        return [list(items)] if items else []
    return [list(items[i : i + size]) for i in range(0, len(items), size)]
