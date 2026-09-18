# -*- coding: utf-8 -*-
"""Building the search specification, and finding organizations the evidence actually names."""
from __future__ import annotations

from typing import Optional, Sequence

from core.client.models import (
    AccessRoute,
    ClientDiscoveryCriteria,
    DiscoveryHypothesis,
    OrganizationMention,
    PurchaseSignal,
    VerifiedOrganization,
)
from core.client.output_schemas import DISCOVERY_CRITERIA, ORGANIZATION_MENTIONS
from core.client.policy import DEFAULT_DISCOVERY_POLICY, ClientPromptSet, DiscoveryPolicy
from core.client.verify import find_span, name_appears_in, verify_mentions
from core.research.models import Rejection, RejectionCode
from core.research.extract import build_evidence_block
from core.models import KeyIssue, ResearchFinding, SourceMetadata
from core.transmission import send


def build_criteria(
    findings: Sequence[ResearchFinding],
    key_issues: Sequence[KeyIssue],
    *,
    llm,
    prompts: ClientPromptSet,
    project_id: str,
    capability: str,
    solution: str,
    output_lang: str = "ko",
    policy: DiscoveryPolicy = DEFAULT_DISCOVERY_POLICY,
) -> tuple[Optional[ClientDiscoveryCriteria], list]:
    """Decide what kind of organization to look for, before looking for any.

    Searching for companies first and justifying them afterwards is how an industry list gets
    mistaken for a discovery result.
    """
    if not findings and not key_issues:
        return None, []

    lines = [f"[F{i}] {f.finding}" for i, f in enumerate(findings, start=1)]
    lines += [f"[K{i}] {k.statement} ({k.decision_area})" for i, k in enumerate(key_issues, 1)]
    lines.append(f"[CAPABILITY] {capability}")
    lines.append(f"[SOLUTION] {solution}")

    result, record = send(
        llm,
        stage="build_criteria",
        prompt=prompts.build_criteria,
        schema=DISCOVERY_CRITERIA,
        items=lines,
        output_lang=output_lang,
    )
    if not isinstance(result, dict) or not result:
        return None, [record]

    criteria = ClientDiscoveryCriteria(
        project_id=project_id,
        target_country=_text(result.get("target_country")),
        target_region=_text(result.get("target_region")),
        target_industry=_text(result.get("target_industry")),
        relevant_problem=_text(result.get("relevant_problem")),
        problem_severity_signal=_text(result.get("problem_severity_signal")),
        required_buyer_type=_text(result.get("required_buyer_type")),
        possible_decision_maker=_text(result.get("possible_decision_maker")),
        our_capability=_text(result.get("our_capability")) or capability,
        our_solution=_text(result.get("our_solution")) or solution,
        required_solution_fit=_text(result.get("required_solution_fit")),
        purchase_signal=_enums(result.get("purchase_signal"), PurchaseSignal),
        budget_signal=_text(result.get("budget_signal")),
        procurement_signal=_text(result.get("procurement_signal")),
        access_signal=_enums(result.get("access_signal"), AccessRoute),
        channel_signal=_text(result.get("channel_signal")),
        partner_signal=_text(result.get("partner_signal")),
        competitive_condition=_text(result.get("competitive_condition")),
        exclusion_condition=_strings(result.get("exclusion_condition")),
        required_evidence=_strings(result.get("required_evidence")),
        # Provenance is the pipeline's, not the model's.
        finding_ids=[f.finding_id for f in findings],
        key_issue_ids=[k.key_issue_id for k in key_issues],
        mn_basis=_union(f.mn_basis for f in findings),
    )
    return criteria, [record]


def find_organizations(
    candidates: Sequence,
    *,
    llm,
    prompts: ClientPromptSet,
    sources_by_id: dict[str, SourceMetadata],
    criteria: Optional[ClientDiscoveryCriteria] = None,
    output_lang: str = "ko",
    policy: DiscoveryPolicy = DEFAULT_DISCOVERY_POLICY,
) -> tuple[list[VerifiedOrganization], list[DiscoveryHypothesis], list[Rejection], list]:
    """Extract organization names from evidence, and keep only the ones the evidence contains.

    The verification step is what separates this from asking a model for companies in a market.
    A name is accepted because it is present in the passage that was cited for it, not because
    a model produced it — so an invented firm, however plausible, has no way through.
    """
    if not candidates:
        return [], [], [], []

    block = build_evidence_block(candidates, policy.research_policy)
    prompt = prompts.find_organizations
    if criteria is not None:
        prompt = f"{prompt}\n\n## What we are looking for\n{_criteria_brief(criteria)}"

    result, record = send(
        llm,
        stage="find_organizations",
        prompt=prompt,
        schema=ORGANIZATION_MENTIONS,
        evidence=block,
        output_lang=output_lang,
    )

    mentions: list[OrganizationMention] = []
    rejections: list[Rejection] = []

    for raw in result.get("mentions") or []:
        if not isinstance(raw, dict):
            rejections.append(Rejection("find_organizations", RejectionCode.ITEM_NOT_AN_OBJECT))
            continue

        name = (raw.get("name") or "").strip()
        ref = raw.get("evidence_ref")
        if not name:
            rejections.append(Rejection("find_organizations", RejectionCode.EMPTY_STATEMENT))
            continue

        entry = block.resolve(ref) if isinstance(ref, str) else None
        if entry is None:
            rejections.append(
                Rejection("find_organizations", RejectionCode.UNKNOWN_EVIDENCE_REF, ref)
            )
            continue

        if not name_appears_in(name, entry.text):
            # The characteristic failure: a real-sounding company the evidence never mentions.
            rejections.append(
                Rejection("find_organizations", RejectionCode.NAME_NOT_IN_EVIDENCE, ref)
            )
            continue

        source = sources_by_id.get(entry.candidate.source_id)
        if source is None:
            rejections.append(
                Rejection("find_organizations", RejectionCode.NO_SOURCE_RECORD, ref)
            )
            continue

        mentions.append(
            OrganizationMention(
                name=name,
                evidence_ref=entry.ref,
                source_id=source.source_id,
                locator=entry.candidate.locator,
                verbatim=find_span(name, entry.text),
            )
        )

    hypotheses: list[DiscoveryHypothesis] = []
    for raw in result.get("hypotheses") or []:
        if not isinstance(raw, dict):
            continue
        profile = (raw.get("organization_profile") or "").strip()
        if not profile:
            continue
        hypotheses.append(
            DiscoveryHypothesis(
                organization_profile=profile,
                rationale=_text(raw.get("rationale")),
                required_evidence=_strings(raw.get("required_evidence")),
                key_issue_ids=list(criteria.key_issue_ids) if criteria else [],
            )
        )

    organizations = verify_mentions(mentions, snippet_locator=policy.snippet_locator)
    return organizations, hypotheses, rejections, [record]


def _criteria_brief(criteria: ClientDiscoveryCriteria) -> str:
    parts = [
        ("industry", criteria.target_industry),
        ("country", criteria.target_country),
        ("problem", criteria.relevant_problem),
        ("buyer", criteria.required_buyer_type),
    ]
    return "\n".join(f"- {label}: {value}" for label, value in parts if value)


def _text(value) -> Optional[str]:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _strings(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [v.strip() for v in value if isinstance(v, str) and v.strip()]


def _enums(value, enum_cls) -> list:
    out = []
    for item in _strings(value):
        try:
            out.append(enum_cls(item))
        except ValueError:
            continue
    return out


def _union(lists) -> list[str]:
    seen: list[str] = []
    for values in lists:
        for value in values:
            if value not in seen:
                seen.append(value)
    return seen
