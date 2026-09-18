# -*- coding: utf-8 -*-
"""The one place document text leaves this process.

Research (Phase 3) and client discovery (Phase 4) both send evidence to a provider, and both
go through :func:`send`. One funnel means one place to audit, one place to add redaction if it
is ever needed, and one place that records what went out.

``tests/test_transmission_boundary.py`` parses **every module under ``core/``** and fails if any
of them other than this one calls ``analyze`` or ``generate_structured``. A boundary nobody can
bypass is worth more than a boundary everyone is asked to respect — and scanning all of ``core``
rather than one package means a new engine cannot quietly open a second channel.

Zero-persistence is not zero-transmission, and this harness cannot make promises about what a
provider does with what it receives. Retention, training use, data residency and enterprise
privacy settings are properties of the deployment, not of this code — ``docs/privacy.md`` says
what an operator has to check, and no vendor's policy is hardcoded here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.research.models import EvidenceBlock


@dataclass(frozen=True)
class TransmissionRecord:
    """What was sent, in counts. Never the content.

    Safe to log in full: every field here is a number, an identifier or an adapter name.
    """

    stage: str
    provider: str
    item_count: int
    char_count: int
    framework_id: Optional[str] = None
    grounded: bool = False

    def as_log_fields(self) -> dict:
        return {
            "stage": self.stage,
            "provider": self.provider,
            "item_count": self.item_count,
            "char_count": self.char_count,
            "framework_id": self.framework_id,
            "grounded": self.grounded,
        }


def send(
    llm,
    *,
    stage: str,
    prompt: str,
    schema: dict,
    evidence: Optional[EvidenceBlock] = None,
    items: Optional[list[str]] = None,
    system: Optional[str] = None,
    output_lang: str = "ko",
    framework_id: Optional[str] = None,
) -> tuple[dict, TransmissionRecord]:
    """Call the configured provider and record that it happened.

    ``evidence`` routes to :meth:`LLMProvider.analyze`, which is the grounded call: the result
    has to be traceable to those passages. ``items`` routes to
    :meth:`LLMProvider.generate_structured`, used by the SWOT and key-issue stages, whose input
    is findings rather than raw document text.

    Returns the parsed result and the record. The caller decides whether the record is logged —
    the core does not log.
    """
    provider_name = getattr(llm, "name", "unknown")

    if evidence is not None:
        lines = evidence.lines()
        record = TransmissionRecord(
            stage=stage,
            provider=provider_name,
            item_count=len(lines),
            char_count=evidence.char_count,
            framework_id=framework_id,
            grounded=True,
        )
        result = llm.analyze(
            prompt,
            evidence=lines,
            schema=schema,
            system=system,
            output_lang=output_lang,
        )
        return result, record

    payload = items or []
    record = TransmissionRecord(
        stage=stage,
        provider=provider_name,
        item_count=len(payload),
        char_count=sum(len(line) for line in payload),
        framework_id=framework_id,
        grounded=False,
    )
    body = prompt if not payload else prompt + "\n\n" + "\n".join(payload)
    result = llm.generate_structured(
        body,
        schema=schema,
        system=system,
        output_lang=output_lang,
    )
    return result, record
