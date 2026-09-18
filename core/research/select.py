# -*- coding: utf-8 -*-
"""Which Master Note frameworks to run against a batch of evidence.

The default is all six, in order. That is not laziness: choosing which framework applies to a
passage *is* an analytical judgement, and making it from keyword overlap would be exactly the
kind of quiet automation that turns a traceable analysis into an opaque one. Running everything
costs six calls per batch and cannot silently drop a dimension nobody thought to look for.

The keyword shortlist exists for deployments where that cost matters. It is off by default, it
only ever narrows the list, and every skipped framework is recorded with a reason so the gap is
visible in the output rather than invisible in the code.

The model never chooses. The pipeline asks about one framework at a time and stamps
``mn_basis`` itself.
"""
from __future__ import annotations

from typing import Iterable, Optional, Sequence

from core.interfaces.knowledge import Framework, KnowledgeProvider
from core.research.policy import DEFAULT_RESEARCH_POLICY, ResearchPolicy


def _keywords(framework: Framework) -> set[str]:
    """Terms drawn from the framework card itself, not a hand-written list.

    Using the card means a framework's vocabulary and its matching rule cannot drift apart.
    """
    terms: set[str] = set()
    for dimension in framework.dimensions:
        terms.add(dimension.key.replace("_", " "))
        for label in (dimension.label_ko, dimension.label_en):
            if label:
                terms.add(label.lower())
    return {term for term in terms if len(term) >= 2}


def shortlist(
    frameworks: Sequence[Framework],
    text: str,
) -> tuple[list[Framework], list[tuple[str, str]]]:
    """Narrow by keyword overlap. Returns the kept frameworks and the skipped ones with reasons.

    If nothing matches, everything is kept: an empty shortlist would mean silently analysing
    nothing, which is worse than analysing too much.
    """
    haystack = text.lower()
    kept: list[Framework] = []
    skipped: list[tuple[str, str]] = []

    for framework in frameworks:
        if any(term in haystack for term in _keywords(framework)):
            kept.append(framework)
        else:
            skipped.append((framework.framework_id, "no dimension term appeared in the batch"))

    if not kept:
        return list(frameworks), []
    return kept, skipped


def frameworks_for(
    knowledge: KnowledgeProvider,
    *,
    policy: ResearchPolicy = DEFAULT_RESEARCH_POLICY,
    requested: Optional[Iterable[str]] = None,
    batch_text: Optional[str] = None,
) -> tuple[list[Framework], list[tuple[str, str]]]:
    """Resolve the frameworks for one batch.

    Precedence: an explicit request from the operator, then the policy's list, then the keyword
    shortlist if it is switched on.
    """
    ids = list(requested) if requested is not None else list(policy.frameworks)
    resolved = [knowledge.get_framework(framework_id) for framework_id in ids]

    if requested is not None or not policy.use_keyword_shortlist or not batch_text:
        return resolved, []

    return shortlist(resolved, batch_text)


def dimension_brief(framework: Framework, lang: str = "ko") -> str:
    """The framework's questions, rendered for a prompt.

    Questions rather than labels: a label invites the model to fill a slot, a question asks it
    to look for something in the evidence.
    """
    lines = [f"{framework.framework_id} — {framework.title(lang)}"]
    for dimension in framework.dimensions:
        question = dimension.question(lang) or dimension.label(lang)
        lines.append(f"- {dimension.key} ({dimension.label(lang)}): {question}")
    return "\n".join(lines)
