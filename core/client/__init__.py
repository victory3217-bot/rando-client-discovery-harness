# -*- coding: utf-8 -*-
"""Client discovery and prioritisation — ENGINE 2, first half.

Takes the diagnosis (findings, SWOT items, key issues) and finds organizations worth
approaching, banded by how well the evidence supports approaching them.

The rule that shapes everything here: **a named client comes from evidence, never from a
model's general knowledge**. A name is accepted because it appears, as text, in the passage
cited for it. Asked for companies in a market, a model will produce companies in that market -
plausible, sometimes real, and not evidence of anything.

Pure, like the rest of ``core``. The LLM arrives injected and every call goes through
:mod:`core.transmission`.
"""
from core.client.discover import build_criteria, find_organizations
from core.client.fit import CRITERION_FRAMEWORKS, assess_fit, findings_for
from core.client.models import (
    AccessRoute,
    ClientDiscoveryCriteria,
    DiscoveryHypothesis,
    DiscoveryOutcome,
    FitDraft,
    OrganizationMention,
    PurchaseSignal,
    VerifiedOrganization,
)
from core.client.pipeline import direct_source_ids, persist, run_discovery
from core.client.policy import (
    DEFAULT_DISCOVERY_POLICY,
    ClientPromptSet,
    DiscoveryPolicy,
)
from core.client.priority import (
    COMMERCIAL_CRITERIA,
    CORE_CRITERIA,
    decide_priority,
    has_direct_evidence,
)
from core.client.verify import name_appears_in, normalize, strip_legal_suffix, verify_mentions

__all__ = [
    "AccessRoute",
    "COMMERCIAL_CRITERIA",
    "CORE_CRITERIA",
    "CRITERION_FRAMEWORKS",
    "ClientDiscoveryCriteria",
    "ClientPromptSet",
    "DEFAULT_DISCOVERY_POLICY",
    "DiscoveryHypothesis",
    "DiscoveryOutcome",
    "DiscoveryPolicy",
    "FitDraft",
    "OrganizationMention",
    "PurchaseSignal",
    "VerifiedOrganization",
    "assess_fit",
    "build_criteria",
    "decide_priority",
    "direct_source_ids",
    "find_organizations",
    "findings_for",
    "has_direct_evidence",
    "name_appears_in",
    "normalize",
    "persist",
    "run_discovery",
    "strip_legal_suffix",
    "verify_mentions",
]
