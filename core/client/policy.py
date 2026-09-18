# -*- coding: utf-8 -*-
"""Discovery policy and prompt text. Pure configuration, injected by the caller."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.research.policy import DEFAULT_RESEARCH_POLICY, SNIPPET_LOCATOR, ResearchPolicy


@dataclass(frozen=True)
class DiscoveryPolicy:
    """Limits for one client-discovery run.

    Batching is delegated to the research policy rather than duplicated: the same evidence
    passages are being sent, so the same character budget applies and there is no reason for
    two numbers that have to be kept in step.
    """

    research_policy: ResearchPolicy = DEFAULT_RESEARCH_POLICY

    #: Locator that marks evidence as a search summary rather than a document.
    snippet_locator: str = SNIPPET_LOCATOR

    #: Organizations assessed in one run. A cap, because each one costs a call.
    max_organizations: int = 20

    #: Findings offered as context when assessing one organization.
    max_findings_per_assessment: int = 24

    #: Require every candidate's legal entity to be pinned down before it can be placed first.
    #:
    #: Off by default: for most public-sector buyers the trading name is unambiguous, and
    #: demanding an identifier nobody publishes would push every candidate down a band for no
    #: gain. Turn it on where two firms share a brand.
    require_identity_for_p1: bool = False


DEFAULT_DISCOVERY_POLICY = DiscoveryPolicy()


@dataclass
class ClientPromptSet:
    """Prompt text for each discovery stage, supplied by the caller.

    The core does not read ``prompts/*.md``; ``adapters/prompts/loader.py`` does and passes the
    text in, exactly as for research.
    """

    build_criteria: str
    find_organizations: str
    assess_fit: str
