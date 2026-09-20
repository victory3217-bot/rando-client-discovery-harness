# -*- coding: utf-8 -*-
"""Deep analysis of a human-selected client — ENGINE 2, second half.

``core/client`` finds organizations worth approaching. This package takes the ones a person
picked and asks nineteen questions about each: who uses the thing, who buys it, who decides,
who holds the budget, what problem they actually have, what they do about it today, what they
compare suppliers on, who else is in the room, and how anyone would reach them.

Three properties shape the code.

**A person chooses.** ``run_client_analysis`` takes ``client_ids`` as a required argument. No
default, no ranking, no top-three. Nothing in this package reads or writes a priority band.

**A claim's evidence type comes from the question, not the answer.** Three facts joined into a
conclusion make an inference — see ``core/analysis/dimensions.py``.

**The research pipeline is Phase 3's.** Client-specific search goes through
``ingest_search_results`` and ``extract_findings`` unchanged, because a second path from a
search snippet to a fact would not stay in agreement with the first.

Pure, like the rest of ``core``. The LLM arrives injected and every call goes through
:mod:`core.transmission`.
"""
from core.analysis.claims import (
    AnalysisFlagCode,
    AnalysisRejectionCode,
    apply_cross_dimension_rules,
    is_established,
    resolve_claim,
    resolve_international,
    source_ids_for,
)
from core.analysis.dimensions import (
    COMPARATOR_DIMENSIONS,
    DIMENSION_CEILING,
    DIMENSION_FRAMEWORK,
    DIMENSION_KIND,
    FRAMEWORK_GROUPS,
    INTERNATIONAL_FRAMEWORK,
    NAMED_ORGANIZATION_DIMENSIONS,
    ROUTE_DIMENSIONS,
    Kind,
    dimensions_for,
)
from core.analysis.models import (
    AnalysisOutcome,
    ClaimDraft,
    ClientResearchCriteria,
    InternationalDraft,
    PartnerProfile,
)
from core.analysis.output_schemas import (
    ALL_OUTPUT_SCHEMAS,
    CLIENT_RESEARCH_CRITERIA,
    INTERNATIONAL_CLAIMS,
    claim_batch_schema,
)
from core.analysis.pipeline import direct_source_ids, persist, run_client_analysis
from core.analysis.policy import (
    DEFAULT_ANALYSIS_POLICY,
    AnalysisPolicy,
    AnalysisPromptSet,
)
from core.analysis.research import build_client_criteria, research_client

__all__ = [
    "ALL_OUTPUT_SCHEMAS",
    "COMPARATOR_DIMENSIONS",
    "CLIENT_RESEARCH_CRITERIA",
    "DEFAULT_ANALYSIS_POLICY",
    "DIMENSION_CEILING",
    "DIMENSION_FRAMEWORK",
    "DIMENSION_KIND",
    "FRAMEWORK_GROUPS",
    "INTERNATIONAL_CLAIMS",
    "INTERNATIONAL_FRAMEWORK",
    "NAMED_ORGANIZATION_DIMENSIONS",
    "ROUTE_DIMENSIONS",
    "AnalysisFlagCode",
    "AnalysisOutcome",
    "AnalysisPolicy",
    "AnalysisPromptSet",
    "AnalysisRejectionCode",
    "ClaimDraft",
    "ClientResearchCriteria",
    "InternationalDraft",
    "Kind",
    "PartnerProfile",
    "apply_cross_dimension_rules",
    "build_client_criteria",
    "claim_batch_schema",
    "dimensions_for",
    "direct_source_ids",
    "is_established",
    "persist",
    "research_client",
    "resolve_claim",
    "resolve_international",
    "run_client_analysis",
    "source_ids_for",
]
