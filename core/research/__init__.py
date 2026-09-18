# -*- coding: utf-8 -*-
"""Research and diagnosis — ENGINE 1.

Evidence → Finding → Master Note basis → SWOT → Key Issue → Strategic Implication, with no
shortcut at any link. Each stage takes the previous stage's output as an argument, so the order
is enforced by the type of thing each function accepts rather than by a rule in a document.

Pure, like the rest of ``core``: no file access, no environment, no network, no logging. The
LLM arrives as an injected provider and every call to it goes through
:mod:`core.research.transmission`, the single point at which document text leaves this process.

Prompts are passed in as text (:class:`~core.research.policy.PromptSet`). The core cannot read
``prompts/*.md`` itself, and inventing a provider interface to fetch three strings would be
more machinery than the problem deserves.
"""
from core.research.classify import classify_swot
from core.research.confidence import (
    ConfidenceSignals,
    cap,
    ceiling_for,
    reasons_for,
    weakest,
)
from core.research.extract import build_evidence_block, extract_findings, infer_findings
from core.research.models import (
    REJECTION_CODES,
    EvidenceBlock,
    EvidenceEntry,
    FlagCode,
    Rejection,
    RejectionCode,
    ResearchOutcome,
    ReviewFlag,
    safe_reference,
)
from core.research.output_schemas import (
    ALL_OUTPUT_SCHEMAS,
    FINDING_BATCH,
    INFERENCE_BATCH,
    KEY_ISSUE_BATCH,
    SWOT_BATCH,
)
from core.research.pipeline import persist, run_research
from core.research.policy import (
    DEFAULT_FRAMEWORKS,
    DEFAULT_RESEARCH_POLICY,
    SNIPPET_LOCATOR,
    PromptSet,
    ResearchPolicy,
    batch_candidates,
    batch_items,
)
from core.research.select import dimension_brief, frameworks_for, shortlist
from core.research.sources import (
    candidate_from_search_result,
    ingest_search_results,
    source_from_search_result,
)
from core.research.synthesize import derive_key_issues, looks_like_a_directive
from core.research.transmission import TransmissionRecord, send

__all__ = [
    "ALL_OUTPUT_SCHEMAS",
    "DEFAULT_FRAMEWORKS",
    "DEFAULT_RESEARCH_POLICY",
    "REJECTION_CODES",
    "SNIPPET_LOCATOR",
    "ConfidenceSignals",
    "FlagCode",
    "RejectionCode",
    "ReviewFlag",
    "EvidenceBlock",
    "EvidenceEntry",
    "FINDING_BATCH",
    "INFERENCE_BATCH",
    "KEY_ISSUE_BATCH",
    "PromptSet",
    "Rejection",
    "ResearchOutcome",
    "ResearchPolicy",
    "SWOT_BATCH",
    "TransmissionRecord",
    "batch_candidates",
    "batch_items",
    "build_evidence_block",
    "candidate_from_search_result",
    "cap",
    "ceiling_for",
    "classify_swot",
    "derive_key_issues",
    "dimension_brief",
    "extract_findings",
    "frameworks_for",
    "infer_findings",
    "ingest_search_results",
    "looks_like_a_directive",
    "persist",
    "reasons_for",
    "run_research",
    "send",
    "safe_reference",
    "shortlist",
    "source_from_search_result",
    "weakest",
]
