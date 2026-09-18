# -*- coding: utf-8 -*-
"""LLM contract.

The core never imports a provider SDK and never holds an API key. It describes what it wants —
a string, or a value matching a schema — and an adapter decides how to get it.

``output_lang`` is a parameter rather than a prompt variant on purpose: the same prompt file
serves Korean and English output, so there is only one prompt to keep correct. Provider
differences (system-message handling, tool use, JSON modes, retries) are absorbed by the
adapter, which is why ``prompts/`` contains no provider names.

Privacy note: this interface is the point where extracted document text leaves the process.
Zero-persistence does not mean zero-transmission — see ``docs/privacy.md``.
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """Text and structured generation.

    Implementations raise :class:`core.errors.StructuredOutputError` when a model's answer
    cannot be made to satisfy the requested schema, instead of returning partial data that
    would later be mistaken for an analysis result.
    """

    #: Short adapter identifier, safe to log (e.g. ``"echo"``, ``"anthropic"``).
    name: str

    def generate(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        output_lang: str = "ko",
    ) -> str:
        """Free-form text. Used for prose that a person will read and edit."""
        ...

    def generate_structured(
        self,
        prompt: str,
        *,
        schema: dict,
        system: Optional[str] = None,
        output_lang: str = "ko",
    ) -> dict:
        """A value satisfying ``schema`` (a JSON Schema object).

        This is the call the analysis stages use, because every stage of this harness produces
        a typed entity rather than prose.
        """
        ...

    def analyze(
        self,
        prompt: str,
        *,
        evidence: list[str],
        schema: dict,
        system: Optional[str] = None,
        output_lang: str = "ko",
    ) -> dict:
        """Structured generation that is explicitly grounded in ``evidence``.

        Separate from :meth:`generate_structured` because the evidence passed here is what the
        result must be traceable to. An adapter is expected to make the grounding explicit to
        the model and to leave fields unanswered rather than filling them from general
        knowledge.
        """
        ...

    def summarize(
        self,
        text: str,
        *,
        output_lang: str = "ko",
        max_sentences: int = 3,
    ) -> str:
        """Condense one passage. Used for ``evidence_summary`` on a finding."""
        ...
